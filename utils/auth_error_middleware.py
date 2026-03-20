"""ASGI middleware to propagate upstream API 401 as MCP transport 401.

When the Alpacon API returns 401 (e.g., MFA timeout), the HTTP client
signals via a module-level thread-safe dict (keyed by token hash).
This middleware checks the dict after the request completes and replaces
the HTTP 200 JSON-RPC response with HTTP 401 + WWW-Authenticate header,
triggering the MCP client's automatic OAuth re-authentication flow.

Uses a module-level dict instead of contextvars because MCP
streamable-http transport runs tool handlers in a separate anyio task
context where ContextVar mutations are invisible to the middleware.

Only active in remote (streamable-http) mode where OAuth is enabled.
"""

import json
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from utils.error_handler import consume_upstream_auth_error, make_auth_error_key
from utils.logger import get_logger

logger = get_logger('auth_error_middleware')


class UpstreamAuthErrorMiddleware:
    """Replace HTTP 200 with 401 when upstream API requires re-authentication.

    Uses a per-client cooldown timer to prevent infinite re-auth loops:
    after emitting a 401 for a given client, subsequent upstream auth errors
    from that client within the cooldown period are passed through as normal
    tool error responses. Cooldown is tracked per client (by hashed
    Authorization header) so one client's re-auth does not suppress another's.
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

        # Buffer the response so we can replace it if needed
        buffered: list[dict] = []

        async def buffer_send(message: dict) -> None:
            buffered.append(message)

        await self.app(scope, receive, buffer_send)

        # Check if tool signaled upstream auth error via module-level dict.
        # The http_client and this middleware both derive the same key from
        # the JWT token, bypassing the contextvars isolation issue.
        token_key = self._extract_token_key(scope)
        error_info = consume_upstream_auth_error(token_key) if token_key else None
        now = time.monotonic()
        self._prune_expired_cooldowns(now)

        if error_info:
            client_key = token_key or '_anonymous'
            cooldown_active = False
            last_401: float = 0
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
