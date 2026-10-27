"""ASGI middleware to turn an upstream API 401 into an MCP transport challenge.

When the Alpacon API returns 401, this middleware intercepts the error and
answers with a WWW-Authenticate challenge that starts the MCP client's OAuth
re-authentication: 401 for an expired credential, 403 insufficient_scope when
the API wants MFA (see ``_send_challenge``).

The middleware plants an empty signal dict in a ContextVar at the start of
each request; ``http_client`` and the MFA pre-check mutate that same object
from the tool handler's task. The signal is read when the first body chunk
arrives, while the start message is still held; a response with no body
falls back to a check after ``self.app()`` returns. SDK 2.x turns a handler
exception into a wire response, so ``UpstreamAuthError`` only reaches the
``except`` branch from a caller that invokes this app directly.

Only active in remote (streamable-http) mode where OAuth is enabled.
"""

import hashlib
import json
import time
from collections.abc import MutableMapping
from enum import Enum, auto
from http import HTTPStatus

from starlette.types import ASGIApp, Receive, Scope, Send

from utils import request_signal
from utils.error_handler import UpstreamAuthError, validate_workspace_format
from utils.logger import get_logger

AsgiMessage = MutableMapping[str, object]

logger = get_logger('auth_error_middleware')


class _Decision(Enum):
    """Whether the response was replaced with a 401, forwarded as-is, or
    forwarded because the cooldown suppressed the 401."""

    PENDING = auto()
    REPLACED = auto()
    FORWARDED = auto()
    FORWARDED_COOLDOWN = auto()


class UpstreamAuthErrorMiddleware:
    """Replace HTTP 200 with a challenge when upstream API requires re-authentication.

    Uses a per-client cooldown timer to prevent infinite re-auth loops:
    after emitting a challenge for a given client, subsequent upstream auth errors
    from that client within the cooldown period leave the app's own response
    alone instead of raising a second one. Cooldown is tracked per client (by
    JWT token hash) so one client's re-auth does not suppress another's.
    """

    def __init__(
        self,
        app: ASGIApp,
        resource_metadata_url: str = '',
        cooldown_seconds: float = 60,
    ):
        self.app = app
        self.resource_metadata_url = resource_metadata_url
        self._cooldown_seconds = cooldown_seconds
        # Per-client cooldown: cooldown_key -> last 401 time.
        # Pruned on each request to prevent unbounded growth.
        self._client_cooldowns: dict[str, float] = {}

    def _prune_expired_cooldowns(self, now: float) -> None:
        """Remove cooldown entries that have expired."""
        expired = [
            key
            for key, ts in self._client_cooldowns.items()
            if (now - ts) > self._cooldown_seconds
        ]
        for key in expired:
            del self._client_cooldowns[key]

    @staticmethod
    def _extract_token_key(scope: Scope) -> str | None:
        """Extract JWT token from Authorization header and derive a cooldown key.

        Returns None if no Bearer token is present. Handles the Bearer scheme
        case-insensitively per RFC 6750 and decodes defensively to avoid
        UnicodeDecodeError on malformed headers.
        """
        headers = dict(scope.get('headers', []))
        auth_raw = headers.get(b'authorization', b'')
        if not auth_raw:
            return None
        try:
            auth_header = auth_raw.decode('utf-8')
        except UnicodeDecodeError:
            auth_header = auth_raw.decode('latin-1', errors='replace')
        auth_header = auth_header.strip()
        if auth_header.lower().startswith('bearer '):
            token = auth_header[len('Bearer ') :].strip()
            if token:
                return hashlib.sha256(token.encode()).hexdigest()[:16]
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        cooldown_key = self._extract_token_key(scope)
        signal = request_signal.begin_request()
        try:
            await self._call_http(scope, receive, send, cooldown_key, signal)
        finally:
            request_signal.end_request()

    async def _call_http(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        cooldown_key: str | None,
        signal: request_signal.AuthSignal,
    ) -> None:
        """Stream the app's response, replacing it with a 401 if the signal fires.

        The start message is held until the signal is known: once it goes out,
        neither the status nor WWW-Authenticate can be changed.
        """
        logger.debug(
            '[DEBUG-MW] Request %s—cooldown_key=%s (None means no Bearer header)',
            scope.get('path', '?'),
            cooldown_key,
        )

        # The signal checks below are not gated on the cooldown key: only a request
        # carrying a JWT ever signals (see http_client), so any other stays empty.
        pending_start: AsgiMessage | None = None
        decision = _Decision.PENDING

        async def gated_send(message: AsgiMessage) -> None:
            nonlocal pending_start, decision

            if decision is _Decision.REPLACED:
                return

            if message['type'] == 'http.response.start':
                pending_start = message
                return

            if decision is _Decision.PENDING:
                if signal:
                    if await self._replace_with_challenge(send, signal, cooldown_key):
                        decision = _Decision.REPLACED
                        return
                    decision = _Decision.FORWARDED_COOLDOWN
                else:
                    decision = _Decision.FORWARDED
                if pending_start is not None:
                    start, pending_start = pending_start, None
                    await send(start)

            await send(message)

        try:
            await self.app(scope, receive, gated_send)
        except UpstreamAuthError as e:
            # Unreachable through the SDK, which turns handler exceptions into
            # a wire response. Kept for a caller that invokes this app directly.
            if decision is _Decision.PENDING:
                sent_401 = await self._replace_with_challenge(
                    send,
                    {'mfa_required': e.mfa_required, 'source': e.source},
                    cooldown_key,
                )
                if not sent_401:
                    # The app raised instead of answering, so the cooldown has no
                    # original response to fall back on.
                    logger.info(
                        'Upstream 401 detected but cooldown active; sending 500 '
                        '(no original response to fall back on)'
                    )
                    await self._send_error(
                        send,
                        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                        message='Authentication error',
                    )
            elif decision is _Decision.FORWARDED and signal:
                logger.warning(
                    'Upstream 401 signalled after the response started; '
                    'cannot replace it'
                )
            return

        if decision is _Decision.REPLACED:
            return

        if decision is _Decision.PENDING:
            if signal:
                if await self._replace_with_challenge(send, signal, cooldown_key):
                    return
        elif decision is _Decision.FORWARDED and signal:
            logger.warning(
                'Upstream 401 signalled after the response started; cannot replace it'
            )

        if pending_start is not None:
            await send(pending_start)

    async def _replace_with_challenge(
        self,
        send: Send,
        signal: request_signal.AuthSignal,
        cooldown_key: str | None,
    ) -> bool:
        """Answer with the challenge, unless this client was told to re-authenticate already.

        The cooldown stops a client from looping on a challenge it cannot satisfy.
        Returns False without sending anything when the cooldown is active, leaving
        the caller to pass the app's own response through.
        """
        now = time.monotonic()
        self._prune_expired_cooldowns(now)
        client_key = cooldown_key or '_anonymous'
        last_401 = self._client_cooldowns.get(client_key)
        mfa_required = bool(signal.get('mfa_required', False))
        source = str(signal.get('source', ''))
        ledger_org = signal.get('ledger_org')
        # The name lands inside a quoted header value; anything a workspace
        # cannot be called is dropped rather than escaped.
        if not isinstance(ledger_org, str) or not validate_workspace_format(ledger_org):
            ledger_org = ''

        if last_401 is not None and (now - last_401) <= self._cooldown_seconds:
            remaining = self._cooldown_seconds - (now - last_401)
            logger.info(
                'Upstream 401 detected but cooldown active (%.0fs remaining), '
                'not replacing the response',
                remaining,
            )
            return False

        self._client_cooldowns[client_key] = now
        logger.info(
            'Upstream 401 detected (mfa_required=%s, ledger=%s, source=%s), '
            'returning a re-auth challenge',
            mfa_required,
            bool(ledger_org),
            source,
        )
        await self._send_challenge(
            send, mfa_required=mfa_required, ledger_org=ledger_org
        )
        return True

    async def _send_error(
        self,
        send: Send,
        *,
        status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR,
        message: str = 'Internal error',
    ) -> None:
        """Send a generic HTTP error response."""
        body = json.dumps({'error': message}).encode()
        await send(
            {
                'type': 'http.response.start',
                'status': status_code,
                'headers': [
                    (b'content-type', b'application/json'),
                    (b'content-length', str(len(body)).encode()),
                ],
            }
        )
        await send(
            {
                'type': 'http.response.body',
                'body': body,
            }
        )

    async def _send_challenge(
        self, send: Send, *, mfa_required: bool = False, ledger_org: str = ''
    ) -> None:
        """Send the re-authentication challenge.

        An MFA signal answers 403 insufficient_scope with 'mfa' in the scope: MCP
        clients refresh on a 401 and drop its scope while the refresh succeeds,
        and a refreshed token still lacks MFA. On insufficient_scope they skip
        the refresh and run /oauth/authorize with the union of scopes, where the
        proxy turns 'mfa' into the two-stage MFA flow. A ledger signal works the
        same way with 'ledger:<workspace>', which the proxy turns into a sign-in
        for the ledger audience. Anything else is a 401.
        """
        scopes = 'openid profile email offline_access'
        error = 'invalid_token'
        status = HTTPStatus.UNAUTHORIZED
        if mfa_required:
            scopes += ' mfa'
        if ledger_org:
            scopes += f' ledger:{ledger_org}'
        if mfa_required or ledger_org:
            error = 'insufficient_scope'
            status = HTTPStatus.FORBIDDEN

        www_auth_parts = [f'error="{error}"', f'scope="{scopes}"']
        if self.resource_metadata_url:
            www_auth_parts.append(f'resource_metadata="{self.resource_metadata_url}"')

        www_authenticate = f'Bearer {", ".join(www_auth_parts)}'

        if mfa_required:
            description = 'MFA verification required. Re-authentication needed.'
        elif ledger_org:
            description = (
                'The command pre-approval ledger needs its own authorization. '
                'Re-authentication needed.'
            )
        else:
            description = 'Authentication expired. Re-authentication needed.'
        body = json.dumps(
            {
                'error': error,
                'error_description': description,
            }
        ).encode()

        await send(
            {
                'type': 'http.response.start',
                'status': status,
                'headers': [
                    (b'content-type', b'application/json'),
                    (b'content-length', str(len(body)).encode()),
                    (b'www-authenticate', www_authenticate.encode()),
                ],
            }
        )
        await send(
            {
                'type': 'http.response.body',
                'body': body,
            }
        )
