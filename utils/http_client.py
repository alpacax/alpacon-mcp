"""HTTP client for Alpacon API interactions."""

import asyncio
import json
import logging
from http import HTTPStatus
from types import TracebackType
from typing import Self
from urllib.parse import urljoin, urlsplit

import httpx

from utils import mfa_step_up, request_signal
from utils.common import MCP_USER_AGENT, is_auth_enabled
from utils.declared_agent import declared_agent_headers
from utils.error_handler import UpstreamAuthError
from utils.logger import get_logger, redact_for_log
from utils.types import JsonValue, QueryParams, RequestBody

logger = get_logger('http_client')

# Pinned values: tests assert these verbatim; callers only check that 'error' exists.
_ERR_HTTP = 'HTTP Error'
_ERR_MAX_RETRIES = 'Max retries exceeded'
_ERR_MFA_REQUIRED = 'MFA Required'
_ERR_REQUEST = 'Request Error'
_ERR_TIMEOUT = 'Timeout'
_ERR_UNEXPECTED = 'Unexpected Error'

# A fresh MFA an action demands: a browser step-up clears it, the same token retries.
_MFA_STEP_UP_CODE = 'auth_mfa_required'

# The workspace's sign-in MFA the token lacks: only a new Auth0 sign-in adds it.
_MFA_SIGN_IN_CODE = 'auth_token_mfa_missing'

# A replay of these can repeat a side effect, and alpacon-server takes no idempotency key:
# they are resent only after an error raised before the request reached the server.
_NON_IDEMPOTENT_METHODS = frozenset({'POST', 'PATCH'})
# Raised before the request reaches Alpacon.
# LocalProtocolError is left out: h11 can raise it mid-body.
_NEVER_SENT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ProxyError,
    httpx.UnsupportedProtocol,
)
# 5xx codes alpacon-server answers while checking the credential, before any view runs.
_REJECTED_BEFORE_VIEW_CODES = frozenset({'auth_verification_unavailable'})


def _error_code_of(text: str) -> str | None:
    """The `code` of a JSON object error body; None for HTML, arrays or no code."""
    try:
        body = json.loads(text)
    except ValueError:
        return None
    code = body.get('code') if isinstance(body, dict) else None
    return code if isinstance(code, str) and code else None


def _error_body_for_log(response: httpx.Response) -> object:
    """An upstream error body by its field names, or by its size if not JSON."""
    try:
        return redact_for_log(response.json())
    except ValueError:
        return redact_for_log(response.text)


def _may_act_twice(
    idempotent: bool, error: httpx.HTTPError, code: str | None = None
) -> bool:
    """Whether resending after `error` could repeat what the server already did;
    ``code`` is the 5xx body's error code, already parsed by the caller."""
    if idempotent or isinstance(error, _NEVER_SENT_ERRORS):
        return False
    if isinstance(error, httpx.HTTPStatusError):
        return code not in _REJECTED_BEFORE_VIEW_CODES
    return True


def _outcome_unknown(
    method: str, reason: str, **fields: JsonValue
) -> dict[str, JsonValue]:
    """Error dict for a POST or PATCH that may have reached the server."""
    return {
        **fields,
        'message': (
            f'{reason}. The {method} was not resent: the server may already '
            'have acted on it.'
        ),
        'outcome_unknown': True,
    }


async def _refuse_before_send(event: str, info: dict[str, object]) -> None:
    # An httpcore trace hook: past the connection pool wait, before the first byte.
    if event.endswith('.send_request_headers.started'):
        mfa_step_up.refuse_if_recorded()


class AlpaconHTTPClient:
    """Pooled async client for the Alpacon API. It never caches a response: reads are
    filtered by the token's permissions, so a hit could outlive a revoked grant."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        """``transport`` replaces the network under the pooled client."""
        self._transport = transport
        self.base_timeout = httpx.Timeout(10.0, connect=5.0)
        self.max_retries = 3
        self.retry_delay = 1.0
        self.max_retry_delay = 30.0
        self.backoff_multiplier = 2.0

        # Connection pooling
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

        logger.info(
            'AlpaconHTTPClient initialized - timeout: %ss, max_retries: %s',
            self.base_timeout.read,
            self.max_retries,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._close_client()

    # __del__ removed: lifespan handles cleanup via close()

    async def close(self) -> None:
        """Close the pool; safe to call more than once."""
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
                logger.debug('Closed HTTP client')
        logger.info('HTTP client closed')

    async def _close_client(self) -> None:
        await self.close()

    @property
    def pool_active(self) -> bool:
        return self._client is not None and not self._client.is_closed

    def get_base_url(self, region: str, workspace: str) -> str:
        """Base URL: a configured override (token.json or
        ALPACON_MCP_<REGION>_<WORKSPACE>_URL), else derived."""
        # Local import keeps the singleton lazy and lets tests patch
        # get_token_manager; the isinstance guard tolerates a mocked manager
        # whose override method returns a non-string sentinel.
        from utils.token_manager import get_token_manager

        override = get_token_manager().get_base_url_override(region, workspace)
        if isinstance(override, str) and override:
            logger.debug('Using configured base URL override: %s', override)
            return override

        base_url = f'https://{workspace}.{region}.alpacon.io'
        logger.debug('Generated base URL: %s', base_url)
        return base_url

    async def request(
        self,
        method: str,
        url: str,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        json_data: RequestBody | None = None,
        params: QueryParams | None = None,
        timeout: float | None = None,
        *,
        reauth_on_401: bool = True,
    ) -> JsonValue:
        """Send with retry, but never resend a POST or PATCH that may have reached the
        server. Raises UpstreamAuthError on a 401 in remote JWT mode unless
        `reauth_on_401` is off, for a JWT that is not the session's own."""
        # Prepare headers
        request_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': MCP_USER_AGENT,
            # The agent behind this request, as it reported itself (#317).
            **declared_agent_headers(),
        }

        if token:
            if self._is_jwt(token):
                request_headers['Authorization'] = f'Bearer {token}'
            else:
                request_headers['Authorization'] = f'token={token}'

        if headers:
            request_headers.update(headers)

        # Set timeout
        request_timeout = httpx.Timeout(timeout or 10.0, connect=5.0)
        idempotent = method.upper() not in _NON_IDEMPOTENT_METHODS

        # Retry logic
        retry_count = 0
        retry_delay = self.retry_delay

        async def backoff(reason: str) -> bool:
            nonlocal retry_count, retry_delay
            retry_count += 1
            if retry_count >= self.max_retries:
                # Check before the log: no retry follows, and the caller logs the exhaustion.
                return False
            logger.warning(
                '%s, retrying (%s/%s) in %ss',
                reason,
                retry_count,
                self.max_retries,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(
                retry_delay * self.backoff_multiplier, self.max_retry_delay
            )
            return True

        logger.info('HTTP %s request to %s', method, url)
        # Names and sizes only: a body carries the command a call runs, and
        # the params the text a caller filtered by.
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug('Request headers: %s', sorted(request_headers))
            if params:
                logger.debug('Request params: %s', redact_for_log(params))
            if json_data:
                logger.debug('Request body: %s', redact_for_log(json_data))

        while retry_count < self.max_retries:
            mfa_step_up.refuse_if_recorded()  # a refused call adds no side effects
            try:
                client = await self._get_client()
                response = await client.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    json=json_data,
                    params=params,
                    timeout=request_timeout,
                    extensions={'trace': _refuse_before_send},
                )

                # Check for success
                response.raise_for_status()
                if not idempotent:
                    mfa_step_up.note_sent(f'{method.upper()} {urlsplit(url).path}')

                # Log successful response
                logger.info(
                    'HTTP %s success - Status: %s, Content-Length: %s',
                    method,
                    response.status_code,
                    len(response.content),
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug('Response headers: %s', sorted(response.headers))

                # Return JSON response
                if response.content:
                    result: JsonValue = response.json()
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug('Response body: %s', redact_for_log(result))
                    return result
                else:
                    result = {'status': 'success', 'status_code': response.status_code}
                    logger.debug('Empty response, returning: %s', result)
                    return result

            except httpx.HTTPStatusError as e:
                # Handle HTTP errors (4xx, 5xx)
                logger.error(
                    'HTTP %s error - Status: %s, URL: %s',
                    method,
                    e.response.status_code,
                    url,
                )
                # Field names only, never the text: an upstream error can
                # echo back what the request sent. A 401 logs nothing here.
                if e.response.status_code != HTTPStatus.UNAUTHORIZED:
                    logger.error('Response body: %s', _error_body_for_log(e.response))

                if e.response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                    code = _error_code_of(e.response.text)
                    code_field: dict[str, JsonValue] = (
                        {'error_code': code} if code else {}
                    )
                    if _may_act_twice(idempotent, e, code):  # already logged above
                        return _outcome_unknown(
                            method,
                            f'Server error {e.response.status_code}',
                            error=_ERR_HTTP,
                            status_code=e.response.status_code,
                            **code_field,
                        )

                    # Server error - retry
                    if await backoff('Server error'):
                        continue

                    error_response: dict[str, JsonValue] = {
                        'error': _ERR_MAX_RETRIES,
                        'status_code': e.response.status_code,
                        'message': f'Server error after {self.max_retries} attempts',
                        **code_field,
                    }
                    logger.error('Server error after all retries: %s', error_response)
                    return error_response
                else:
                    # Client error - don't retry
                    if (
                        e.response.status_code == HTTPStatus.UNAUTHORIZED
                        and reauth_on_401
                    ):
                        return self._handle_upstream_401(e, token=token)

                    error_response = {
                        'error': _ERR_HTTP,
                        'status_code': e.response.status_code,
                        'message': str(e),
                        'response': e.response.text,
                    }
                    logger.error(
                        'Client error, not retrying - Status: %s',
                        e.response.status_code,
                    )
                    return error_response

            except httpx.RequestError as e:
                timed_out = isinstance(e, httpx.TimeoutException)
                reason = 'Request timed out' if timed_out else f'Network error: {e}'
                if _may_act_twice(idempotent, e):
                    logger.error('%s: %s, not resending', method, reason)
                    return _outcome_unknown(
                        method,
                        reason,
                        error=_ERR_TIMEOUT if timed_out else _ERR_REQUEST,
                    )

                # Timeout or network error - retry
                if await backoff(reason):
                    continue

                if timed_out:
                    error_response = {
                        'error': _ERR_TIMEOUT,
                        'message': f'Request timed out after {self.max_retries} retries',
                    }
                    logger.error(
                        'Request timeout after all retries: %s', error_response
                    )
                else:
                    error_response = {'error': _ERR_REQUEST, 'message': str(e)}
                    logger.error('Network error after all retries: %s', error_response)
                return error_response

            except mfa_step_up.MfaStepUpRequired:
                raise  # raised before the request was sent

            except Exception as e:
                # Unexpected error - don't retry
                logger.exception('Unexpected error: %s', e)
                # It may have run: a 2xx whose body failed to parse lands here.
                if not idempotent:
                    return _outcome_unknown(
                        method, f'Unexpected error: {e}', error=_ERR_UNEXPECTED
                    )
                return {'error': _ERR_UNEXPECTED, 'message': str(e)}

        # Every branch above returns, so this is only reached when max_retries <= 0
        error_response = {
            'error': _ERR_MAX_RETRIES,
            'message': f'Failed after {self.max_retries} attempts',
        }
        logger.error('Loop never ran - max_retries is %s', self.max_retries)
        return error_response

    async def get(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str | None = None,
        params: QueryParams | None = None,
    ) -> JsonValue:
        """GET; returns the parsed JSON body or an error dict."""
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method='GET', url=full_url, token=token, params=params
        )

    async def post(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str | None = None,
        data: RequestBody | None = None,
        params: QueryParams | None = None,
    ) -> JsonValue:
        """POST; returns the parsed JSON body or an error dict."""
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method='POST', url=full_url, token=token, json_data=data, params=params
        )

    async def put(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str | None = None,
        data: RequestBody | None = None,
    ) -> JsonValue:
        """PUT; returns the parsed JSON body or an error dict."""
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method='PUT', url=full_url, token=token, json_data=data
        )

    async def patch(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str | None = None,
        data: RequestBody | None = None,
    ) -> JsonValue:
        """PATCH; returns the parsed JSON body or an error dict."""
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method='PATCH', url=full_url, token=token, json_data=data
        )

    async def delete(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str | None = None,
        params: QueryParams | None = None,
    ) -> JsonValue:
        """DELETE; returns the parsed JSON body or an error dict."""
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method='DELETE', url=full_url, token=token, params=params
        )

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=self.base_timeout,
                    transport=self._transport,
                    limits=httpx.Limits(
                        max_keepalive_connections=20,
                        max_connections=100,
                        keepalive_expiry=30.0,
                    ),
                )
                logger.debug('Created new HTTP client with connection pooling')
            return self._client

    @staticmethod
    def _is_jwt(token: str) -> bool:
        parts = token.split('.')
        return len(parts) == 3 and all(parts)

    @staticmethod
    def _handle_upstream_401(
        exc: httpx.HTTPStatusError, token: str | None = None
    ) -> dict[str, JsonValue]:
        """Map an upstream 401 to an MFA-aware error dict. With a JWT in remote mode it raises
        MfaStepUpRequired on auth_mfa_required, else UpstreamAuthError after the signal."""
        code: object = None
        raw_source: object = None

        try:
            body = exc.response.json()
            if isinstance(body, dict):
                code = body.get('code')
                raw_source = body.get('source')
        except Exception as parse_exc:
            logger.debug('Failed to parse 401 response body as JSON: %s', parse_exc)

        step_up = code == _MFA_STEP_UP_CODE
        mfa_required = step_up or code == _MFA_SIGN_IN_CODE
        source = raw_source if mfa_required and isinstance(raw_source, str) else ''

        auth_enabled = is_auth_enabled()
        is_jwt = bool(token and AlpaconHTTPClient._is_jwt(token))
        # Only a JWT-carrying request may signal: the middleware trusts that and
        # checks the signal without knowing which credential produced it.
        signals = bool(auth_enabled and is_jwt)

        logger.debug(
            'Upstream 401 - auth_enabled=%s, token_present=%s, is_jwt=%s, '
            'mfa_required=%s, source=%s, signaling=%s',
            auth_enabled,
            bool(token),
            is_jwt,
            mfa_required,
            source,
            signals,
        )

        if signals and step_up:
            # No request_signal entry here: any entry there replaces the response
            # with a re-auth challenge.
            mfa_step_up.record(source)
            raise mfa_step_up.MfaStepUpRequired(source)

        if signals:
            request_signal.signal_upstream_auth_error(
                {
                    'mfa_required': mfa_required,
                    'source': source,
                },
            )
            raise UpstreamAuthError(mfa_required=mfa_required, source=source)

        error_msg = 'MFA verification required' if mfa_required else str(exc)
        error_response: dict[str, JsonValue] = {
            'error': _ERR_MFA_REQUIRED if mfa_required else _ERR_HTTP,
            'status_code': HTTPStatus.UNAUTHORIZED,
            'message': error_msg,
            'mfa_required': mfa_required,
        }
        logger.error(
            'Upstream 401 (mfa_required=%s, source=%s), not retrying',
            mfa_required,
            source,
        )
        return error_response


# Singleton instance
http_client = AlpaconHTTPClient()
