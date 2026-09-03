"""Keys, signed state, device ids, sealed grants, and the nonce cookie."""

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Literal, TypedDict

from starlette.requests import Request
from starlette.responses import Response

from utils.logger import get_logger
from utils.oauth._http import _get_oauth_config

logger = get_logger('oauth')


# Explicit state signing key; unset, it is derived from the client secret.
_STATE_SECRET_ENV = 'ALPACON_MCP_STATE_SECRET'


# Domain-separates the state key from other keys derived from the client secret.
_STATE_SECRET_INFO = b'alpacon-mcp-oauth-state-v1'


# Separate from the state key: a state lives ten minutes, a sealed refresh token
# as long as Auth0 allows, so rotating one must not cost the other.
_GRANT_SECRET_ENV = 'ALPACON_MCP_GRANT_SECRET'


_GRANT_SECRET_INFO = b'alpacon-mcp-oauth-grant-v1'


# The 32 bytes a derived key always has, so an explicit key cannot be weaker
# than none.
_SECRET_MIN_BYTES = 32


# Marks every value this server sealed, so a bare Auth0 token, which also
# contains dots, is never taken for a tampered seal.
_SEALED_PREFIX = 'amcp1'


_SEAL_KIND_CODE = 'code'


_SEAL_KIND_REFRESH = 'refresh'


# Covers an Auth0 login plus MFA; keeps a leaked state only briefly usable.
_STATE_TTL_SECONDS = 600


# Stage tags carried through the state in the two-stage MFA flow.
_STAGE_MFA = 'mfa'


_STAGE_REGULAR = 'regular'


# Mirrors the validator in the Auth0 action's code.js: a value accepted here but
# rejected there would silently fall back to fingerprint keying.
_DEVICE_ID_PATTERN = re.compile(r'^[A-Za-z0-9-]{8,64}$')


# The __Host- prefix makes the browser itself require Secure, Path=/ and no
# Domain, so the cookie cannot be planted by a sibling host.
_NONCE_COOKIE_NAME = '__Host-alpacon_oauth_nonce'


class _NonceCookieAttrs(TypedDict):
    path: Literal['/']
    secure: Literal[True]
    httponly: bool
    samesite: Literal['lax', 'strict', 'none']


# Shared by set and delete: a delete without Path addresses a different cookie,
# and one without Secure is rejected outright under a __Host- name, so the
# cookie survives. Lax, not Strict: Strict drops the cookie on the top-level
# return from Auth0.
_NONCE_COOKIE_ATTRS: _NonceCookieAttrs = {
    'path': '/',
    'secure': True,
    'httponly': True,
    'samesite': 'lax',
}


def _explicit_hex_secret(env_name: str) -> bytes | None:
    """The key an operator set, or None when the variable is unset."""
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
    """Derived from AUTH0_CLIENT_SECRET so no extra secret needs provisioning,
    and identical across replicas so a signed value verifies without shared
    storage.
    """
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


def _sign_state(payload: dict) -> str:
    """Serialise a state payload with an expiry and an HMAC signature."""
    body = {**payload, 'exp': int(time.time()) + _STATE_TTL_SECONDS}
    encoded = base64.urlsafe_b64encode(
        json.dumps(body, separators=(',', ':')).encode()
    ).decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(_get_state_secret(), encoded.encode(), hashlib.sha256).digest()
    ).decode()
    return f'{encoded}.{signature}'


def _verify_state(state: str) -> dict | None:
    """Return the state payload, or None when it is forged or expired.

    The signature covers the encoded payload rather than the raw JSON so it can
    be checked before anything is decoded.
    """
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


def _build_state(redirect_uri: str, state: str, **extra) -> str:
    """Pack everything the callback needs to recover into one signed state value."""
    return _sign_state({'redirect_uri': redirect_uri, 'state': state, **extra})


def _is_device_id(value: str) -> bool:
    """Whether the Auth0 action will honor this as a client-supplied device id."""
    return bool(_DEVICE_ID_PATTERN.match(value.strip()))


def _client_device_id(scope: str) -> str | None:
    """The first `device:` token if the Auth0 action would accept it; the action
    reads only the first, so a usable one behind an unusable one does not count.
    """
    first = next((s for s in scope.split() if s.startswith('device:')), None)
    if first is None:
        return None
    candidate = first.removeprefix('device:').strip()
    return candidate if _is_device_id(candidate) else None


def _strip_device_scopes(scope: str) -> str:
    """The scope without any `device:` token, so a client's cannot outrank ours."""
    return ' '.join(s for s in scope.split() if not s.startswith('device:'))


def _mint_device_id() -> str:
    """One id per grant; 32 hex characters clear the Auth0 action's validator."""
    return secrets.token_hex(16)


def _seal(kind: str, value: str, device_id: str) -> str:
    """Bind a value the client echoes back opaquely to its grant's device id.

    Codes and refresh tokens are the only carrier for the id without server-side
    storage; the signature keeps a client from pointing one at another grant's
    record.
    """
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            {'k': kind, 'v': value, 'd': device_id}, separators=(',', ':')
        ).encode()
    ).decode()
    signed = f'{_SEALED_PREFIX}.{encoded}'
    signature = base64.urlsafe_b64encode(
        hmac.new(_get_grant_secret(), signed.encode(), hashlib.sha256).digest()
    ).decode()
    return f'{signed}.{signature}'


def _unseal(kind: str, sealed: object) -> tuple[str, str] | None:
    """(value, device_id), or None unless this server sealed it as `kind`, so a
    code cannot be replayed as a refresh token.
    """
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
    return value, device_id


def _seal_code(code: str, device_id: str) -> str:
    return _seal(_SEAL_KIND_CODE, code, device_id)


def _unseal_code(sealed: object) -> tuple[str, str] | None:
    return _unseal(_SEAL_KIND_CODE, sealed)


def _seal_refresh_token(refresh_token: str, device_id: str) -> str:
    return _seal(_SEAL_KIND_REFRESH, refresh_token, device_id)


def _unseal_refresh_token(sealed: object) -> tuple[str, str] | None:
    return _unseal(_SEAL_KIND_REFRESH, sealed)


def _log_unsealed_rejection(what: str, value: object) -> None:
    """Log a value this server did not seal, before it is rejected.

    One under our prefix that fails to verify is tampering or corruption and
    worth a warning; a bare one is a session from before sealing, which every
    client hits once at rollout, or an Auth0 token handed to the proxy directly.
    """
    if isinstance(value, str) and value.startswith(f'{_SEALED_PREFIX}.'):
        logger.warning('Rejected a %s that failed seal verification', what)
    else:
        logger.info('Rejected an unsealed %s', what)


def _mint_nonce() -> str:
    """Mint the per-flow value that proves a callback reached the same browser."""
    return secrets.token_urlsafe(32)


def _hash_nonce(nonce: str) -> str:
    """State travels through URLs and proxy logs, so it carries only the hash."""
    return base64.urlsafe_b64encode(hashlib.sha256(nonce.encode()).digest()).decode()


def _set_nonce_cookie(response: Response, nonce: str) -> None:
    response.set_cookie(
        _NONCE_COOKIE_NAME, nonce, max_age=_STATE_TTL_SECONDS, **_NONCE_COOKIE_ATTRS
    )


def _nonce_cookie_matches(request: Request, state_data: dict) -> bool:
    """Fail closed: a state with no binding, or a browser with no cookie, is a no."""
    expected = state_data.get('nonce_hash')
    nonce = request.cookies.get(_NONCE_COOKIE_NAME, '')
    if not isinstance(expected, str) or not expected or not nonce:
        return False
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
    return hmac.compare_digest(expected.encode(), _hash_nonce(nonce).encode())


def _clear_nonce_cookie(response: Response) -> None:
    response.delete_cookie(_NONCE_COOKIE_NAME, **_NONCE_COOKIE_ATTRS)
