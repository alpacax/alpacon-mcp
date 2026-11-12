"""OAuth 2.0 proxy endpoints that let MCP clients run the authorization code flow
through this server to Auth0; custom_route registers them outside MCP authentication."""

import os

from starlette.requests import Request
from starlette.responses import Response

from utils.error_handler import is_production_deployment
from utils.oauth._authorize import oauth_authorize
from utils.oauth._callback import oauth_callback
from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _CALLBACK_PATH,
    _FALLBACK_AUTHORIZE_PATH,
    _FALLBACK_REGISTER_PATH,
    _FALLBACK_TOKEN_PATH,
    _METADATA_PATH,
    _REGISTER_PATH,
    _TOKEN_PATH,
    logger,
)
from utils.oauth._metadata import oauth_metadata
from utils.oauth._redirect_uris import (
    _ENV_ALLOWED_REDIRECT_DOMAINS,
    _has_redirect_uri_override,
    _is_redirect_uri_report_only,
)
from utils.oauth._register import oauth_register
from utils.oauth._sealing import (
    _GRANT_SECRET_ENV,
    _STATE_SECRET_ENV,
    _get_grant_secret,
    _get_state_secret,
    ledger_grant_key,
    request_state_key,
)
from utils.oauth._token import oauth_token
from utils.routes import RouteHandler, RouteRegistry


async def oauth_token_fallback(request: Request) -> Response:
    """Fallback for /token, hit when oauth_metadata is not cached; delegates to
    /oauth/token."""
    if request.method != 'OPTIONS':
        logger.info('/token fallback hit—delegating to /oauth/token handler')
    return await oauth_token(request)


async def oauth_authorize_fallback(request: Request) -> Response:
    """Fallback for /authorize when oauth_metadata is not cached."""
    logger.info('/authorize fallback hit—delegating to /oauth/authorize handler')
    return await oauth_authorize(request)


async def oauth_register_fallback(request: Request) -> Response:
    """Fallback for /register when oauth_metadata is not cached."""
    if request.method != 'OPTIONS':
        logger.info('/register fallback hit—delegating to /oauth/register handler')
    return await oauth_register(request)


_ROUTES: tuple[tuple[str, tuple[str, ...], RouteHandler], ...] = (
    (_METADATA_PATH, ('GET',), oauth_metadata),
    (_AUTHORIZE_PATH, ('GET',), oauth_authorize),
    (_TOKEN_PATH, ('POST', 'OPTIONS'), oauth_token),
    (_REGISTER_PATH, ('POST', 'OPTIONS'), oauth_register),
    (_CALLBACK_PATH, ('GET',), oauth_callback),
    (_FALLBACK_TOKEN_PATH, ('POST', 'OPTIONS'), oauth_token_fallback),
    (_FALLBACK_AUTHORIZE_PATH, ('GET',), oauth_authorize_fallback),
    (_FALLBACK_REGISTER_PATH, ('POST', 'OPTIONS'), oauth_register_fallback),
)


def register_oauth_routes(mcp_server: RouteRegistry) -> None:
    """Register the OAuth proxy routes; raises ValueError when an explicit state or
    grant secret is malformed."""
    # A malformed key would otherwise surface on the first OAuth request. Only the
    # explicit keys are checked outside production so local setups may omit OAuth config.
    if os.getenv(_STATE_SECRET_ENV):
        _get_state_secret()
    if os.getenv(_GRANT_SECRET_ENV):
        _get_grant_secret()
    elif is_production_deployment():
        logger.error(
            '%s is not set in production; using the client-secret-derived key '
            'until fallback removal (#488)',
            _GRANT_SECRET_ENV,
        )

    for path, methods, handler in _ROUTES:
        mcp_server.custom_route(path, methods=list(methods))(handler)

    # Report-only mode is what makes the domain list meaningful on its own, so
    # a deployment running it is configured, not misconfigured.
    domains_only = (
        os.getenv(_ENV_ALLOWED_REDIRECT_DOMAINS, '').strip()
        and not _has_redirect_uri_override()
        and not _is_redirect_uri_report_only()
    )
    if domains_only:
        logger.warning(
            'ALLOWED_REDIRECT_DOMAINS is set but ALLOWED_REDIRECT_URIS is not; '
            'those hosts are being rejected. List their full callback URIs in '
            'ALLOWED_REDIRECT_URIS, or set ALPACON_MCP_REDIRECT_URI_REPORT_ONLY=true '
            'to fall back to logging only'
        )

    logger.info(
        'OAuth proxy routes registered (including /token, /authorize, '
        '/register fallbacks) - state secret: %s, grant secret: %s',
        'explicit env'
        if os.getenv(_STATE_SECRET_ENV)
        else 'derived from client secret',
        'explicit env'
        if os.getenv(_GRANT_SECRET_ENV)
        else 'derived from client secret',
    )


__all__ = ['ledger_grant_key', 'register_oauth_routes', 'request_state_key']
