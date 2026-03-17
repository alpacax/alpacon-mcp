"""ASGI middleware to propagate upstream API 401 as MCP transport 401.

When the Alpacon API returns 401 (e.g., MFA timeout), the HTTP client
sets a contextvars flag. This middleware detects the flag and replaces
the HTTP 200 JSON-RPC response with HTTP 401 + WWW-Authenticate header,
triggering the MCP client's automatic OAuth re-authentication flow.

Only active in remote (streamable-http) mode where OAuth is enabled.
"""

import hashlib
import json
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from utils.error_handler import upstream_auth_error_flag
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
        flag_provider=None,
    ):
        self.app = app
        self.resource_metadata_url = resource_metadata_url
        self._cooldown_seconds = cooldown_seconds
        # Allow injecting a custom flag provider for testing.
        # Defaults to the module-level contextvars flag.
        self._flag = flag_provider or upstream_auth_error_flag
        # Per-client cooldown: hash(authorization) -> last 401 time.
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
    def _get_client_key(scope: Scope) -> str:
        """Derive a client key from the Authorization header.

        Uses a SHA-256 hash prefix to avoid storing raw tokens in memory.
        Falls back to a fixed key if no Authorization header is present.
        """
        headers = dict(scope.get('headers', []))
        auth_header = headers.get(b'authorization', b'')
        if auth_header:
            return hashlib.sha256(auth_header).hexdigest()[:16]
        return '_anonymous'

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        # Reset flag for this request
        self._flag.set(None)

        # Buffer the response so we can replace it if needed
        buffered: list[dict] = []

        async def buffer_send(message: dict) -> None:
            buffered.append(message)

        await self.app(scope, receive, buffer_send)

        # Check if tool signaled upstream auth error
        error_info = self._flag.get()
        # TEMP DEBUG: remove after CI diagnosis
        import sys

        print(
            f'MIDDLEWARE_DEBUG: flag_type={type(self._flag).__name__}, '
            f'flag_module={type(self._flag).__module__}, '
            f'error_info={error_info!r}, '
            f'flag_id={id(self._flag)}',
            file=sys.stderr,
        )
        now = time.monotonic()
        self._prune_expired_cooldowns(now)

        if error_info:
            client_key = self._get_client_key(scope)
            last_401 = self._client_cooldowns.get(client_key, 0)
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
