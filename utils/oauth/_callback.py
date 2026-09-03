"""The /oauth/callback endpoint Auth0 returns to."""

from dataclasses import dataclass, field
from http import HTTPStatus

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from utils.logger import get_logger
from utils.oauth._http import (
    _DEFAULT_SCOPES,
    _ERROR_INVALID_REQUEST,
    _FORM_CONTENT_TYPE,
    _GRANT_AUTHORIZATION_CODE,
    _RESPONSE_TYPE_CODE,
    _auth0_authorize_url,
    _auth0_token_url,
    _build_redirect_url,
    _callback_url,
    _escape_for_log,
    _get_oauth_config,
    _get_server_url,
    _oauth_error_response,
    _OAuthRequestError,
    _reject_response,
)
from utils.oauth._redirect_uris import _is_allowed_redirect_uri
from utils.oauth._sealing import (
    _NONCE_COOKIE_NAME,
    _STAGE_MFA,
    _STAGE_REGULAR,
    _build_state,
    _clear_nonce_cookie,
    _is_device_id,
    _nonce_cookie_matches,
    _seal_code,
    _set_nonce_cookie,
    _verify_state,
)

logger = get_logger('oauth')


@dataclass
class _CallbackState:
    """The authorize-time context recovered from a callback's signed state."""

    client_redirect_uri: str = ''
    original_state: str = ''
    stage: str = ''
    original_scope: str = ''
    nonce_hash: str = ''
    device_id: str = ''
    authorize_params: dict = field(default_factory=dict)


def _restore_callback_state(request: Request) -> _CallbackState:
    """Recover the authorize-time context from the signed state, or reject it.

    An absent state is not rejected: an Auth0 error callback may arrive without one,
    and it names no redirect target a forgery could steer. The nonce-cookie check
    runs before the caller looks at `error` so the gate lives in one place. A state
    without a device id is rejected, since the code could never be sealed. The
    redirect_uri in the state is re-checked as defense in depth: a forged state
    could name our callback directly.
    """
    composite_state = request.query_params.get('state')
    state = _CallbackState()
    if not composite_state:
        return state

    try:
        state_data = _verify_state(composite_state)
    except ValueError as e:
        raise _OAuthRequestError(HTTPStatus.INTERNAL_SERVER_ERROR, str(e)) from e
    if state_data is None:
        logger.warning('Callback rejected an invalid or expired state')
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'Invalid or expired state parameter',
        )
    if not _nonce_cookie_matches(request, state_data):
        logger.warning('Callback rejected a state not bound to this browser')
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'Invalid or expired state parameter',
        )

    state.client_redirect_uri = state_data.get('redirect_uri', '')
    state.original_state = state_data.get('state', '')
    state.stage = state_data.get('stage', '')
    state.original_scope = state_data.get('original_scope', '')
    state.nonce_hash = state_data.get('nonce_hash', '')
    state.authorize_params = state_data.get('authorize_params', {})
    state.device_id = state_data.get('device_id', '')
    if not isinstance(state.device_id, str) or not _is_device_id(state.device_id):
        logger.warning('Callback rejected a state without a device id')
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'Invalid or expired state parameter',
        )

    if state.client_redirect_uri and not _is_allowed_redirect_uri(
        state.client_redirect_uri
    ):
        logger.warning(
            'Callback rejected untrusted redirect_uri from state: %s',
            _escape_for_log(state.client_redirect_uri),
        )
        state.client_redirect_uri = ''

    return state


def _forward_auth0_error(
    client_redirect_uri: str, original_state: str, error: str, error_description: str
) -> Response:
    """Relay an Auth0-reported error to the client, or answer it directly."""
    logger.warning(f'Auth0 callback error: {error} - {error_description}')
    if client_redirect_uri:
        params = {'error': error, 'error_description': error_description or ''}
        if original_state:
            params['state'] = original_state
        return RedirectResponse(
            url=_build_redirect_url(client_redirect_uri, params),
            status_code=HTTPStatus.FOUND,
        )
    return _oauth_error_response(error, error_description)


async def _handle_mfa_stage1(request: Request, state: _CallbackState) -> Response:
    """Confirm MFA in the Auth0 session, then redirect to the regular audience.

    The MFA code is exchanged only for its effect on the Auth0 SSO session; the
    token is discarded, so every failure here is logged, not surfaced. Stage 1
    client params are replayed into stage 2 only from a dict-shaped, allow-listed
    set, so a forged state cannot inject params. Stage 2 restarts the state's
    expiry, so the nonce cookie is re-set to match.
    """
    logger.info(
        'Stage 1 complete: MFA authorization code received, '
        'exchanging and proceeding to Stage 2 (regular audience)'
    )

    try:
        config = _get_oauth_config()
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    server_url = _get_server_url(request)
    code = request.query_params.get('code')

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            mfa_response = await client.post(
                _auth0_token_url(config),
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': code,
                    'redirect_uri': _callback_url(server_url),
                    'client_id': config['client_id'],
                    'client_secret': config['client_secret'],
                },
                headers={'Content-Type': _FORM_CONTENT_TYPE},
            )
            if mfa_response.status_code >= HTTPStatus.BAD_REQUEST:
                logger.warning(
                    'MFA token exchange returned %s (non-fatal): %s',
                    mfa_response.status_code,
                    mfa_response.text[:200],
                )
            else:
                logger.info('MFA token exchange succeeded (token discarded)')
    except httpx.HTTPError as e:
        logger.warning(f'MFA token exchange failed (non-fatal): {e}')

    stage2_params = {
        'response_type': _RESPONSE_TYPE_CODE,
        'client_id': config['client_id'],
        'audience': config['audience'],
        'redirect_uri': _callback_url(server_url),
        'scope': state.original_scope or ' '.join(_DEFAULT_SCOPES),
        'state': _build_state(
            state.client_redirect_uri,
            state.original_state,
            stage=_STAGE_REGULAR,
            nonce_hash=state.nonce_hash,
            device_id=state.device_id,
        ),
    }
    _ALLOWED_REPLAY_KEYS = {
        'code_challenge',
        'code_challenge_method',
        'nonce',
        'resource',
    }
    if isinstance(state.authorize_params, dict):
        for key, value in state.authorize_params.items():
            if key in _ALLOWED_REPLAY_KEYS and isinstance(value, str):
                stage2_params[key] = value

    auth0_url = _auth0_authorize_url(config, stage2_params)
    logger.info('Stage 2: Redirecting to Auth0 regular audience (SSO)')
    response = RedirectResponse(url=auth0_url, status_code=HTTPStatus.FOUND)
    _set_nonce_cookie(response, request.cookies[_NONCE_COOKIE_NAME])
    return response


def _deliver_code(code: str, state: _CallbackState) -> Response:
    """Seal the code to this grant's device id and hand it back to the client.

    A code that arrived without a state has no device id to seal under and would die
    at the token exchange, so it is rejected here.
    """
    if not _is_device_id(state.device_id):
        logger.warning('Callback rejected a code that arrived without a state')
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST, _ERROR_INVALID_REQUEST, 'Missing state parameter'
        )
    try:
        sealed_code = _seal_code(code, state.device_id)
    except ValueError as e:
        raise _OAuthRequestError(HTTPStatus.INTERNAL_SERVER_ERROR, str(e)) from e

    if state.client_redirect_uri:
        params = {'code': sealed_code}
        if state.original_state:
            params['state'] = state.original_state
        response = RedirectResponse(
            url=_build_redirect_url(state.client_redirect_uri, params),
            status_code=HTTPStatus.FOUND,
        )
        _clear_nonce_cookie(response)
        return response

    result = {'code': sealed_code}
    if state.original_state:
        result['state'] = state.original_state
    response = JSONResponse(result)
    _clear_nonce_cookie(response)
    return response


async def _oauth_callback(request):
    """Handle the Auth0 callback.

    In the MFA stage, exchange the code and redirect to the regular audience;
    otherwise forward the code to the MCP client.
    """
    code = request.query_params.get('code')
    error = request.query_params.get('error')
    error_description = request.query_params.get('error_description')

    try:
        state = _restore_callback_state(request)

        if error:
            return _forward_auth0_error(
                state.client_redirect_uri,
                state.original_state,
                error,
                error_description,
            )
        if not code:
            raise _OAuthRequestError(
                HTTPStatus.BAD_REQUEST,
                _ERROR_INVALID_REQUEST,
                'Missing authorization code',
            )

        if state.stage == _STAGE_MFA:
            return await _handle_mfa_stage1(request, state)

        logger.info('Auth0 callback received authorization code')
        return _deliver_code(code, state)
    except _OAuthRequestError as e:
        return _reject_response(e)
