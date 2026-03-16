"""ASGI middleware to propagate upstream API 401 as MCP transport 401.

When the Alpacon API returns 401 (e.g., MFA timeout), the HTTP client
sets a contextvars flag. This middleware detects the flag and replaces
the HTTP 200 JSON-RPC response with HTTP 401 + WWW-Authenticate header,
triggering the MCP client's automatic OAuth re-authentication flow.

Only active in remote (streamable-http) mode where OAuth is enabled.
"""

import json
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from utils.error_handler import upstream_auth_error_flag
from utils.logger import get_logger

logger = get_logger('auth_error_middleware')


class UpstreamAuthErrorMiddleware:
    """Replace HTTP 200 with 401 when upstream API requires re-authentication.

    Uses a cooldown timer to prevent infinite re-auth loops: after emitting
    a 401, subsequent upstream auth errors within the cooldown period are
    passed through as normal tool error responses.
    """

    def __init__(
        self,
        app: ASGIApp,
        resource_metadata_url: str = '',
        cooldown_seconds: float = 60,
    ):
        self.app = app
        self.resource_metadata_url = resource_metadata_url
        self._last_401_time: float = 0
        self._cooldown_seconds = cooldown_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        # Reset flag for this request
        upstream_auth_error_flag.set(None)

        # Buffer the response so we can replace it if needed
        buffered: list[dict] = []

        async def buffer_send(message: dict) -> None:
            buffered.append(message)

        await self.app(scope, receive, buffer_send)

        # Check if tool signaled upstream auth error
        error_info = upstream_auth_error_flag.get()
        now = time.monotonic()
        cooldown_active = (now - self._last_401_time) <= self._cooldown_seconds

        if error_info and not cooldown_active:
            self._last_401_time = now
            mfa_required = error_info.get('mfa_required', False)
            source = error_info.get('source', '')
            logger.info(
                'Upstream 401 detected (mfa_required=%s, source=%s), '
                'returning HTTP 401 to trigger re-auth',
                mfa_required,
                source,
            )
            await self._send_401(send, mfa_required=mfa_required)
        else:
            if error_info and cooldown_active:
                remaining = self._cooldown_seconds - (now - self._last_401_time)
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
