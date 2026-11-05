"""The command pre-approval ledger stage of the sign-in flow."""

from http import HTTPStatus

import httpx
from starlette.requests import Request
from starlette.responses import Response

from utils.common import is_remote_ledger_enabled
from utils.error_handler import validate_workspace_format
from utils.ledger_grant import (
    LedgerGrant,
    grant_from_token_response,
    ledger_audience,
    open_grant,
    open_stage,
    seal_grant,
    subject_of,
)
from utils.logger import escape_for_log
from utils.oauth._http import (
    _AUTH0_TIMEOUT_SECONDS,
    _AUTH0_TOKEN_PATH,
    _FORM_HEADERS,
    _GRANT_AUTHORIZATION_CODE,
    _RESPONSE_TYPE_CODE,
    _auth0_authorize_url,
    _callback_url,
    logger,
)
from utils.oauth._sealing import (
    _COOKIE_HEADER_LIMIT,
    _DEVICE_SCOPE_PREFIX,
    _FLOW_COOKIE_ATTRS,
    _LEDGER_NONCE_MARK,
    _MAX_LIVE_FLOWS,
    _NONCE_COOKIE_BYTES,
    _NONCE_COOKIE_PREFIX,
    _STATE_TTL_SECONDS,
    _cookie_header_fits,
    _flow_cookie_name,
    ledger_grant_key,
)

_LEDGER_SCOPE_PREFIX = 'ledger:'

# Holds the encrypted ledger token from the ledger callback to the final one,
# so it never rides a URL to Auth0. Named and set like the nonce cookie.
_LEDGER_COOKIE_PREFIX = '__Host-alpacon_ledger_grant'
# Bounds `; <ledger cookie name>=<sealed>`: two fit beside a full set of nonce cookies.
_LEDGER_COOKIE_BYTES = (
    _COOKIE_HEADER_LIMIT - _MAX_LIVE_FLOWS * _NONCE_COOKIE_BYTES
) // 2


def _ledger_org(scope: str) -> str:
    """The workspace of the newest `ledger:<ws>:<ms>` challenge, or ''. The tag, not
    the position, decides: a client's scope union keeps only the first copy of a scope."""
    if not is_remote_ledger_enabled():
        return ''
    newest: tuple[int, int] = (-1, -1)
    org = ''
    for position, part in enumerate(scope.split()):
        if not part.startswith(_LEDGER_SCOPE_PREFIX):
            continue
        name, _, tag = part.removeprefix(_LEDGER_SCOPE_PREFIX).partition(':')
        if not validate_workspace_format(name) or (
            tag and not (len(tag) <= 20 and tag.isascii() and tag.isdigit())
        ):
            continue
        rank = (int(tag) if tag else 0, position)
        if rank > newest:
            newest, org = rank, name
    return org


def _strip_ledger_scopes(scope: str) -> str:
    """The scope without any `ledger:` token; Auth0 never sees the pseudo-scope."""
    return ' '.join(s for s in scope.split() if not s.startswith(_LEDGER_SCOPE_PREFIX))


def _ledger_state(ledger_org: str) -> dict[str, str]:
    """The state field naming the ledger workspace; absent when none was asked."""
    return {'ledger_org': ledger_org} if ledger_org else {}


def _ledger_stage_url(
    config: dict[str, str],
    server_url: str,
    state: str,
    ledger_org: str,
    device_id: str,
) -> str:
    """Auth0 authorize URL for the ledger audience: this app, no offline_access (the
    ledger allows no refresh), and the CLI's `org:` scope for the org claim."""
    params = {
        'response_type': _RESPONSE_TYPE_CODE,
        'client_id': config['client_id'],
        'audience': ledger_audience(),
        'redirect_uri': _callback_url(server_url),
        # The grant's own device id, so the login action reads and writes the
        # same MFA record as this installation's regular sign-in.
        'scope': f'openid profile email org:{ledger_org} {_DEVICE_SCOPE_PREFIX}{device_id}',
        'state': state,
    }
    return _auth0_authorize_url(config, params)


async def _exchange_ledger_code(
    config: dict[str, str], server_url: str, code: str, ledger_org: str
) -> LedgerGrant | None:
    """Exchange the ledger stage's code; None when Auth0 issued no usable token,
    which does not end the sign-in."""
    try:
        async with httpx.AsyncClient(timeout=_AUTH0_TIMEOUT_SECONDS) as client:
            response = await client.post(
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
    except httpx.HTTPError as e:
        logger.warning('Ledger token exchange failed: %s', e)
        return None
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code != HTTPStatus.OK or not isinstance(body, dict):
        logger.warning(
            'Ledger token exchange returned %s: %s',
            response.status_code,
            escape_for_log(
                body.get('error', 'unknown') if isinstance(body, dict) else 'non-JSON'
            ),
        )
        return None
    grant = grant_from_token_response(body, ledger_org)
    if grant is None:
        logger.warning('Ledger token exchange returned no usable token')
    return grant


def _ledger_cookie_name(nonce_hash: str) -> str:
    return _flow_cookie_name(_LEDGER_COOKIE_PREFIX, nonce_hash)


def _ledger_cookie_reservation(request: Request, ledger_org: str) -> int:
    """Room for every ledger cookie still to come. Authorize holds it, because ledger
    callbacks that run at once each see only the Cookie header they started with."""
    nonce_prefix = f'{_NONCE_COOKIE_PREFIX}_'
    ledger_prefix = f'{_LEDGER_COOKIE_PREFIX}_'
    cookies = request.cookies
    staged = {
        n.removeprefix(ledger_prefix) for n in cookies if n.startswith(ledger_prefix)
    }
    pending = sum(
        name.startswith(nonce_prefix)
        and value.startswith(_LEDGER_NONCE_MARK)
        and name.removeprefix(nonce_prefix) not in staged
        for name, value in cookies.items()
    )
    return _LEDGER_COOKIE_BYTES * (pending + bool(ledger_org))


def _ledger_cookie_fits(request: Request, sealed: str, nonce_hash: str) -> bool:
    added = len(f'; {_ledger_cookie_name(nonce_hash)}={sealed}')
    return added <= _LEDGER_COOKIE_BYTES and _cookie_header_fits(request, added)


def _set_ledger_cookie(response: Response, sealed: str, *, nonce_hash: str) -> None:
    response.set_cookie(
        _ledger_cookie_name(nonce_hash),
        sealed,
        max_age=_STATE_TTL_SECONDS,
        **_FLOW_COOKIE_ATTRS,
    )


def _clear_ledger_cookie(response: Response, nonce_hash: str) -> None:
    response.delete_cookie(_ledger_cookie_name(nonce_hash), **_FLOW_COOKIE_ATTRS)


def _staged_ledger_grant(request: Request, ledger_org: str, nonce_hash: str) -> str:
    """The encrypted grant the ledger stage left for this flow, or ''."""
    if not ledger_org:
        return ''
    key = ledger_grant_key()
    sealed = request.cookies.get(_ledger_cookie_name(nonce_hash))
    grant = open_stage(key, sealed, nonce_hash)
    if grant is None or grant.org != ledger_org:
        return ''
    return seal_grant(key, grant)


def _carried_ledger_grant(
    sealed_ledger: str, access_token: object
) -> LedgerGrant | None:
    """The grant to wrap into this access token; None when unreadable, lapsed, or a
    token issued to another person than this access token's."""
    if not sealed_ledger or not isinstance(access_token, str):
        return None
    key = ledger_grant_key()
    grant = open_grant(key, sealed_ledger)
    if grant is None or not grant.is_live():
        return None
    if not grant.is_failure and grant.subject != subject_of(access_token):
        logger.warning('Dropped a ledger grant issued to another subject')
        return None
    return grant
