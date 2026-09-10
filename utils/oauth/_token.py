"""The /oauth/token endpoint."""

import json
from http import HTTPStatus
from urllib.parse import parse_qs

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from utils.logger import get_logger
from utils.oauth._http import (
    _ALLOWED_GRANT_TYPES,
    _ERROR_INVALID_CLIENT,
    _ERROR_INVALID_GRANT,
    _ERROR_INVALID_REQUEST,
    _ERROR_SERVER_ERROR,
    _ERROR_UNSUPPORTED_GRANT_TYPE,
    _FORM_CONTENT_TYPE,
    _GRANT_AUTHORIZATION_CODE,
    _JSON_CONTENT_TYPE,
    _allow_browser_clients,
    _auth0_token_url,
    _callback_url,
    _get_oauth_config,
    _get_server_url,
    _oauth_error_response,
    _OAuthRequestError,
    _read_bounded_body,
    _reject_response,
)
from utils.oauth._sealing import (
    _log_unsealed_rejection,
    _seal_refresh_token,
    _strip_device_scopes,
    _unseal_code,
    _unseal_refresh_token,
)

logger = get_logger('oauth')


async def _parse_token_request(request: Request) -> dict:
    """Read and decode the token request body, then validate grant_type.

    grant_type gates the allow-list and the injected client_secret, so it must be
    present; checking it is a str first keeps a JSON body's unhashable value from
    raising on the membership test instead of answering 400.
    """
    body = await _read_bounded_body(request)
    if body is None:
        raise _OAuthRequestError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            _ERROR_INVALID_REQUEST,
            'Request body is too large',
        )
    content_type = request.headers.get('content-type', '')

    if _JSON_CONTENT_TYPE in content_type:
        try:
            params = json.loads(body)
        except json.JSONDecodeError:
            raise _OAuthRequestError(
                HTTPStatus.BAD_REQUEST, _ERROR_INVALID_REQUEST, 'Invalid JSON'
            ) from None
        if not isinstance(params, dict):
            raise _OAuthRequestError(
                HTTPStatus.BAD_REQUEST,
                _ERROR_INVALID_REQUEST,
                'Request body must be a JSON object',
            )
    else:
        try:
            decoded_body = body.decode('utf-8')
        except UnicodeDecodeError:
            raise _OAuthRequestError(
                HTTPStatus.BAD_REQUEST,
                _ERROR_INVALID_REQUEST,
                'Request body must be UTF-8 encoded',
            ) from None
        parsed = parse_qs(decoded_body)
        params = {k: v[0] for k, v in parsed.items()}

    grant_type = params.get('grant_type', '')
    if not isinstance(grant_type, str) or not grant_type:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'grant_type must be a non-empty string',
        )
    if grant_type not in _ALLOWED_GRANT_TYPES:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_UNSUPPORTED_GRANT_TYPE,
            f'Grant type "{grant_type}" is not supported. '
            f'Allowed: {", ".join(sorted(_ALLOWED_GRANT_TYPES))}',
        )
    return params


def _inject_client_credentials(params: dict, config: dict) -> None:
    """Force this endpoint's client_id and secret and drop any client device scope.

    A mismatched client_id would make this a generic credential exchange against the
    injected secret, so it is rejected, not overridden. The `device:` scope is
    stripped so a client-supplied one cannot outrank the sealed id injected after
    unsealing; a non-str scope is dropped, and an empty result drops the key, since
    RFC 6749 reads an absent scope as the grant's own.
    """
    configured_client_id = config['client_id']
    provided_client_id = params.get('client_id')
    if provided_client_id and provided_client_id != configured_client_id:
        logger.warning(
            'Rejected /oauth/token request with mismatched client_id: %s',
            provided_client_id,
        )
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT,
            'client_id is not allowed for this endpoint',
        )
    params['client_id'] = configured_client_id
    params['client_secret'] = config['client_secret']

    scope = params.pop('scope', None)
    if isinstance(scope, str):
        stripped = _strip_device_scopes(scope)
        if stripped:
            params['scope'] = stripped


def _replace_sealed_grant(params: dict) -> str:
    """Unseal the code or refresh_token, binding the exchange to its grant.

    An unsealed value, tampered or issued before sealing, would refresh under a key
    shared by every session of the user, so the client is sent to a fresh login
    instead. A client-supplied device id never reaches Auth0: dropped for the code
    grant, which already sent it in the /authorize scope, and overwritten for the
    refresh grant, which may omit scope.
    """
    grant_type = params['grant_type']
    if grant_type == _GRANT_AUTHORIZATION_CODE:
        raw = params.get('code')
        unsealed = _unseal_code(raw)
        what = 'authorization code'
    else:
        raw = params.get('refresh_token')
        unsealed = _unseal_refresh_token(raw)
        what = 'refresh token'

    if unsealed is None:
        _log_unsealed_rejection(what, raw)
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_GRANT,
            f'The {what} was not issued by this server',
        )

    value, sealed_device_id = unsealed
    if grant_type == _GRANT_AUTHORIZATION_CODE:
        params['code'] = value
        params.pop('device_id', None)
    else:
        params['refresh_token'] = value
        params['device_id'] = sealed_device_id
    return sealed_device_id


async def _exchange_with_auth0(
    config: dict, params: dict, sealed_device_id: str
) -> JSONResponse:
    """POST the token request to Auth0 and reseal any refresh token it returns.

    Every refresh token that leaves here is sealed under the grant's device
    id, or the next refresh loses that binding.
    """
    auth0_token_url = _auth0_token_url(config)
    logger.info(
        'Proxying token request to Auth0 - grant_type: %s, has_refresh_token: %s',
        params.get('grant_type'),
        'refresh_token' in params,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                auth0_token_url,
                data=params,
                headers={'Content-Type': _FORM_CONTENT_TYPE},
            )

        try:
            response_data = response.json()
        except Exception:
            logger.warning(f'Auth0 returned non-JSON response: {response.status_code}')
            response_data = {
                'error': _ERROR_SERVER_ERROR,
                'error_description': 'Auth0 returned unexpected response format',
            }

        if (
            sealed_device_id
            and response.status_code == HTTPStatus.OK
            and isinstance(response_data, dict)
            and isinstance(response_data.get('refresh_token'), str)
        ):
            response_data['refresh_token'] = _seal_refresh_token(
                response_data['refresh_token'], sealed_device_id
            )

        if isinstance(response_data, dict):
            if response.status_code == HTTPStatus.OK:
                logger.debug(
                    'Auth0 token response - grant_type: %s, '
                    'has_access_token: %s, has_refresh_token: %s, '
                    'expires_in: %s',
                    params.get('grant_type'),
                    'access_token' in response_data,
                    'refresh_token' in response_data,
                    response_data.get('expires_in'),
                )
            else:
                logger.warning(
                    'Auth0 token request failed - grant_type: %s, '
                    'status: %s, error: %s',
                    params.get('grant_type'),
                    response.status_code,
                    response_data.get('error', 'unknown'),
                )
        else:
            logger.warning(
                'Auth0 token response is not a dict - grant_type: %s, '
                'status: %s, type: %s',
                params.get('grant_type'),
                response.status_code,
                type(response_data).__name__,
            )

        return JSONResponse(
            response_data,
            status_code=response.status_code,
            headers={
                'Cache-Control': 'no-store',
                'Pragma': 'no-cache',
            },
        )
    except httpx.HTTPError as e:
        logger.error(f'Auth0 token request failed: {e}')
        return _oauth_error_response(
            _ERROR_SERVER_ERROR,
            'Failed to communicate with Auth0',
            status=HTTPStatus.BAD_GATEWAY,
        )


@_allow_browser_clients
async def _oauth_token(request):
    """Proxy the token exchange to Auth0 with the configured client_id and secret."""
    try:
        config = _get_oauth_config()
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    try:
        params = await _parse_token_request(request)
        _inject_client_credentials(params, config)
        sealed_device_id = _replace_sealed_grant(params)
    except _OAuthRequestError as e:
        return _reject_response(e)

    # Auth0 requires this to match /authorize's exactly, which always sent one.
    if params.get('grant_type') == _GRANT_AUTHORIZATION_CODE:
        params['redirect_uri'] = _callback_url(_get_server_url(request))

    return await _exchange_with_auth0(config, params, sealed_device_id)
