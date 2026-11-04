"""The callback endpoint: the later legs of the sign-in flow."""

from dataclasses import dataclass, field, replace
from http import HTTPStatus
from typing import NoReturn

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from utils.ledger_grant import LedgerGrant, seal_stage
from utils.logger import escape_for_log
from utils.oauth._http import (
    _AUTH0_TIMEOUT_SECONDS,
    _AUTH0_TOKEN_PATH,
    _DEFAULT_SCOPES,
    _ERROR_INVALID_REQUEST,
    _FORM_HEADERS,
    _GRANT_AUTHORIZATION_CODE,
    _REPLAYED_AUTHORIZE_PARAMS,
    _RESPONSE_TYPE_CODE,
    _auth0_authorize_url,
    _build_redirect_url,
    _callback_url,
    _get_oauth_config,
    _get_server_url,
    _misconfiguration_response,
    _oauth_error_response,
    _OAuthRequestError,
    _require_oauth_config,
    logger,
)
from utils.oauth._ledger import (
    _clear_ledger_cookie,
    _exchange_ledger_code,
    _ledger_stage_url,
    _ledger_state,
    _set_ledger_cookie,
    _staged_ledger_grant,
)
from utils.oauth._redirect_uris import _is_allowed_redirect_uri
from utils.oauth._sealing import (
    _NONCE_COOKIE_NAME,
    _STAGE_LEDGER,
    _STAGE_MFA,
    _STAGE_REGULAR,
    _build_state,
    _clear_nonce_cookie,
    _is_device_id,
    _nonce_cookie_matches,
    _seal_code,
    _set_nonce_cookie,
    _state_str,
    _verify_state,
    ledger_grant_key,
)


async def oauth_callback(request: Request) -> Response:
    """Handle the Auth0 callback after state and nonce-cookie checks. Stage 'mfa'
    redirects on to Stage 2; otherwise a sealed code goes to the client."""
    code = request.query_params.get('code')
    error = request.query_params.get('error')
    error_description = request.query_params.get('error_description', '')
    try:
        state = _restore_callback_state(request)
        # Before the error branch: an Auth0 refusal of the ledger leg (say, the
        # person left that organization) must not cost them the regular sign-in.
        if state.stage == _STAGE_LEDGER and state.ledger_org:
            return await _complete_ledger_stage(
                request, state, code, error, error_description
            )
        if error:
            return _forward_auth0_error(state, error, error_description)
        if not code:
            return _oauth_error_response(
                _ERROR_INVALID_REQUEST, 'Missing authorization code'
            )
        if state.stage == _STAGE_MFA:
            return await _complete_mfa_stage(request, state, code)
        return _deliver_code(request, state, code)
    except _OAuthRequestError as e:
        return e.response


@dataclass(frozen=True)
class _CallbackState:
    """What the callback recovers from a verified state; all empty without one."""

    client_redirect_uri: str = ''
    original_state: str = ''
    stage: str = ''
    original_scope: str = ''
    nonce_hash: str = ''
    device_id: str = ''
    ledger_org: str = ''
    authorize_params: dict[str, object] = field(default_factory=dict)


def _restore_callback_state(request: Request) -> _CallbackState:
    """The verified state, with a redirect_uri no longer allowed blanked out."""
    composite_state = request.query_params.get('state')
    # An absent state is not rejected: Auth0 error callbacks can arrive without
    # one, and it names no redirect target a forgery could steer.
    state = (
        _verify_callback_state(request, composite_state)
        if composite_state
        else _CallbackState()
    )
    # Authorize checked it already, but a state crafted directly could reach
    # Auth0 with our callback URL.
    if state.client_redirect_uri and not _is_allowed_redirect_uri(
        state.client_redirect_uri
    ):
        logger.warning(
            'Callback rejected untrusted redirect_uri from state: %s',
            escape_for_log(state.client_redirect_uri),
        )
        return replace(state, client_redirect_uri='')
    return state


def _verify_callback_state(request: Request, composite_state: str) -> _CallbackState:
    """Refuse a state that is forged, expired, bound to another browser, or without
    a device id."""
    try:
        state_data = _verify_state(composite_state)
    except ValueError as e:
        # Without an explicit state secret, verification needs the OAuth config.
        raise _OAuthRequestError(_misconfiguration_response(e)) from e
    if state_data is None:
        _reject_callback_state('Callback rejected an invalid or expired state')
    # Ahead of the error branch so the gate lives in one spot; an error callback
    # carries no code, so nothing is lost by rejecting it.
    if not _nonce_cookie_matches(request, state_data):
        _reject_callback_state('Callback rejected a state not bound to this browser')
    # Every state this server mints carries an id; without one the code could
    # not be sealed and the exchange would refuse it anyway.
    device_id = _state_str(state_data, 'device_id')
    if not _is_device_id(device_id):
        _reject_callback_state('Callback rejected a state without a device id')
    stored_params = state_data.get('authorize_params')
    return _CallbackState(
        client_redirect_uri=_state_str(state_data, 'redirect_uri'),
        original_state=_state_str(state_data, 'state'),
        stage=_state_str(state_data, 'stage'),
        original_scope=_state_str(state_data, 'original_scope'),
        nonce_hash=_state_str(state_data, 'nonce_hash'),
        device_id=device_id,
        ledger_org=_state_str(state_data, 'ledger_org'),
        authorize_params=stored_params if isinstance(stored_params, dict) else {},
    )


def _reject_callback_state(log_message: str) -> NoReturn:
    logger.warning(log_message)
    raise _OAuthRequestError(
        _oauth_error_response(
            _ERROR_INVALID_REQUEST, 'Invalid or expired state parameter'
        )
    )


async def _complete_ledger_stage(
    request: Request,
    state: _CallbackState,
    code: str | None,
    error: str | None,
    error_description: str,
) -> Response:
    """Stage the ledger token, or a failure record, in a cookie and redirect on to
    the regular audience."""
    try:
        config = _get_oauth_config()
        key = ledger_grant_key()
    except ValueError as e:
        raise _OAuthRequestError(_misconfiguration_response(e)) from e
    server_url = _get_server_url(request)
    grant = None
    if error:
        logger.warning(
            'Ledger stage refused by Auth0: %s - %s',
            escape_for_log(error),
            escape_for_log(error_description),
        )
    elif code:
        grant = await _exchange_ledger_code(config, server_url, code, state.ledger_org)
    # A failure record stops the ledger tool from asking again at once.
    staged = grant or LedgerGrant.failed(state.ledger_org)

    response = RedirectResponse(
        url=_final_stage_url(config, server_url, state),
        status_code=HTTPStatus.FOUND,
    )
    _set_nonce_cookie(response, request.cookies[_NONCE_COOKIE_NAME])
    _set_ledger_cookie(response, seal_stage(key, staged, state.nonce_hash))
    logger.info(
        'Ledger stage complete (token obtained: %s); redirecting to the '
        'regular audience',
        grant is not None,
    )
    return response


def _forward_auth0_error(
    state: _CallbackState, error: str, error_description: str
) -> Response:
    """Relay Auth0's error to the client's redirect_uri, or answer it as JSON."""
    logger.warning(
        'Auth0 callback error: %s - %s',
        escape_for_log(error),
        escape_for_log(error_description),
    )
    if state.client_redirect_uri:
        params = {'error': error, 'error_description': error_description}
        if state.original_state:
            params['state'] = state.original_state
        return RedirectResponse(
            url=_build_redirect_url(state.client_redirect_uri, params),
            status_code=HTTPStatus.FOUND,
        )
    return _oauth_error_response(error, error_description)


async def _complete_mfa_stage(
    request: Request, state: _CallbackState, code: str
) -> Response:
    """Exchange the MFA code for its side effect, then redirect on to the ledger
    stage if one was asked, else to the regular audience."""
    logger.info(
        'Stage 1 complete: MFA authorization code received, '
        'exchanging and proceeding to Stage 2 (regular audience)'
    )
    config = _require_oauth_config()
    server_url = _get_server_url(request)
    await _confirm_mfa_completion(config, server_url, code)

    if state.ledger_org:
        # The ledger stage hands over to the regular audience itself.
        auth0_url = _ledger_stage_url(
            config,
            server_url,
            _build_state(
                state.client_redirect_uri,
                state.original_state,
                stage=_STAGE_LEDGER,
                original_scope=state.original_scope,
                authorize_params=state.authorize_params,
                nonce_hash=state.nonce_hash,
                device_id=state.device_id,
                ledger_org=state.ledger_org,
            ),
            state.ledger_org,
            state.device_id,
        )
        logger.info('Stage 2: Redirecting to Auth0 for the ledger audience')
    else:
        auth0_url = _final_stage_url(config, server_url, state)
        logger.info('Stage 2: Redirecting to Auth0 regular audience (SSO)')
    response = RedirectResponse(url=auth0_url, status_code=HTTPStatus.FOUND)
    # The next stage restarts the state expiry; re-set the cookie so the two
    # do not drift apart.
    _set_nonce_cookie(response, request.cookies[_NONCE_COOKIE_NAME])
    return response


async def _confirm_mfa_completion(
    config: dict[str, str], server_url: str, code: str
) -> None:
    """Exchange the MFA code and discard the token: only the MFA completion it leaves
    in the Auth0 session matters, so a failure is logged and the flow goes on."""
    try:
        async with httpx.AsyncClient(timeout=_AUTH0_TIMEOUT_SECONDS) as client:
            mfa_response = await client.post(
                f'{config["auth0_base_url"]}{_AUTH0_TOKEN_PATH}',
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': code,
                    'redirect_uri': _callback_url(server_url),
                    'client_id': config['client_id'],
                    'client_secret': config['client_secret'],
                },
                headers=_FORM_HEADERS,
            )
            if mfa_response.status_code >= HTTPStatus.BAD_REQUEST:
                logger.warning(
                    'MFA token exchange returned %s (non-fatal): %s',
                    mfa_response.status_code,
                    escape_for_log(mfa_response.text, max_chars=200),
                )
            else:
                logger.info('MFA token exchange succeeded (token discarded)')
    except httpx.HTTPError as e:
        logger.warning('MFA token exchange failed (non-fatal): %s', e)


def _final_stage_url(
    config: dict[str, str], server_url: str, state: _CallbackState
) -> str:
    """Auth0 authorize URL for the regular audience after an earlier stage (SSO);
    `ledger_org` stays in the state so the last callback finds the staged grant."""
    params = {
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
            **_ledger_state(state.ledger_org),
        ),
    }
    for key, value in state.authorize_params.items():
        if key in _REPLAYED_AUTHORIZE_PARAMS and isinstance(value, str):
            params[key] = value
    return _auth0_authorize_url(config, params)


def _deliver_code(request: Request, state: _CallbackState, code: str) -> Response:
    """Seal the code under the grant's device id and staged ledger grant, then hand
    it to the client's redirect_uri, or as JSON when there is none."""
    logger.info('Auth0 callback received authorization code')

    # The token exchange sees no state, so the code carries the id the refresh
    # token is sealed under; a code that arrived without a state has none.
    if not _is_device_id(state.device_id):
        logger.warning('Callback rejected a code that arrived without a state')
        raise _OAuthRequestError(
            _oauth_error_response(_ERROR_INVALID_REQUEST, 'Missing state parameter')
        )
    try:
        sealed_code = _seal_code(
            code,
            state.device_id,
            _staged_ledger_grant(request, state.ledger_org, state.nonce_hash),
        )
    except ValueError as e:
        raise _OAuthRequestError(_misconfiguration_response(e)) from e

    params = {'code': sealed_code}
    if state.original_state:
        params['state'] = state.original_state
    response: Response
    if state.client_redirect_uri:
        response = RedirectResponse(
            url=_build_redirect_url(state.client_redirect_uri, params),
            status_code=HTTPStatus.FOUND,
        )
    else:
        response = JSONResponse(params)
    _clear_nonce_cookie(response)
    if state.ledger_org:
        _clear_ledger_cookie(response)
    return response
