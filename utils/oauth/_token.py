"""The token endpoint: proxies code and refresh exchanges to Auth0."""

import json
from http import HTTPStatus
from urllib.parse import parse_qs

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from utils.ledger_grant import wrap_access_token
from utils.logger import escape_for_log
from utils.oauth._http import (
    _AUTH0_TIMEOUT_SECONDS,
    _AUTH0_TOKEN_PATH,
    _CACHE_CONTROL_NO_STORE,
    _ERROR_INVALID_CLIENT,
    _ERROR_INVALID_REQUEST,
    _ERROR_SERVER_ERROR,
    _ERROR_UNSUPPORTED_GRANT_TYPE,
    _FORM_HEADERS,
    _GRANT_AUTHORIZATION_CODE,
    _GRANT_REFRESH_TOKEN,
    _JSON_CONTENT_TYPE,
    _MFA_SCOPE,
    _allow_browser_clients,
    _callback_url,
    _get_server_url,
    _oauth_error_response,
    _OAuthRequestError,
    _read_bounded_body,
    _require_oauth_config,
    logger,
)
from utils.oauth._ledger import _carried_ledger_grant, _strip_ledger_scopes
from utils.oauth._sealing import (
    _SEAL_KIND_CODE,
    _SEAL_KIND_REFRESH,
    _open_seal,
    _OpenedSeal,
    _reject_unsealed,
    _seal_refresh_token,
    _strip_device_scopes,
    ledger_grant_key,
)

_ALLOWED_GRANT_TYPES = frozenset({_GRANT_AUTHORIZATION_CODE, _GRANT_REFRESH_TOKEN})


@_allow_browser_clients
async def oauth_token(request: Request) -> Response:
    """Proxy token exchange to Auth0, injecting client_id and client_secret; allows
    only authorization_code and refresh_token grants, over sealed values."""
    try:
        config = _require_oauth_config()
        params = await _parse_token_request(request)
        grant_type = _require_grant_type(params)
        _inject_client_credentials(params, config)
        _strip_client_scope(params)
        grant = _unseal_grant(params, grant_type)
        # Auth0 requires the redirect_uri /authorize sent, which is always ours.
        if grant_type == _GRANT_AUTHORIZATION_CODE:
            params['redirect_uri'] = _callback_url(_get_server_url(request))
        return await _proxy_token_request(config, params, grant_type, grant)
    except _OAuthRequestError as e:
        return e.response


async def _parse_token_request(request: Request) -> dict[str, object]:
    """The token request's parameters, from a JSON object or a form body."""
    body = await _read_bounded_body(request)
    if body is None:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REQUEST,
                'Request body is too large',
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        )
    content_type = request.headers.get('content-type', '')

    if _JSON_CONTENT_TYPE in content_type:
        try:
            params = json.loads(body)
        except json.JSONDecodeError:
            raise _OAuthRequestError(
                _oauth_error_response(_ERROR_INVALID_REQUEST, 'Invalid JSON')
            ) from None
        if not isinstance(params, dict):
            raise _OAuthRequestError(
                _oauth_error_response(
                    _ERROR_INVALID_REQUEST, 'Request body must be a JSON object'
                )
            )
        return params

    try:
        decoded_body = body.decode('utf-8')
    except UnicodeDecodeError:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REQUEST, 'Request body must be UTF-8 encoded'
            )
        ) from None
    return {k: v[0] for k, v in parse_qs(decoded_body).items()}


def _require_grant_type(params: dict[str, object]) -> str:
    """The grant type, required: both unseal branches key off it, so an absent one
    would reach Auth0 with the client_secret and no seal check."""
    grant_type = params.get('grant_type', '')
    # A JSON body can send any type, and an unhashable one would raise on the
    # membership test rather than answer 400.
    if not isinstance(grant_type, str) or not grant_type:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REQUEST, 'grant_type must be a non-empty string'
            )
        )
    if grant_type not in _ALLOWED_GRANT_TYPES:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_UNSUPPORTED_GRANT_TYPE,
                f'Grant type "{grant_type}" is not supported. '
                f'Allowed: {", ".join(sorted(_ALLOWED_GRANT_TYPES))}',
            )
        )
    return grant_type


def _inject_client_credentials(
    params: dict[str, object], config: dict[str, str]
) -> None:
    """Set the configured client_id and secret, refusing any other client_id so this
    endpoint is no generic token proxy for arbitrary Auth0 clients."""
    configured_client_id = config['client_id']
    provided_client_id = params.get('client_id')
    if provided_client_id and provided_client_id != configured_client_id:
        logger.warning(
            'Rejected /oauth/token request with mismatched client_id: %s',
            escape_for_log(provided_client_id),
        )
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_CLIENT, 'client_id is not allowed for this endpoint'
            )
        )
    params['client_id'] = configured_client_id
    params['client_secret'] = config['client_secret']


def _strip_client_scope(params: dict[str, object]) -> None:
    """Drop `device:` tokens, which the Auth0 action reads ahead of the sealed id, and
    the mfa and `ledger:` pseudo-scopes; a non-str or emptied scope goes entirely."""
    # httpx sends a JSON list the action cannot tell from a string, and RFC 6749
    # reads an omitted scope as the grant's own but says nothing of an empty one.
    scope = params.pop('scope', None)
    if isinstance(scope, str):
        stripped = ' '.join(
            part
            for part in _strip_ledger_scopes(_strip_device_scopes(scope)).split()
            if part != _MFA_SCOPE
        )
        if stripped:
            params['scope'] = stripped


def _unseal_grant(params: dict[str, object], grant_type: str) -> _OpenedSeal:
    """Swap the sealed code or refresh token in `params` for the Auth0 value. An
    unsealed one would refresh under a key every session of the user shares."""
    if grant_type == _GRANT_AUTHORIZATION_CODE:
        opened = _open_seal(_SEAL_KIND_CODE, params.get('code', ''))
        if opened is None:
            _reject_unsealed('authorization code', params.get('code'))
        params['code'] = opened.value
        # The code carried the id in the scope sent to /authorize.
        params.pop('device_id', None)
        return opened

    opened = _open_seal(_SEAL_KIND_REFRESH, params.get('refresh_token', ''))
    if opened is None:
        _reject_unsealed('refresh token', params.get('refresh_token'))
    params['refresh_token'] = opened.value
    # A refresh may omit scope, so the id rides the body field the action also reads.
    params['device_id'] = opened.device_id
    return opened


async def _proxy_token_request(
    config: dict[str, str],
    params: dict[str, object],
    grant_type: str,
    grant: _OpenedSeal,
) -> Response:
    logger.info(
        'Proxying token request to Auth0 - grant_type: %s, has_refresh_token: %s',
        grant_type,
        'refresh_token' in params,
    )
    try:
        async with httpx.AsyncClient(timeout=_AUTH0_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f'{config["auth0_base_url"]}{_AUTH0_TOKEN_PATH}',
                data=params,
                headers=_FORM_HEADERS,
            )
        return _token_response(response, grant_type, grant)
    except httpx.HTTPError as e:
        logger.error('Auth0 token request failed: %s', e)
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_SERVER_ERROR,
                'Failed to communicate with Auth0',
                status=HTTPStatus.BAD_GATEWAY,
            )
        ) from e


def _token_response(
    response: httpx.Response, grant_type: str, grant: _OpenedSeal
) -> JSONResponse:
    """Auth0's answer with the ledger grant wrapped into the access token and the
    refresh token sealed, status kept."""
    try:
        response_data = response.json()
    except Exception:
        logger.warning('Auth0 returned non-JSON response: %s', response.status_code)
        response_data = {
            'error': _ERROR_SERVER_ERROR,
            'error_description': 'Auth0 returned unexpected response format',
        }

    # The ledger allows no refresh, so a grant rides only until its own expiry
    # and a lapsed one is dropped here.
    carried = None
    if response.status_code == HTTPStatus.OK and isinstance(response_data, dict):
        carried = _carried_ledger_grant(grant.ledger, response_data.get('access_token'))
    if carried is not None:
        response_data['access_token'] = wrap_access_token(
            ledger_grant_key(), response_data['access_token'], carried
        )

    # Auth0 rotates refresh tokens, so every one that leaves here is sealed under
    # the grant's id or the next refresh loses it.
    if (
        grant.device_id
        and response.status_code == HTTPStatus.OK
        and isinstance(response_data, dict)
        and isinstance(response_data.get('refresh_token'), str)
    ):
        response_data['refresh_token'] = _seal_refresh_token(
            response_data['refresh_token'],
            grant.device_id,
            grant.ledger if carried is not None else '',
        )

    _log_token_response(response.status_code, response_data, grant_type)
    return JSONResponse(
        response_data,
        status_code=response.status_code,
        headers={
            'Cache-Control': _CACHE_CONTROL_NO_STORE,
            'Pragma': 'no-cache',
        },
    )


def _log_token_response(
    status_code: int, response_data: object, grant_type: str
) -> None:
    if isinstance(response_data, dict):
        if status_code == HTTPStatus.OK:
            logger.debug(
                'Auth0 token response - grant_type: %s, '
                'has_access_token: %s, has_refresh_token: %s, '
                'expires_in: %s',
                grant_type,
                'access_token' in response_data,
                'refresh_token' in response_data,
                response_data.get('expires_in'),
            )
        else:
            logger.warning(
                'Auth0 token request failed - grant_type: %s, status: %s, error: %s',
                grant_type,
                status_code,
                escape_for_log(response_data.get('error', 'unknown')),
            )
    else:
        logger.warning(
            'Auth0 token response is not a dict - grant_type: %s, status: %s, type: %s',
            grant_type,
            status_code,
            type(response_data).__name__,
        )
