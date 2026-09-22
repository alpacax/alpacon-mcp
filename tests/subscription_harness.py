"""Serve the deployment's composed app on a loopback port, for subscription tests.

Run as a script, never imported by the test process: ``server`` builds its
MCPServer at import time from the environment, so remote mode has to be the
first thing this module does and cannot be turned on inside an already-imported
test session without reloading the module.

It composes what ``main_http.py`` composes—``prepare(TRANSPORT_STREAMABLE_HTTP)``,
``create_streamable_http_app``, wrapped in ``UpstreamAuthErrorMiddleware``—plus
two test-only endpoints and one test-only tool. Only the token verifier is
stubbed, and it binds 127.0.0.1 where production binds 0.0.0.0, so DNS rebinding
protection is on here and off there.

Usage: ``python tests/subscription_harness.py <port>``
"""

import os
import sys
from typing import cast

os.environ['ALPACON_MCP_AUTH_ENABLED'] = 'true'
os.environ['AUTH0_DOMAIN'] = 'example.us.auth0.com'
os.environ['AUTH0_CLIENT_ID'] = 'test-client-id'
os.environ['ALPACON_MCP_RESOURCE_URL'] = 'https://mcp.example.com'

import uvicorn  # noqa: E402
from mcp.server.auth.provider import AccessToken  # noqa: E402
from mcp.server.subscriptions import InMemorySubscriptionBus  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

import server  # noqa: E402
from utils import request_signal  # noqa: E402
from utils.auth import Auth0TokenVerifier  # noqa: E402
from utils.auth_error_middleware import UpstreamAuthErrorMiddleware  # noqa: E402
from utils.error_handler import UpstreamAuthError  # noqa: E402

TOKEN_PREFIX = 'test-jwt'  # noqa: S105
SIGNALLING_TOOL = 'raise_upstream_401'


async def _accept_test_token(self, token: str) -> AccessToken | None:
    """Stand in for Auth0 verification; the rest of the auth path stays real.

    Every token under TOKEN_PREFIX is accepted, so a test that must not share
    the middleware's per-token re-auth cooldown can mint its own.
    """
    if not token.startswith(TOKEN_PREFIX):
        return None
    return AccessToken(
        token=token,
        client_id='test-client-id',
        scopes=['openid', 'profile', 'email', 'offline_access'],
        expires_at=None,
        subject='auth0|test-user',
        claims={'sub': 'auth0|test-user'},
    )


def _register_test_endpoints() -> None:
    @server.mcp.custom_route('/_test/subscriptions', methods=['GET'])
    async def subscription_count(request: Request) -> JSONResponse:
        # The bus listener set is the only place a live listen stream is
        # counted; ListenHandler subscribes on entry and unsubscribes in its
        # finally, so this reads the lifecycle rather than a task total.
        bus = cast(InMemorySubscriptionBus, server.mcp._subscriptions)
        return JSONResponse({'listeners': len(bus._listeners)})

    @server.mcp.tool(name=SIGNALLING_TOOL)
    async def raise_upstream_401() -> str:
        """Record an upstream 401 the way http_client does, then fail."""
        request_signal.signal_upstream_auth_error(
            {'mfa_required': False, 'source': 'harness'}
        )
        raise UpstreamAuthError(mfa_required=False, source='harness')


def main() -> None:
    # setattr, not assignment: mypy refuses to rebind a method on the class.
    setattr(Auth0TokenVerifier, 'verify_token', _accept_test_token)  # noqa: B010

    server.prepare(server.TRANSPORT_STREAMABLE_HTTP)
    _register_test_endpoints()

    app = UpstreamAuthErrorMiddleware(
        server.create_streamable_http_app(host='127.0.0.1'),
        resource_metadata_url=server.resource_metadata_url(),
    )
    uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')


if __name__ == '__main__':
    main()
