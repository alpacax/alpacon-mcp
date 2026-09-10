"""Dynamic client registration (RFC 7591) at /oauth/register."""

import json
from http import HTTPStatus

from starlette.requests import Request
from starlette.responses import JSONResponse

from utils.logger import get_logger
from utils.oauth._http import (
    _ERROR_INVALID_CLIENT_METADATA,
    _ERROR_INVALID_REDIRECT_URI,
    _ERROR_INVALID_REQUEST,
    _ERROR_SERVER_ERROR,
    _JSON_CONTENT_TYPE,
    _allow_browser_clients,
    _get_oauth_config,
    _oauth_error_response,
    _OAuthRequestError,
    _read_bounded_body,
    _reject_response,
)
from utils.oauth._redirect_uris import (
    _MAX_REGISTERED_REDIRECT_URIS,
    _is_allowed_redirect_uri,
    _is_registrable_uri_list,
)

logger = get_logger('oauth')


async def _parse_client_metadata(request: Request) -> dict:
    """Read, decode, and shape-check the client metadata body (RFC 7591)."""
    body = await _read_bounded_body(request)
    if body is None:
        raise _OAuthRequestError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            _ERROR_INVALID_CLIENT_METADATA,
            'Request body is too large',
        )
    content_type = request.headers.get('content-type', '')

    if _JSON_CONTENT_TYPE not in content_type:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'Content-Type must be application/json',
        )
    if not body:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT_METADATA,
            'Request body must be a JSON object with client metadata',
        )

    try:
        client_metadata = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT_METADATA,
            'Request body must be valid JSON',
        ) from None
    if not isinstance(client_metadata, dict):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT_METADATA,
            'Client metadata must be a JSON object',
        )
    return client_metadata


def _validate_redirect_uris(metadata: dict) -> None:
    """Reject redirect_uris that are malformed or outside the allowlist.

    The shape check runs first: _is_allowed_redirect_uri parses each entry as a
    URL string.
    """
    if 'redirect_uris' not in metadata:
        return
    redirect_uris = metadata['redirect_uris']
    if not _is_registrable_uri_list(redirect_uris):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT_METADATA,
            'redirect_uris must be an array of 1 to '
            f'{_MAX_REGISTERED_REDIRECT_URIS} strings',
        )
    if not all(_is_allowed_redirect_uri(uri) for uri in redirect_uris):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REDIRECT_URI,
            'One or more redirect_uris are invalid or not allowed by this server',
        )


@_allow_browser_clients
async def _oauth_register(request):
    """Dynamic client registration (RFC 7591).

    Auth0 offers it only on Enterprise plans, so this answers with the pre-
    configured client_id to satisfy the MCP SDK.
    """
    try:
        config = _get_oauth_config()
    except ValueError as e:
        logger.error(f'OAuth config error in /oauth/register: {e}')
        return _oauth_error_response(
            _ERROR_SERVER_ERROR,
            'OAuth configuration is incomplete',
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    try:
        client_metadata = await _parse_client_metadata(request)
        _validate_redirect_uris(client_metadata)
    except _OAuthRequestError as e:
        return _reject_response(e)

    response_data = {
        'client_id': config['client_id'],
        'token_endpoint_auth_method': 'none',
    }
    # Truthful only because these URIs cleared the check /oauth/authorize applies.
    if 'redirect_uris' in client_metadata:
        response_data['redirect_uris'] = client_metadata['redirect_uris']
    if 'client_name' in client_metadata:
        response_data['client_name'] = client_metadata['client_name']

    logger.info('Dynamic client registration: returning pre-configured client_id')

    return JSONResponse(
        response_data,
        status_code=HTTPStatus.CREATED,
        headers={
            'Cache-Control': 'no-store',
        },
    )
