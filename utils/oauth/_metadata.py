"""Authorization server metadata (RFC 8414)."""

from http import HTTPStatus

from starlette.responses import JSONResponse

from utils.oauth._http import (
    _ALLOWED_GRANT_TYPES,
    _AUTHORIZE_PATH,
    _DEFAULT_SCOPES,
    _PKCE_CHALLENGE_METHOD,
    _REGISTER_PATH,
    _RESPONSE_TYPE_CODE,
    _TOKEN_PATH,
    _allow_browser_clients,
    _get_oauth_config,
    _get_server_url,
)

_METADATA_CACHE_SECONDS = 3600


# RFC 8414 metadata is public and carries no credentials. Decorating covers the
# 500 path too, so a misconfiguration reads as an error, not a CORS failure.
@_allow_browser_clients
async def _oauth_metadata(request):
    """RFC 8414 metadata naming this server as the authorization server.

    authorize, token and register proxy to Auth0; only jwks_uri points at Auth0
    directly.
    """
    try:
        config = _get_oauth_config()
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    server_url = _get_server_url(request)

    metadata = {
        'issuer': f'{server_url}/',
        'authorization_endpoint': f'{server_url}{_AUTHORIZE_PATH}',
        'token_endpoint': f'{server_url}{_TOKEN_PATH}',
        'registration_endpoint': f'{server_url}{_REGISTER_PATH}',
        'jwks_uri': f'{config["auth0_base_url"]}/.well-known/jwks.json',
        'response_types_supported': [_RESPONSE_TYPE_CODE],
        'grant_types_supported': list(_ALLOWED_GRANT_TYPES),
        'token_endpoint_auth_methods_supported': [
            'none',
        ],
        'scopes_supported': list(_DEFAULT_SCOPES),
        'code_challenge_methods_supported': [_PKCE_CHALLENGE_METHOD],
    }

    return JSONResponse(
        metadata,
        headers={'Cache-Control': f'public, max-age={_METADATA_CACHE_SECONDS}'},
    )
