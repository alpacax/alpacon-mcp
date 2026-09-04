"""HTTP client for Alpacon API interactions."""

import asyncio
import logging
from http import HTTPStatus
from typing import Any
from urllib.parse import urljoin

import httpx

from utils.common import MCP_USER_AGENT, is_auth_enabled
from utils.error_handler import (
    UpstreamAuthError,
    make_auth_error_key,
    signal_upstream_auth_error,
)
from utils.logger import get_logger

logger = get_logger('http_client')

# Pinned values: tests assert these verbatim; callers only check that 'error' exists.
_ERR_HTTP = 'HTTP Error'
_ERR_MAX_RETRIES = 'Max retries exceeded'
_ERR_MFA_REQUIRED = 'MFA Required'
_ERR_REQUEST = 'Request Error'
_ERR_REQUEST_EXCEPTION = 'Request Exception'
_ERR_TIMEOUT = 'Timeout'
_ERR_UNEXPECTED = 'Unexpected Error'


class AlpaconHTTPClient:
    """Async HTTP client for Alpacon API with connection pooling.

    Responses are never cached. Every endpoint worth caching here—the server
    list, process info, IAM users and groups—comes back filtered by the calling
    token's permissions, and no in-process scheme can see a grant revoked
    elsewhere (the web console, Slack, another MCP process), so a cached read
    would keep answering with access the caller has already lost.
    """

    def __init__(self):
        """Initialize HTTP client."""
        self.base_timeout = httpx.Timeout(10.0, connect=5.0)
        self.max_retries = 3
        self.retry_delay = 1.0
        self.max_retry_delay = 30.0
        self.backoff_multiplier = 2.0

        # Connection pooling
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

        logger.info(
            f'AlpaconHTTPClient initialized - timeout: {self.base_timeout.read}s, max_retries: {self.max_retries}'
        )

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close client."""
        await self._close_client()

    # __del__ removed: lifespan handles cleanup via close()

    async def close(self):
        """Close the HTTP client.

        This is the primary public method for cleanup. Safe to call
        multiple times (idempotent).
        """
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
                logger.debug('Closed HTTP client')
        logger.info('HTTP client closed')

    async def _close_client(self):
        """Close the shared client. Alias for close() for backward compatibility."""
        await self.close()

    @property
    def pool_active(self) -> bool:
        """Whether the HTTP connection pool has an active client."""
        return self._client is not None and not self._client.is_closed

    def get_base_url(self, region: str, workspace: str) -> str:
        """Get base URL for API calls.

        Prefers an explicitly configured base URL (token.json object form or the
        ``ALPACON_MCP_<REGION>_<WORKSPACE>_URL`` env var) so the host is a pinned,
        persisted value rather than one re-derived from the workspace label on
        every call. This keeps a workspace addressable across a URL slug change
        (ADR 0027), where a freed slug can later be reused by another workspace.
        Falls back to the default Alpacon Cloud host derivation.

        Args:
            region: Region (ap1, us1)
            workspace: Workspace name

        Returns:
            Base URL for API calls
        """
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
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Full URL for the request
            token: API token for authentication
            headers: Additional headers
            json_data: JSON data for request body
            params: Query parameters
            timeout: Request timeout in seconds

        Returns:
            Response data as dictionary

        Raises:
            httpx.HTTPError: If request fails after retries
        """
        # Prepare headers
        request_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': MCP_USER_AGENT,
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

        # Retry logic
        retry_count = 0
        retry_delay = self.retry_delay

        async def backoff(reason: str) -> bool:
            """False once retries are exhausted."""
            nonlocal retry_count, retry_delay
            retry_count += 1
            if retry_count >= self.max_retries:
                # Check before the log: no retry follows, and the caller logs the exhaustion.
                return False
            logger.warning(
                f'{reason}, retrying ({retry_count}/{self.max_retries}) in {retry_delay}s'
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(
                retry_delay * self.backoff_multiplier, self.max_retry_delay
            )
            return True

        logger.info('HTTP %s request to %s', method, url)
        if logger.isEnabledFor(logging.DEBUG):
            redacted_headers = {
                k: (v if k != 'Authorization' else '[REDACTED]')
                for k, v in request_headers.items()
            }
            logger.debug('Request headers: %s', redacted_headers)
        if params:
            logger.debug('Request params: %s', params)
        if json_data:
            logger.debug('Request body: %s', json_data)

        while retry_count < self.max_retries:
            try:
                client = await self._get_client()
                response = await client.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    json=json_data,
                    params=params,
                    timeout=request_timeout,
                )

                # Check for success
                response.raise_for_status()

                # Log successful response
                logger.info(
                    'HTTP %s success - Status: %s, Content-Length: %s',
                    method,
                    response.status_code,
                    len(response.content),
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug('Response headers: %s', dict(response.headers))

                # Return JSON response
                if response.text:
                    result = response.json()
                    logger.debug('Response body: %s', result)
                    return result
                else:
                    result = {'status': 'success', 'status_code': response.status_code}
                    logger.debug('Empty response, returning: %s', result)
                    return result

            except httpx.HTTPStatusError as e:
                # Handle HTTP errors (4xx, 5xx)
                logger.error(
                    f'HTTP {method} error - Status: {e.response.status_code}, URL: {url}'
                )
                # Omit response body for 401 to avoid leaking auth error details/PII
                if e.response.status_code != HTTPStatus.UNAUTHORIZED:
                    logger.error(f'Response body: {e.response.text}')

                if e.response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                    # Server error - retry
                    if await backoff('Server error'):
                        continue

                    error_response = {
                        'error': _ERR_MAX_RETRIES,
                        'status_code': e.response.status_code,
                        'message': f'Server error after {self.max_retries} attempts',
                    }
                    logger.error(f'Server error after all retries: {error_response}')
                    return error_response
                else:
                    # Client error - don't retry
                    if e.response.status_code == HTTPStatus.UNAUTHORIZED:
                        return self._handle_upstream_401(e, token=token)

                    error_response = {
                        'error': _ERR_HTTP,
                        'status_code': e.response.status_code,
                        'message': str(e),
                        'response': e.response.text,
                    }
                    logger.error(f'Client error, not retrying: {error_response}')
                    return error_response

            except httpx.TimeoutException:
                # Timeout - retry
                if await backoff('Request timeout'):
                    continue

                error_response = {
                    'error': _ERR_TIMEOUT,
                    'message': f'Request timed out after {self.max_retries} retries',
                }
                logger.error(f'Request timeout after all retries: {error_response}')
                return error_response

            except httpx.RequestError as e:
                # Network error - retry
                if await backoff(f'Network error: {e}'):
                    continue

                error_response = {'error': _ERR_REQUEST, 'message': str(e)}
                logger.error(f'Network error after all retries: {error_response}')
                return error_response

            except Exception as e:
                # Unexpected error - don't retry
                error_response = {'error': _ERR_UNEXPECTED, 'message': str(e)}
                logger.error(f'Unexpected error: {error_response}', exc_info=True)
                return error_response

        # Every branch above returns, so this is only reached when max_retries <= 0
        error_response = {
            'error': _ERR_MAX_RETRIES,
            'message': f'Failed after {self.max_retries} attempts',
        }
        logger.error(f'Loop never ran - max_retries is {self.max_retries}')
        return error_response

    async def batch_request(
        self, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Execute multiple requests in parallel.

        Args:
            requests: List of request dictionaries with keys:
                - method: HTTP method
                - region: Region
                - workspace: Workspace
                - endpoint: API endpoint
                - token: API token
                - params: Optional query parameters
                - data: Optional request body data

        Returns:
            List of response dictionaries in the same order as requests
        """
        if not requests:
            return []

        logger.info(f'Executing {len(requests)} requests in parallel')

        # Create tasks for parallel execution
        tasks = []
        for req in requests:
            if req['method'].upper() == 'GET':
                task = self.get(
                    region=req['region'],
                    workspace=req['workspace'],
                    endpoint=req['endpoint'],
                    token=req['token'],
                    params=req.get('params'),
                )
            elif req['method'].upper() == 'POST':
                task = self.post(
                    region=req['region'],
                    workspace=req['workspace'],
                    endpoint=req['endpoint'],
                    token=req['token'],
                    data=req.get('data'),
                    params=req.get('params'),
                )
            else:
                # For other methods, use the generic request method
                base_url = self.get_base_url(req['region'], req['workspace'])
                full_url = urljoin(base_url, req['endpoint'])
                task = self.request(
                    method=req['method'],
                    url=full_url,
                    token=req['token'],
                    json_data=req.get('data'),
                    params=req.get('params'),
                )
            tasks.append(task)

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error dictionaries
        processed_results: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    {
                        'error': _ERR_REQUEST_EXCEPTION,
                        'message': str(result),
                        'request_index': i,
                    }
                )
            elif isinstance(result, BaseException):
                raise result  # Re-raise CancelledError, KeyboardInterrupt, etc.
            else:
                processed_results.append(result)

        logger.info(f'Completed {len(requests)} parallel requests')
        return processed_results

    async def get(
        self,
        region: str,
        workspace: str,
        endpoint: str,
        token: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute GET request.

        Args:
            region: Region (ap1, us1)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            params: Query parameters

        Returns:
            Response data
        """
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
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute POST request.

        Args:
            region: Region (ap1, us1)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            data: Request body data
            params: Query parameters

        Returns:
            Response data
        """
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
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute PUT request.

        Args:
            region: Region (ap1, us1)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            data: Request body data

        Returns:
            Response data
        """
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
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute PATCH request.

        Args:
            region: Region (ap1, us1)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            data: Request body data

        Returns:
            Response data
        """
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
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute DELETE request.

        Args:
            region: Region (ap1, us1)
            workspace: Workspace name
            endpoint: API endpoint path
            token: API token
            params: Query parameters

        Returns:
            Response data
        """
        base_url = self.get_base_url(region, workspace)
        full_url = urljoin(base_url, endpoint)

        return await self.request(
            method='DELETE', url=full_url, token=token, params=params
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create shared async client for connection pooling."""
        # For testing compatibility, check if client pooling is disabled
        if hasattr(self, '_disable_pooling') and self._disable_pooling:
            return httpx.AsyncClient(timeout=self.base_timeout)

        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=self.base_timeout,
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
        """Check if a token is a JWT (header.payload.signature format)."""
        parts = token.split('.')
        return len(parts) == 3 and all(parts)

    @staticmethod
    def _handle_upstream_401(
        exc: httpx.HTTPStatusError, token: str | None = None
    ) -> dict[str, Any]:
        """Handle upstream API 401 responses.

        Detects MFA-required errors from the Alpacon API response body
        and triggers re-authentication in remote (streamable-http) mode
        via two complementary mechanisms:

        1. Dict-based signal: Sets a module-level flag keyed by token hash
           that the ASGI middleware consumes after the request completes.
        2. Exception: Raises UpstreamAuthError which propagates through
           the call stack to the middleware's try/except handler.

        The exception path is the primary mechanism (more reliable across
        anyio task boundaries). The dict signal is a fallback for edge
        cases where the exception might be caught by intermediate handlers.

        In stdio/SSE mode (auth not enabled), only returns an error dict
        without signaling or raising.
        """
        mfa_required = False
        source = ''

        try:
            body = exc.response.json()
            if isinstance(body, dict) and body.get('code') == 'auth_mfa_required':
                mfa_required = True
                source = body.get('source', '')
        except Exception as parse_exc:
            logger.debug('Failed to parse 401 response body as JSON: %s', parse_exc)

        auth_enabled = is_auth_enabled()
        is_jwt = bool(token and AlpaconHTTPClient._is_jwt(token))

        logger.debug(
            '[DEBUG-401] auth_enabled=%s, token_present=%s, is_jwt=%s, '
            'mfa_required=%s, source=%s',
            auth_enabled,
            bool(token),
            is_jwt,
            mfa_required,
            source,
        )

        # Token-hash dict, not contextvars: streamable-http runs handlers in a separate anyio task where ContextVar writes are invisible to the ASGI middleware.
        # JWT only — the middleware cannot derive a matching key from API tokens, so their entries would go unconsumed.
        if auth_enabled and token and is_jwt:
            token_key = make_auth_error_key(token)
            logger.debug(
                '[DEBUG-401] Setting dict signal with token_key=%s',
                token_key,
            )
            signal_upstream_auth_error(
                token_key,
                {
                    'mfa_required': mfa_required,
                    'source': source,
                },
            )
            logger.debug(
                '[DEBUG-401] Raising UpstreamAuthError (mfa_required=%s, source=%s)',
                mfa_required,
                source,
            )
            raise UpstreamAuthError(mfa_required=mfa_required, source=source)

        logger.debug(
            '[DEBUG-401] NOT signaling/raising — falling through to error dict. '
            'auth_enabled=%s, is_jwt=%s',
            auth_enabled,
            is_jwt,
        )
        error_msg = 'MFA verification required' if mfa_required else str(exc)
        error_response = {
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
