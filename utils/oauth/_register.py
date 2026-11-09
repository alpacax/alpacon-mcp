"""The dynamic client registration endpoint."""

from http import HTTPStatus

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from utils.oauth._http import (
    _CACHE_CONTROL_NO_STORE,
    _ERROR_INVALID_CLIENT_METADATA,
    _ERROR_INVALID_REDIRECT_URI,
    _ERROR_INVALID_REQUEST,
    _ERROR_SERVER_ERROR,
    _JSON_BODY_ERRORS,
    _JSON_CONTENT_TYPE,
    _TOKEN_ENDPOINT_AUTH_NONE,
    _allow_browser_clients,
    _get_oauth_config,
    _oauth_error_response,
    _OAuthRequestError,
    _parse_json_body,
    _read_bounded_body,
    logger,
)
from utils.oauth._redirect_uris import (
    _MAX_REGISTERED_REDIRECT_URIS,
    _is_allowed_redirect_uri,
    _is_registrable_uri_list,
)


@_allow_browser_clients
async def oauth_register(request: Request) -> Response:
    """Dynamic Client Registration (RFC 7591): validates redirect_uris, returns the
    pre-configured client_id, since Auth0 lacks DCR on non-Enterprise plans."""
    try:
        config = _require_registration_config()
        client_metadata = await _parse_client_metadata(request)
        _validate_registered_redirect_uris(client_metadata)
    except _OAuthRequestError as e:
        return e.response

    response_data = _registration_body(config, client_metadata)
    logger.info('Dynamic client registration: returning pre-configured client_id')
    return JSONResponse(
        response_data,
        status_code=HTTPStatus.CREATED,
        headers={
            'Cache-Control': _CACHE_CONTROL_NO_STORE,
        },
    )


def _require_registration_config() -> dict[str, str]:
    try:
        return _get_oauth_config()
    except ValueError as e:
        logger.error('OAuth config error in /oauth/register: %s', e)
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_SERVER_ERROR,
                'OAuth configuration is incomplete',
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        ) from e


async def _parse_client_metadata(request: Request) -> dict[str, object]:
    """The RFC 7591 client metadata, which must be a JSON object."""
    body = await _read_bounded_body(request)
    if body is None:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_CLIENT_METADATA,
                'Request body is too large',
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        )
    content_type = request.headers.get('content-type', '')

    if _JSON_CONTENT_TYPE not in content_type:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REQUEST, 'Content-Type must be application/json'
            )
        )

    if not body:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_CLIENT_METADATA,
                'Request body must be a JSON object with client metadata',
            )
        )

    try:
        client_metadata = _parse_json_body(body)
    except _JSON_BODY_ERRORS:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_CLIENT_METADATA, 'Request body must be valid JSON'
            )
        ) from None

    if not isinstance(client_metadata, dict):
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_CLIENT_METADATA, 'Client metadata must be a JSON object'
            )
        )
    return client_metadata


def _validate_registered_redirect_uris(client_metadata: dict[str, object]) -> None:
    """Refuse redirect_uris that /oauth/authorize would refuse; absent is allowed."""
    if 'redirect_uris' not in client_metadata:
        return
    redirect_uris = client_metadata['redirect_uris']
    # The shape check comes first: _is_allowed_redirect_uri parses a str.
    if not _is_registrable_uri_list(redirect_uris):
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_CLIENT_METADATA,
                'redirect_uris must be an array of 1 to '
                f'{_MAX_REGISTERED_REDIRECT_URIS} strings',
            )
        )
    if not all(_is_allowed_redirect_uri(uri) for uri in redirect_uris):
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REDIRECT_URI,
                'One or more redirect_uris are invalid or not allowed by this server',
            )
        )


def _registration_body(
    config: dict[str, str], client_metadata: dict[str, object]
) -> dict[str, object]:
    response_data: dict[str, object] = {
        'client_id': config['client_id'],
        'token_endpoint_auth_method': _TOKEN_ENDPOINT_AUTH_NONE,
    }
    # Truthful only because these URIs cleared the check /oauth/authorize applies.
    if 'redirect_uris' in client_metadata:
        response_data['redirect_uris'] = client_metadata['redirect_uris']
    if 'client_name' in client_metadata:
        response_data['client_name'] = client_metadata['client_name']
    return response_data
