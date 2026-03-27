"""ASGI middleware to propagate upstream API 401 as MCP transport 401.

When the Alpacon API returns 401 (e.g., MFA timeout), this middleware
intercepts the error and returns HTTP 401 + WWW-Authenticate header,
triggering the MCP client's automatic OAuth re-authentication flow.

Two complementary propagation mechanisms are supported:

1. **Exception path (primary)**: ``http_client`` raises
   ``UpstreamAuthError`` which propagates through the call stack.
   The middleware catches it in the ``try/except`` around
   ``self.app()``.

2. **Dict-signal path (fallback)**: ``http_client`` sets a
   module-level thread-safe dict entry (keyed by token hash) before
   raising.  If an intermediate handler catches the exception, the
   middleware still finds the signal after the request completes.
   Uses a module-level dict instead of contextvars because MCP
   streamable-http runs tool handlers in a separate anyio task
   context where ContextVar mutations are invisible.

Only active in remote (streamable-http) mode where OAuth is enabled.
"""

import json
import time
from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from utils.error_handler import (
    UpstreamAuthError,
    consume_upstream_auth_error,
    make_auth_error_key,
)
from utils.logger import get_logger

logger = get_logger('auth_error_middleware')


class UpstreamAuthErrorMiddleware:
    """Replace HTTP 200 with 401 when upstream API requires re-authentication.

    Uses a per-client cooldown timer to prevent infinite re-auth loops:
    after emitting a 401 for a given client, subsequent upstream auth errors
    from that client within the cooldown period are passed through as normal
    tool error responses. Cooldown is tracked per client (by JWT token hash)
    so one client's re-auth does not suppress another's.
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
        # Per-client cooldown: token_key -> last 401 time.
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
        """Extract JWT token from Authorization header and derive a hash key.

        Returns a short hash key that matches make_auth_error_key() output
        from the http_client, enabling cross-context error signaling.
        Returns None if no Bearer token is present.

        Handles the Bearer scheme case-insensitively per RFC 6750 and
        decodes defensively to avoid UnicodeDecodeError on malformed headers.
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
                return make_auth_error_key(token)
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        # Extract token key upfront so we can always clean up stale entries
        # in the module-level dict, even if the app raises or is cancelled.
        token_key = self._extract_token_key(scope)

        # Buffer the response so we can replace it if needed
        buffered: list[MutableMapping[str, Any]] = []

        async def buffer_send(message: MutableMapping[str, Any]) -> None:
            buffered.append(message)

        try:
            await self.app(scope, receive, buffer_send)
        except UpstreamAuthError as e:
            # Primary path: http_client raised UpstreamAuthError on upstream 401.
            # This propagates reliably across anyio task boundaries.
            # Consume any dict signal too (set before the raise) to prevent
            # stale entries.
            if token_key:
                consume_upstream_auth_error(token_key)

            now = time.monotonic()
            self._prune_expired_cooldowns(now)
            client_key = token_key or '_anonymous'
            cooldown_active = False
            if client_key in self._client_cooldowns:
                last_401 = self._client_cooldowns[client_key]
                cooldown_active = (now - last_401) <= self._cooldown_seconds

            if not cooldown_active:
                self._client_cooldowns[client_key] = now
                logger.info(
                    'UpstreamAuthError caught (mfa_required=%s, source=%s), '
                    'returning HTTP 401 to trigger re-auth',
                    e.mfa_required,
                    e.source,
                )
                await self._send_401(send, mfa_required=e.mfa_required)
                return

            remaining = self._cooldown_seconds - (now - last_401)
            logger.info(
                'UpstreamAuthError caught but cooldown active '
                '(%.0fs remaining), passing through buffered response',
                remaining,
            )
            # Forward any buffered response from the app (which may be a
            # tool error response generated by FastMCP's exception handler)
            # instead of overriding with a generic error. This keeps cooldown
            # behavior consistent with the dict-signal path.
            if buffered:
                for msg in buffered:
                    await send(msg)
            else:
                # No response was buffered (exception raised before any
                # response was written). Send a generic error as fallback.
                await self._send_error(
                    send, status_code=500, message='Authentication error'
                )
            return
        except BaseException:
            # App raised or request was cancelled. Consume any pending
            # signal to prevent stale entries and unbounded dict growth.
            if token_key:
                consume_upstream_auth_error(token_key)
            raise

        # Fallback path: Consume the upstream auth signal from the dict.
        # This handles cases where the exception was caught by an intermediate
        # handler but the dict signal was still set.
        error_info = None
        if token_key:
            error_info = consume_upstream_auth_error(token_key)
        now = time.monotonic()
        self._prune_expired_cooldowns(now)

        if error_info:
            client_key = token_key or '_anonymous'
            cooldown_active = False
            last_401 = 0.0
            if client_key in self._client_cooldowns:
                last_401 = self._client_cooldowns[client_key]
                cooldown_active = (now - last_401) <= self._cooldown_seconds

            if not cooldown_active:
                self._client_cooldowns[client_key] = now
                mfa_required = error_info.get('mfa_required', False)
                source = error_info.get('source', '')
                logger.info(
                    'Upstream 401 detected (mfa_required=%s, source=%s), '
                    'returning HTTP 401 to trigger re-auth',
                    mfa_required,
                    source,
                )
                await self._send_401(send, mfa_required=mfa_required)
                return

            remaining = self._cooldown_seconds - (now - last_401)
            logger.info(
                'Upstream 401 detected but cooldown active '
                '(%.0fs remaining), passing through as tool error',
                remaining,
            )

        for msg in buffered:
            await send(msg)

    async def _send_error(
        self, send: Send, *, status_code: int = 500, message: str = 'Internal error'
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

    async def _send_401(self, send: Send, *, mfa_required: bool = False) -> None:
        """Send HTTP 401 with WWW-Authenticate header.

        When mfa_required is True, includes 'mfa' in the scope parameter.
        The MCP client reads this scope and passes it to /oauth/authorize,
        where our proxy converts it to Auth0 acr_values to force MFA.
        """
        scopes = 'openid profile email offline_access'
        if mfa_required:
            scopes += ' mfa'

        www_auth_parts = ['error="invalid_token"']
        www_auth_parts.append(f'scope="{scopes}"')
        if self.resource_metadata_url:
            www_auth_parts.append(f'resource_metadata="{self.resource_metadata_url}"')

        www_authenticate = f'Bearer {", ".join(www_auth_parts)}'

        description = (
            'MFA verification required. Re-authentication needed.'
            if mfa_required
            else 'Authentication expired. Re-authentication needed.'
        )
        body = json.dumps(
            {
                'error': 'invalid_token',
                'error_description': description,
            }
        ).encode()

        await send(
            {
                'type': 'http.response.start',
                'status': 401,
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
