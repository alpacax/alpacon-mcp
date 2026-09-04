"""The /oauth/authorize endpoint."""

from http import HTTPStatus

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from utils.logger import get_logger
from utils.oauth._http import (
    _ERROR_INVALID_REQUEST,
    _OFFLINE_ACCESS_SCOPE,
    _PKCE_CHALLENGE_METHOD,
    _PKCE_CHALLENGE_PATTERN,
    _RESPONSE_TYPE_CODE,
    _auth0_authorize_url,
    _callback_url,
    _escape_for_log,
    _get_oauth_config,
    _get_server_url,
    _OAuthRequestError,
    _reject_response,
)
from utils.oauth._redirect_uris import (
    _is_allowed_redirect_uri,
    _is_pkce_exempt_redirect_uri,
)
from utils.oauth._sealing import (
    _STAGE_MFA,
    _build_state,
    _client_device_id,
    _hash_nonce,
    _mint_device_id,
    _mint_nonce,
    _set_nonce_cookie,
    _strip_device_scopes,
)

logger = get_logger('oauth')


def _probe_pkce_exemption_usage(redirect_uri: str, code_challenge_method: str) -> None:
    """Record what each client sends, to settle who reaches the exempt callback.

    Remove once no client uses the PKCE-exempt redirect_uri and no deployment
    needs report-only mode to cover a missing allowlist entry.
    """
    logger.info(
        'authorize observed - redirect_uri: %s, pkce: %s',
        _escape_for_log(redirect_uri) or '(none)',
        _escape_for_log(code_challenge_method) or 'none',
    )


def _normalize_authorize_params(request: Request, config: dict) -> tuple[dict, bool]:
    """Build the outbound Auth0 params and detect the MFA re-auth pseudo-scope.

    client_id is forced so the endpoint cannot proxy an arbitrary Auth0 client, and
    offline_access is added so Auth0 issues a refresh token. The scope leaves with
    exactly one `device:` token, the first being what the Auth0 action reads, so the
    callback can seal the code under this grant. The `mfa` pseudo-scope the 401
    middleware asks for is detected and stripped.
    """
    params = dict(request.query_params)
    params['client_id'] = config['client_id']
    if 'audience' not in params:
        params['audience'] = config['audience']
    if 'response_type' not in params:
        params['response_type'] = _RESPONSE_TYPE_CODE

    scope = params.get('scope', '')
    if _OFFLINE_ACCESS_SCOPE not in scope:
        scope = f'{scope} {_OFFLINE_ACCESS_SCOPE}'.strip()
    device_id = _client_device_id(scope) or _mint_device_id()
    scope = f'{_strip_device_scopes(scope)} device:{device_id}'.strip()

    scope_parts = scope.split()
    mfa_requested = 'mfa' in scope_parts
    if mfa_requested:
        scope = ' '.join(s for s in scope_parts if s != 'mfa')
        logger.info('MFA scope detected, will use two-stage OAuth flow')
    params['scope'] = scope

    return params, mfa_requested


def _validate_authorize_request(params: dict, client_redirect_uri: str) -> None:
    """Reject a redirect_uri or PKCE setup Auth0 must not receive.

    Only a `_PKCE_EXEMPT_REDIRECT_URIS` destination may start a flow without a
    challenge, since Copilot Studio's gateway cannot send one; every other client
    needs one that clears RFC 7636 and this server's method. With no challenge the
    method is dropped rather than forwarded uninspected.
    """
    if client_redirect_uri and not _is_allowed_redirect_uri(client_redirect_uri):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'redirect_uri must be a loopback URL or an allowlisted callback endpoint',
        )

    code_challenge = params.get('code_challenge', '')
    code_challenge_method = params.get('code_challenge_method', '')
    if not code_challenge and not _is_pkce_exempt_redirect_uri(client_redirect_uri):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'code_challenge is required; this server accepts only '
            f'{_PKCE_CHALLENGE_METHOD} PKCE',
        )
    if code_challenge and code_challenge_method != _PKCE_CHALLENGE_METHOD:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            f'code_challenge_method must be {_PKCE_CHALLENGE_METHOD}',
        )
    if code_challenge and not _PKCE_CHALLENGE_PATTERN.match(code_challenge):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'code_challenge must be 43 to 128 characters from the '
            'RFC 7636 unreserved set',
        )
    if not code_challenge:
        params.pop('code_challenge_method', None)


def _build_auth0_redirect(
    config: dict,
    server_url: str,
    params: dict,
    client_redirect_uri: str,
    mfa_requested: bool,
    original_state: str,
) -> RedirectResponse:
    """Sign the state Auth0 will echo back and redirect to it.

    A malformed ALPACON_MCP_STATE_SECRET raises here, on the endpoint an operator
    reaches first, rather than as a bare 500 at the callback. An MFA-requested
    client goes to the MFA audience first (stage 1); the callback continues to the
    regular audience (stage 2), replaying the PKCE and other authorize params
    carried in the state so the exchange succeeds with the client's verifier.
    """
    nonce = _mint_nonce()
    nonce_hash = _hash_nonce(nonce)
    device_id = _client_device_id(params['scope'])

    if mfa_requested:
        mfa_params = {
            'response_type': _RESPONSE_TYPE_CODE,
            'client_id': config['client_id'],
            'audience': config['mfa_audience'],
            'redirect_uri': _callback_url(server_url),
            'scope': 'enroll read:authenticators',
        }
        stage2_authorize_params = {
            key: params[key]
            for key in ('code_challenge', 'code_challenge_method', 'nonce', 'resource')
            if key in params
        }
        mfa_params['state'] = _build_state(
            client_redirect_uri,
            original_state,
            stage=_STAGE_MFA,
            original_scope=params['scope'],
            authorize_params=stage2_authorize_params,
            nonce_hash=nonce_hash,
            device_id=device_id,
        )
        auth0_url = _auth0_authorize_url(config, mfa_params)
        logger.info('Stage 1: Redirecting to Auth0 MFA audience for MFA verification')
    else:
        params['redirect_uri'] = _callback_url(server_url)
        params['state'] = _build_state(
            client_redirect_uri,
            original_state,
            nonce_hash=nonce_hash,
            device_id=device_id,
        )
        auth0_url = _auth0_authorize_url(config, params)
        logger.info('Redirecting to Auth0 authorize endpoint')

    response = RedirectResponse(url=auth0_url, status_code=HTTPStatus.FOUND)
    _set_nonce_cookie(response, nonce)
    return response


async def _oauth_authorize(request):
    """Redirect to Auth0's authorize endpoint with our client_id and audience."""
    try:
        config = _get_oauth_config()
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    params, mfa_requested = _normalize_authorize_params(request, config)
    client_redirect_uri = params.get('redirect_uri', '')
    original_state = params.get('state', '')
    _probe_pkce_exemption_usage(
        client_redirect_uri, params.get('code_challenge_method', '')
    )

    try:
        _validate_authorize_request(params, client_redirect_uri)
    except _OAuthRequestError as e:
        return _reject_response(e)

    try:
        return _build_auth0_redirect(
            config,
            _get_server_url(request),
            params,
            client_redirect_uri,
            mfa_requested,
            original_state,
        )
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )
