"""Secrets, signed state, the nonce cookie, device ids and sealed grants."""

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Literal, NamedTuple, NoReturn, TypedDict

from starlette.requests import Request
from starlette.responses import Response

from utils.device_id import DEVICE_ID_PATTERN
from utils.oauth._http import (
    _get_oauth_config,
    _invalid_grant_response,
    _OAuthRequestError,
    logger,
)

_DEVICE_SCOPE_PREFIX = 'device:'

# Explicit state signing key; when unset, the key is derived from the client secret.
_STATE_SECRET_ENV = 'ALPACON_MCP_STATE_SECRET'
# Domain-separates the state key from other keys derived from the client secret.
_STATE_SECRET_INFO = b'alpacon-mcp-oauth-state-v1'

# Kept apart from the state key: a state lives ten minutes, a sealed refresh token
# up to its Auth0 lifetime, so rotating one must not cost the other.
_GRANT_SECRET_ENV = 'ALPACON_MCP_GRANT_SECRET'
_GRANT_SECRET_INFO = b'alpacon-mcp-oauth-grant-v1'

# Domain-separates the ledger grant key from the grant seal's HMAC key.
_LEDGER_KEY_INFO = b'alpacon-mcp-ledger-key-v1'
_REQUEST_STATE_KEY_INFO = b'alpacon-mcp-request-state-v1'

# The 32 bytes a derived key always has, so an explicit key cannot be weaker than
# leaving the variable unset.
_SECRET_MIN_BYTES = 32

# Covers an Auth0 login plus MFA; keeps a leaked state only briefly usable.
_STATE_TTL_SECONDS = 600

# Stage tags carried through the state in the multi-stage flows.
_STAGE_MFA = 'mfa'
_STAGE_REGULAR = 'regular'
# The command pre-approval ledger stage: a sign-in for the ledger audience, run
# before the regular one when the client asks for `ledger:<workspace>`.
_STAGE_LEDGER = 'ledger'

# Leads every value this server sealed, so a bare Auth0 token, which also
# contains dots, is never mistaken for a tampered seal.
_SEALED_PREFIX = 'amcp1'
_SEAL_KIND_CODE = 'code'
_SEAL_KIND_REFRESH = 'refresh'

# Mirrors the validator in the Auth0 action's code.js, another repo: a value accepted
# here but rejected there silently falls back to the fingerprint keying.
_DEVICE_ID_PATTERN = DEVICE_ID_PATTERN

# The __Host- prefix makes the browser itself require Secure, Path=/ and no
# Domain, so the cookie cannot be planted by a sibling host.
_NONCE_COOKIE_PREFIX = '__Host-alpacon_oauth_nonce'

# Long enough that two flows in one browser never share a cookie name.
_FLOW_SUFFIX_CHARS = 16

_MAX_LIVE_FLOWS = 8
# Under nginx's default 8 KB header line, so a callback still reaches this server.
_COOKIE_HEADER_LIMIT = 8000
# One nonce cookie plus a ledger cookie at the browser's 4 KB cookie cap.
_NEW_FLOW_COOKIE_BYTES = 4200


class _FlowCookieAttrs(TypedDict):
    path: Literal['/']
    secure: Literal[True]
    httponly: bool
    samesite: Literal['lax', 'strict', 'none']


# Shared by set and delete: a delete without Path or Secure misses a __Host- cookie,
# which then survives. Lax, since Strict drops it on the top-level return from Auth0.
_FLOW_COOKIE_ATTRS: _FlowCookieAttrs = {
    'path': '/',
    'secure': True,
    'httponly': True,
    'samesite': 'lax',
}


def _explicit_hex_secret(env_name: str) -> bytes | None:
    """The key an operator set, or None when unset; raises ValueError unless it is
    hex of at least 32 bytes."""
    explicit = os.getenv(env_name, '')
    if not explicit:
        return None
    # Signed values travel in URLs and proxy logs, so the key is an offline
    # brute-force target; hex-only input keeps a typed passphrase out.
    try:
        key = bytes.fromhex(explicit)
    except ValueError:
        raise ValueError(
            f'{env_name} must be hex; '
            f'generate one with openssl rand -hex {_SECRET_MIN_BYTES}'
        ) from None
    if len(key) < _SECRET_MIN_BYTES:
        raise ValueError(
            f'{env_name} must decode to at least {_SECRET_MIN_BYTES} bytes'
        )
    return key


def _derived_secret(info: bytes) -> bytes:
    """Key derived from AUTH0_ALPACON_LOGIN_CLIENT_SECRET: nothing to provision, and
    identical across replicas so a signed value verifies without shared storage."""
    client_secret = _get_oauth_config()['client_secret']
    return hmac.new(client_secret.encode(), info, hashlib.sha256).digest()


def _get_state_secret() -> bytes:
    return _explicit_hex_secret(_STATE_SECRET_ENV) or _derived_secret(
        _STATE_SECRET_INFO
    )


def _get_grant_secret() -> bytes:
    return _explicit_hex_secret(_GRANT_SECRET_ENV) or _derived_secret(
        _GRANT_SECRET_INFO
    )


def ledger_grant_key() -> bytes:
    """AES-256 key for ledger grants, derived from the grant secret so every replica
    reads what another wrapped; rotating that secret drops every ledger grant."""
    return hmac.new(_get_grant_secret(), _LEDGER_KEY_INFO, hashlib.sha256).digest()


def request_state_key() -> bytes:
    """Key for a tools/call requestState, derived from the grant secret so a retry may land
    on any replica; without one, a random key that only this process opens."""
    try:
        secret = _get_grant_secret()
    except ValueError as e:
        logger.warning(
            'requestState sealed per process (%s): a retry must reach this replica', e
        )
        return secrets.token_bytes(32)
    return hmac.new(secret, _REQUEST_STATE_KEY_INFO, hashlib.sha256).digest()


def _sign_state(payload: dict[str, object]) -> str:
    """Serialize a state payload with an expiry and an HMAC signature."""
    body = {**payload, 'exp': int(time.time()) + _STATE_TTL_SECONDS}
    encoded = base64.urlsafe_b64encode(
        json.dumps(body, separators=(',', ':')).encode()
    ).decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(_get_state_secret(), encoded.encode(), hashlib.sha256).digest()
    ).decode()
    return f'{encoded}.{signature}'


def _verify_state(state: str) -> dict[str, object] | None:
    """Return the state payload, or None when it is forged or expired; raises
    ValueError when no state key can be resolved."""
    encoded, _, signature = state.rpartition('.')
    if not encoded or not signature:
        return None

    expected = base64.urlsafe_b64encode(
        hmac.new(_get_state_secret(), encoded.encode(), hashlib.sha256).digest()
    )
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
    if not hmac.compare_digest(expected, signature.encode()):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode()).decode())
    except (json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        return None

    if not isinstance(payload, dict):
        return None

    expires_at = payload.get('exp')
    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        return None

    return payload


def _build_state(redirect_uri: str, state: str, **extra: object) -> str:
    """Pack everything the callback needs to recover into one signed state value."""
    return _sign_state({'redirect_uri': redirect_uri, 'state': state, **extra})


def _state_str(state_data: dict[str, object], key: str) -> str:
    """A string field of a verified state; any other type reads as absent."""
    value = state_data.get(key)
    return value if isinstance(value, str) else ''


def _mint_nonce() -> str:
    """Mint the per-flow value that proves a callback reached the same browser."""
    return secrets.token_urlsafe(32)


def _hash_nonce(nonce: str) -> str:
    """State travels through URLs and proxy logs, so it carries only the hash."""
    return base64.urlsafe_b64encode(hashlib.sha256(nonce.encode()).digest()).decode()


def _flow_cookie_name(prefix: str, nonce_hash: str) -> str:
    """A per-flow name, so a second authorize in the same browser leaves the first
    flow's cookies alone; the signed state's nonce_hash names the flow."""
    digest = hashlib.sha256(nonce_hash.encode()).hexdigest()
    return f'{prefix}_{digest[:_FLOW_SUFFIX_CHARS]}'


def _nonce_cookie_name(nonce_hash: str) -> str:
    return _flow_cookie_name(_NONCE_COOKIE_PREFIX, nonce_hash)


def _set_nonce_cookie(response: Response, nonce: str) -> None:
    response.set_cookie(
        _nonce_cookie_name(_hash_nonce(nonce)),
        nonce,
        max_age=_STATE_TTL_SECONDS,
        **_FLOW_COOKIE_ATTRS,
    )


def _refresh_nonce_cookie(
    request: Request, response: Response, nonce_hash: str
) -> None:
    """Re-set the cookie so its expiry tracks the next stage's fresh state."""
    # Only past _nonce_cookie_matches, which saw this cookie non-empty.
    _set_nonce_cookie(response, request.cookies[_nonce_cookie_name(nonce_hash)])


def _clear_nonce_cookie(response: Response, nonce_hash: str) -> None:
    response.delete_cookie(_nonce_cookie_name(nonce_hash), **_FLOW_COOKIE_ATTRS)


def _cookie_header_fits(request: Request, added_bytes: int) -> bool:
    size = len(request.headers.get('cookie', ''))
    return size + added_bytes <= _COOKIE_HEADER_LIMIT


def _has_room_for_a_flow(request: Request) -> bool:
    """Live flows keep their cookies, so a full browser is refused a new flow until
    one finishes or expires."""
    prefix = f'{_NONCE_COOKIE_PREFIX}_'
    live = sum(name.startswith(prefix) for name in request.cookies)
    return live < _MAX_LIVE_FLOWS and _cookie_header_fits(
        request, _NEW_FLOW_COOKIE_BYTES
    )


def _nonce_cookie_matches(request: Request, state_data: dict[str, object]) -> bool:
    """Fail closed: a state with no binding, or a browser with no cookie, is a no."""
    expected = _state_str(state_data, 'nonce_hash')
    if not expected:
        return False
    nonce = request.cookies.get(_nonce_cookie_name(expected), '')
    if not nonce:
        return False
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
    return hmac.compare_digest(expected.encode(), _hash_nonce(nonce).encode())


def _is_device_id(value: str) -> bool:
    """Whether the Auth0 action will honor this as a client-supplied device id."""
    return bool(_DEVICE_ID_PATTERN.match(value.strip()))


def _client_device_id(scope: str) -> str | None:
    """The first `device:` token if the Auth0 action would accept it; the action
    reads only the first, so a usable one behind an unusable one does not count."""
    first = next((s for s in scope.split() if s.startswith(_DEVICE_SCOPE_PREFIX)), None)
    if first is None:
        return None
    candidate = first.removeprefix(_DEVICE_SCOPE_PREFIX).strip()
    return candidate if _is_device_id(candidate) else None


def _strip_device_scopes(scope: str) -> str:
    """The scope without any `device:` token, so one the client sent cannot outrank
    the device id this server adds."""
    return ' '.join(s for s in scope.split() if not s.startswith(_DEVICE_SCOPE_PREFIX))


def _mint_device_id() -> str:
    """One id per grant; 32 hex characters clear the Auth0 action's validator."""
    return secrets.token_hex(16)


def _seal(kind: str, value: str, device_id: str, ledger: str = '') -> str:
    """Bind an opaque value the client echoes back to its grant's device id, with an
    encrypted ledger grant riding along if any; the signature pins both."""
    payload: dict[str, str] = {'k': kind, 'v': value, 'd': device_id}
    if ledger:
        payload['l'] = ledger
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode()
    ).decode()
    signed = f'{_SEALED_PREFIX}.{encoded}'
    signature = base64.urlsafe_b64encode(
        hmac.new(_get_grant_secret(), signed.encode(), hashlib.sha256).digest()
    ).decode()
    return f'{signed}.{signature}'


class _OpenedSeal(NamedTuple):
    """The Auth0 value a seal carried, its grant's device id, and the encrypted ledger
    grant riding along, or ''."""

    value: str
    device_id: str
    ledger: str


def _open_seal(kind: str, sealed: object) -> _OpenedSeal | None:
    """None unless this server sealed it as `kind`, so a code cannot be replayed as a
    refresh token."""
    prefix = f'{_SEALED_PREFIX}.'
    if not isinstance(sealed, str) or not sealed.startswith(prefix):
        return None
    signed, _, signature = sealed.rpartition('.')
    expected = base64.urlsafe_b64encode(
        hmac.new(_get_grant_secret(), signed.encode(), hashlib.sha256).digest()
    )
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
    if not hmac.compare_digest(expected, signature.encode()):
        return None
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(signed.removeprefix(prefix).encode()).decode()
        )
    except (json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        return None
    if not isinstance(payload, dict) or payload.get('k') != kind:
        return None
    value = payload.get('v')
    device_id = payload.get('d')
    if not isinstance(value, str) or not value:
        return None
    if not isinstance(device_id, str) or not _is_device_id(device_id):
        return None
    ledger = payload.get('l', '')
    return _OpenedSeal(value, device_id, ledger if isinstance(ledger, str) else '')


def _seal_code(code: str, device_id: str, ledger: str = '') -> str:
    return _seal(_SEAL_KIND_CODE, code, device_id, ledger)


def _seal_refresh_token(refresh_token: str, device_id: str, ledger: str = '') -> str:
    return _seal(_SEAL_KIND_REFRESH, refresh_token, device_id, ledger)


def _reject_unsealed(what: str, value: object) -> NoReturn:
    """Log and refuse a value this server did not seal: a warning when it bears our
    prefix but fails verification, an info line for a pre-sealing or bare token."""
    if isinstance(value, str) and value.startswith(f'{_SEALED_PREFIX}.'):
        logger.warning('Rejected a %s that failed seal verification', what)
    else:
        logger.info('Rejected an unsealed %s', what)
    raise _OAuthRequestError(_invalid_grant_response(what))
