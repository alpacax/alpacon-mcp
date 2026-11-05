"""The authorize endpoint: the first leg of the sign-in flow."""

import re
from http import HTTPStatus
from typing import NamedTuple

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from utils.logger import escape_for_log
from utils.oauth._http import (
    _ERROR_INVALID_REQUEST,
    _MFA_SCOPE,
    _OFFLINE_ACCESS_SCOPE,
    _PKCE_CHALLENGE_METHOD,
    _REPLAYED_AUTHORIZE_PARAMS,
    _RESPONSE_TYPE_CODE,
    _auth0_authorize_url,
    _callback_url,
    _get_server_url,
    _misconfiguration_response,
    _oauth_error_response,
    _OAuthRequestError,
    _require_oauth_config,
    logger,
)
from utils.oauth._ledger import (
    _ledger_org,
    _ledger_stage_url,
    _ledger_state,
    _strip_ledger_scopes,
)
from utils.oauth._redirect_uris import (
    _is_allowed_redirect_uri,
    _is_pkce_exempt_redirect_uri,
)
from utils.oauth._sealing import (
    _DEVICE_SCOPE_PREFIX,
    _STAGE_LEDGER,
    _STAGE_MFA,
    _build_state,
    _client_device_id,
    _hash_nonce,
    _mint_device_id,
    _mint_nonce,
    _set_nonce_cookie,
    _strip_device_scopes,
)

# RFC 7636 §4.1: a base64url SHA-256 digest. Matched, never normalized, since the
# value checked here is the one forwarded upstream.
_PKCE_CHALLENGE_PATTERN = re.compile(r'^[A-Za-z0-9\-._~]{43,128}\Z')


async def oauth_authorize(request: Request) -> Response:
    """Validate redirect_uri and PKCE, then redirect to Auth0 with the configured
    client_id, a signed state and a nonce cookie; 'mfa' scope runs two stages."""
    try:
        config = _require_oauth_config()
        authorize = _normalize_authorize_request(request, config)
        server_url = _get_server_url(request)
        _validate_authorize_request(authorize)
        _drop_unchecked_challenge_method(authorize.params)
        nonce = _mint_nonce()
        auth0_url = _first_stage_url(config, server_url, authorize, _hash_nonce(nonce))
    except _OAuthRequestError as e:
        return e.response

    response = RedirectResponse(url=auth0_url, status_code=HTTPStatus.FOUND)
    _set_nonce_cookie(response, nonce)
    return response


class _AuthorizeRequest(NamedTuple):
    """The client's authorize request, normalized for Auth0."""

    params: dict[str, str]
    client_redirect_uri: str
    device_id: str
    ledger_org: str
    mfa_requested: bool


def _normalize_authorize_request(
    request: Request, config: dict[str, str]
) -> _AuthorizeRequest:
    """Pin client_id, fill audience and response_type, and leave the scope with
    offline_access, exactly one `device:` token, and no pseudo-scopes."""
    params = dict(request.query_params)
    # Pinned so this endpoint cannot proxy arbitrary Auth0 clients.
    params['client_id'] = config['client_id']
    if 'audience' not in params:
        params['audience'] = config['audience']
    if 'response_type' not in params:
        params['response_type'] = _RESPONSE_TYPE_CODE

    # Without offline_access Auth0 issues no refresh token.
    scope = params.get('scope', '')
    if _OFFLINE_ACCESS_SCOPE not in scope:
        scope = f'{scope} {_OFFLINE_ACCESS_SCOPE}'.strip()
    # The Auth0 action keys MFA presence on the first `device:` token, so exactly one
    # leaves here. The id rides the state so the callback can seal the code under it.
    device_id = _client_device_id(scope)
    if device_id is None:
        device_id = _mint_device_id()
    scope = f'{_strip_device_scopes(scope)} {_DEVICE_SCOPE_PREFIX}{device_id}'.strip()

    ledger_org = _ledger_org(scope)
    scope = _strip_ledger_scopes(scope)

    # The re-auth 403 asks for scope "... mfa"; the pseudo-scope picks the MFA flow.
    scope_parts = scope.split()
    mfa_requested = _MFA_SCOPE in scope_parts
    if mfa_requested:
        scope = ' '.join(s for s in scope_parts if s != _MFA_SCOPE)
        logger.info('MFA scope detected, will use two-stage OAuth flow')

    params['scope'] = scope
    return _AuthorizeRequest(
        params=params,
        client_redirect_uri=params.get('redirect_uri', ''),
        device_id=device_id,
        ledger_org=ledger_org,
        mfa_requested=mfa_requested,
    )


def _validate_authorize_request(authorize: _AuthorizeRequest) -> None:
    """Validate redirect_uri and S256 PKCE; only exempt callbacks may omit
    the challenge."""
    params = authorize.params
    client_redirect_uri = authorize.client_redirect_uri
    _log_authorize_client_profile(
        client_redirect_uri, params.get('code_challenge_method', '')
    )
    if client_redirect_uri and not _is_allowed_redirect_uri(client_redirect_uri):
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REQUEST,
                'redirect_uri must be a loopback URL or an allowlisted '
                'callback endpoint',
            )
        )

    code_challenge = params.get('code_challenge', '')
    code_challenge_method = params.get('code_challenge_method', '')
    if not code_challenge and not _is_pkce_exempt_redirect_uri(client_redirect_uri):
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REQUEST,
                'code_challenge is required; this server accepts only '
                f'{_PKCE_CHALLENGE_METHOD} PKCE',
            )
        )
    if code_challenge and code_challenge_method != _PKCE_CHALLENGE_METHOD:
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REQUEST,
                f'code_challenge_method must be {_PKCE_CHALLENGE_METHOD}',
            )
        )
    if code_challenge and not _PKCE_CHALLENGE_PATTERN.match(code_challenge):
        raise _OAuthRequestError(
            _oauth_error_response(
                _ERROR_INVALID_REQUEST,
                'code_challenge must be 43 to 128 characters from the '
                'RFC 7636 unreserved set',
            )
        )


def _drop_unchecked_challenge_method(params: dict[str, str]) -> None:
    """Without a challenge, the method was never checked; forwarding it would hand
    Auth0 a value this server never stood behind."""
    if not params.get('code_challenge'):
        params.pop('code_challenge_method', None)


def _log_authorize_client_profile(
    redirect_uri: str, code_challenge_method: str
) -> None:
    """Log each client's redirect_uri and PKCE method. Remove once no client uses the
    PKCE-exempt callback and no deployment needs report-only mode."""
    logger.info(
        'authorize observed - redirect_uri: %s, pkce: %s',
        escape_for_log(redirect_uri) or '(none)',
        escape_for_log(code_challenge_method) or 'none',
    )


def _first_stage_url(
    config: dict[str, str],
    server_url: str,
    authorize: _AuthorizeRequest,
    nonce_hash: str,
) -> str:
    """The Auth0 authorize URL the flow starts at: the MFA audience, else the ledger
    audience, else the regular audience in a single stage."""
    params = authorize.params
    original_state = params.get('state', '')
    # The later stages replay the client's PKCE challenge, so the final code
    # exchange succeeds with the client's code_verifier.
    replayed = {key: params[key] for key in _REPLAYED_AUTHORIZE_PARAMS if key in params}

    # _build_state signs with the configured key, so a malformed state secret
    # raises here, on the endpoint an operator reaches before the callback.
    try:
        if authorize.mfa_requested:
            # Once MFA is done, the callback redirects on to the regular audience.
            mfa_params = {
                'response_type': _RESPONSE_TYPE_CODE,
                'client_id': config['client_id'],
                'audience': config['mfa_audience'],
                'redirect_uri': _callback_url(server_url),
                'scope': 'enroll read:authenticators',
            }
            mfa_params['state'] = _build_state(
                authorize.client_redirect_uri,
                original_state,
                stage=_STAGE_MFA,
                original_scope=params['scope'],
                authorize_params=replayed,
                nonce_hash=nonce_hash,
                device_id=authorize.device_id,
                **_ledger_state(authorize.ledger_org),
            )
            auth0_url = _auth0_authorize_url(config, mfa_params)
            logger.info(
                'Stage 1: Redirecting to Auth0 MFA audience for MFA verification'
            )
        elif authorize.ledger_org:
            auth0_url = _ledger_stage_url(
                config,
                server_url,
                _build_state(
                    authorize.client_redirect_uri,
                    original_state,
                    stage=_STAGE_LEDGER,
                    original_scope=params['scope'],
                    authorize_params=replayed,
                    nonce_hash=nonce_hash,
                    device_id=authorize.device_id,
                    ledger_org=authorize.ledger_org,
                ),
                authorize.ledger_org,
                authorize.device_id,
            )
            logger.info('Redirecting to Auth0 for the ledger audience first')
        else:
            params['redirect_uri'] = _callback_url(server_url)
            params['state'] = _build_state(
                authorize.client_redirect_uri,
                original_state,
                nonce_hash=nonce_hash,
                device_id=authorize.device_id,
            )
            auth0_url = _auth0_authorize_url(config, params)
            logger.info('Redirecting to Auth0 authorize endpoint')
    except ValueError as e:
        raise _OAuthRequestError(_misconfiguration_response(e)) from e
    return auth0_url
