"""The RFC 8414 authorization server metadata endpoint."""

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _DEFAULT_SCOPES,
    _GRANT_AUTHORIZATION_CODE,
    _GRANT_REFRESH_TOKEN,
    _PKCE_CHALLENGE_METHOD,
    _REGISTER_PATH,
    _RESPONSE_TYPE_CODE,
    _TOKEN_ENDPOINT_AUTH_NONE,
    _TOKEN_PATH,
    _allow_browser_clients,
    _get_server_url,
    _OAuthRequestError,
    _require_oauth_config,
)

_METADATA_CACHE_SECONDS = 3600


# RFC 8414 metadata is public and carries no credentials. Decorating covers the
# 500 path too, so a misconfiguration is readable rather than a CORS error.
@_allow_browser_clients
async def oauth_metadata(request: Request) -> Response:
    """OAuth 2.0 Authorization Server Metadata (RFC 8414): authorize, token and
    register point here; only jwks_uri points to Auth0."""
    try:
        config = _require_oauth_config()
    except _OAuthRequestError as e:
        return e.response

    return JSONResponse(
        _authorization_server_metadata(config, _get_server_url(request)),
        headers={'Cache-Control': f'public, max-age={_METADATA_CACHE_SECONDS}'},
    )


def _authorization_server_metadata(
    config: dict[str, str], server_url: str
) -> dict[str, object]:
    return {
        'issuer': f'{server_url}/',
        'authorization_endpoint': f'{server_url}{_AUTHORIZE_PATH}',
        'token_endpoint': f'{server_url}{_TOKEN_PATH}',
        'registration_endpoint': f'{server_url}{_REGISTER_PATH}',
        'jwks_uri': f'{config["auth0_base_url"]}/.well-known/jwks.json',
        'response_types_supported': [_RESPONSE_TYPE_CODE],
        'grant_types_supported': [
            _GRANT_AUTHORIZATION_CODE,
            _GRANT_REFRESH_TOKEN,
        ],
        'token_endpoint_auth_methods_supported': [
            _TOKEN_ENDPOINT_AUTH_NONE,
        ],
        'scopes_supported': list(_DEFAULT_SCOPES),
        'code_challenge_methods_supported': [_PKCE_CHALLENGE_METHOD],
    }
