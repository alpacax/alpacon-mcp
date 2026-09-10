"""Route registration and the unprefixed fallback endpoints."""

import os

from utils.logger import get_logger
from utils.oauth._authorize import _oauth_authorize
from utils.oauth._callback import _oauth_callback
from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _CALLBACK_PATH,
    _METADATA_PATH,
    _REGISTER_PATH,
    _TOKEN_PATH,
)
from utils.oauth._metadata import _oauth_metadata
from utils.oauth._redirect_uris import (
    _ENV_ALLOWED_REDIRECT_DOMAINS,
    _has_redirect_uri_override,
    _is_redirect_uri_report_only,
)
from utils.oauth._register import _oauth_register
from utils.oauth._sealing import (
    _GRANT_SECRET_ENV,
    _STATE_SECRET_ENV,
    _get_grant_secret,
    _get_state_secret,
)
from utils.oauth._token import _oauth_token

logger = get_logger('oauth')


async def _oauth_token_fallback(request):
    """Fallback token endpoint at /token.

    MCP SDK clients fall back to /token when the metadata is not cached, e.g. after
    a restart that kept a refresh_token; delegating avoids a silent 404.
    """
    if request.method != 'OPTIONS':
        logger.info('/token fallback hit — delegating to /oauth/token handler')
    return await _oauth_token(request)


async def _oauth_authorize_fallback(request):
    """Fallback at /authorize for MCP SDK clients without cached metadata."""
    logger.info('/authorize fallback hit — delegating to /oauth/authorize handler')
    return await _oauth_authorize(request)


async def _oauth_register_fallback(request):
    """Fallback at /register for MCP SDK clients without cached metadata."""
    if request.method != 'OPTIONS':
        logger.info('/register fallback hit — delegating to /oauth/register handler')
    return await _oauth_register(request)


def register_oauth_routes(mcp_server):
    """Register the OAuth proxy routes on the FastMCP server.

    Raises ValueError when ALPACON_MCP_STATE_SECRET or ALPACON_MCP_GRANT_SECRET is
    set to a malformed value.
    """
    # A malformed key would otherwise surface on the first user's OAuth request,
    # long after the deployment reported success. Only explicit keys are checked:
    # deriving one needs OAuth config, and deployments without it must keep
    # starting.
    if os.getenv(_STATE_SECRET_ENV):
        _get_state_secret()
    if os.getenv(_GRANT_SECRET_ENV):
        _get_grant_secret()

    for path, methods, handler in (
        (_METADATA_PATH, ['GET'], _oauth_metadata),
        (_AUTHORIZE_PATH, ['GET'], _oauth_authorize),
        (_TOKEN_PATH, ['POST', 'OPTIONS'], _oauth_token),
        (_REGISTER_PATH, ['POST', 'OPTIONS'], _oauth_register),
        (_CALLBACK_PATH, ['GET'], _oauth_callback),
        ('/token', ['POST', 'OPTIONS'], _oauth_token_fallback),
        ('/authorize', ['GET'], _oauth_authorize_fallback),
        ('/register', ['POST', 'OPTIONS'], _oauth_register_fallback),
    ):
        mcp_server.custom_route(path, methods=methods)(handler)

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
