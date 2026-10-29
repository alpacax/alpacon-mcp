"""A remote caller's ledger token, AES-GCM encrypted into that caller's own credential:
no server-side store, any replica can read it, and no other connection holds it."""

import base64
import binascii
import json
import os
import time
from dataclasses import dataclass
from typing import Self, TypeGuard

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mcp.server.auth.provider import AccessToken

from utils.types import JsonValue

LEDGER_URL_ENV = 'ALPACON_MCP_LEDGER_URL'
LEDGER_AUDIENCE_ENV = 'ALPACON_MCP_LEDGER_AUDIENCE'
DEFAULT_LEDGER_URL = 'https://alpacon.ai'
# An audience is an opaque identifier matched character for character; the
# trailing slash is part of it.
DEFAULT_LEDGER_AUDIENCE = 'https://alpacon.ai/'


def ledger_base_url() -> str:
    """The ledger API host, without a trailing slash."""
    url = os.getenv(LEDGER_URL_ENV, '').strip() or DEFAULT_LEDGER_URL
    return url.rstrip('/')


def ledger_audience() -> str:
    """The ledger audience, verbatim."""
    return os.getenv(LEDGER_AUDIENCE_ENV, '').strip() or DEFAULT_LEDGER_AUDIENCE


# Leads an access token this server wrapped, so the verifier can tell it from a
# bare Auth0 JWT, which never starts with it.
WRAPPED_ACCESS_PREFIX = 'amcpl1.'

PURPOSE_STAGE = b'alpacon-mcp-ledger-stage-v1'
PURPOSE_GRANT = b'alpacon-mcp-ledger-grant-v1'
PURPOSE_ACCESS = b'alpacon-mcp-ledger-access-v1'

# A ledger token closer to its expiry than this is treated as expired, so a
# call does not leave with a token that lapses on the way.
EXPIRY_SKEW_SECONDS = 60

# A ledger sign-in that finished this recently and still left no working token
# is reported as a configuration problem instead of being asked for again: each
# re-auth mints a new bearer, so the middleware's cooldown cannot stop a loop.
RETRY_WINDOW_SECONDS = 600

_NONCE_BYTES = 12


def _is_int(value: JsonValue) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class LedgerGrant:
    """A ledger token for workspace `org`, or, with `token` and `subject` empty, the
    record of a ledger sign-in that returned none; times are epoch seconds."""

    token: str
    org: str
    subject: str
    expires_at: int
    issued_at: int

    @classmethod
    def failed(cls, org: str, now: float | None = None) -> Self:
        """The record of a ledger sign-in for `org` that produced no token."""
        issued_at = int(time.time() if now is None else now)
        return cls('', org, '', issued_at + RETRY_WINDOW_SECONDS, issued_at)

    @property
    def is_failure(self) -> bool:
        return not self.token

    def usable_for(self, org: str, now: float | None = None) -> bool:
        """Whether this grant holds a token that may be presented for `org` now."""
        current = time.time() if now is None else now
        return (
            not self.is_failure
            and self.org == org
            and self.expires_at - EXPIRY_SKEW_SECONDS > current
        )

    def is_live(self, now: float | None = None) -> bool:
        """Whether this grant is still worth carrying into a new access token."""
        current = time.time() if now is None else now
        skew = 0 if self.is_failure else EXPIRY_SKEW_SECONDS
        return self.expires_at - skew > current

    def is_recent(self, now: float | None = None) -> bool:
        """Whether its ledger sign-in finished within `RETRY_WINDOW_SECONDS`."""
        current = time.time() if now is None else now
        return current - self.issued_at < RETRY_WINDOW_SECONDS

    def to_json(self) -> dict[str, JsonValue]:
        return {
            't': self.token,
            'o': self.org,
            's': self.subject,
            'e': self.expires_at,
            'i': self.issued_at,
        }

    @classmethod
    def from_json(cls, value: JsonValue) -> Self | None:
        if not isinstance(value, dict):
            return None
        token, org, subject = value.get('t'), value.get('o'), value.get('s')
        expires_at, issued_at = value.get('e'), value.get('i')
        if not (
            isinstance(token, str)
            and isinstance(subject, str)
            and bool(token) == bool(subject)  # both, or a failure record
            and isinstance(org, str)
            and org
            and _is_int(expires_at)
            and _is_int(issued_at)
        ):
            return None
        return cls(token, org, subject, expires_at, issued_at)


# Where the verifier leaves the grant on the SDK's AccessToken. `claims` is the
# SDK's slot for extra verifier output; it reads only `iss` from it, and nothing
# in it reaches a client.
_LEDGER_CLAIM = 'alpacon_mcp_ledger'


def ledger_claims(grant: LedgerGrant) -> dict[str, JsonValue]:
    """The AccessToken `claims` that carry `grant` to the tool handler."""
    return {_LEDGER_CLAIM: grant.to_json()}


def ledger_grant_of(access: AccessToken | None) -> LedgerGrant | None:
    """The grant the verifier found in this request's credential, if any."""
    if access is None or not access.claims:
        return None
    return LedgerGrant.from_json(access.claims.get(_LEDGER_CLAIM))


def _claims_unverified(token: str) -> dict[str, JsonValue]:
    # Not utils.auth.decode_claims_unverified: utils.auth imports this module.
    try:
        claims = jwt.decode(token, options={'verify_signature': False})
    except jwt.InvalidTokenError:
        return {}
    return claims if isinstance(claims, dict) else {}


def subject_of(token: str) -> str:
    """A JWT's `sub`, unverified, or '' when it has none."""
    subject = _claims_unverified(token).get('sub')
    return subject if isinstance(subject, str) else ''


def grant_from_token_response(
    body: dict[str, JsonValue], org: str, now: float | None = None
) -> LedgerGrant | None:
    """A grant from Auth0's ledger-audience token response, read unverified (it came
    over our own back channel; the ledger verifies it); no `sub` or lifetime, None."""
    token = body.get('access_token')
    if not isinstance(token, str) or not token:
        return None
    claims = _claims_unverified(token)
    subject = claims.get('sub')
    if not isinstance(subject, str) or not subject:
        return None
    issued_at = int(time.time() if now is None else now)
    exp = claims.get('exp')
    if isinstance(exp, int) and not isinstance(exp, bool):
        expires_at = exp
    else:
        expires_in = body.get('expires_in')
        if not isinstance(expires_in, int) or isinstance(expires_in, bool):
            return None
        expires_at = issued_at + expires_in
    return LedgerGrant(token, org, subject, expires_at, issued_at)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def encrypt(key: bytes, purpose: bytes, payload: dict[str, JsonValue]) -> str:
    """Encrypt a JSON object; `purpose` is the associated data it is bound to."""
    nonce = os.urandom(_NONCE_BYTES)
    plaintext = json.dumps(payload, separators=(',', ':')).encode()
    return _b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext, purpose))


def decrypt(key: bytes, purpose: bytes, blob: object) -> dict[str, JsonValue] | None:
    """The JSON object `encrypt` sealed for `purpose`, or None for anything else."""
    if not isinstance(blob, str) or not blob:
        return None
    try:
        raw = _b64decode(blob)
    except (binascii.Error, ValueError):
        return None
    if len(raw) <= _NONCE_BYTES:
        return None
    try:
        plaintext = AESGCM(key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], purpose)
        payload = json.loads(plaintext)
    except (InvalidTag, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def seal_grant(key: bytes, grant: LedgerGrant) -> str:
    """The grant as it rides inside a sealed code or refresh token."""
    return encrypt(key, PURPOSE_GRANT, grant.to_json())


def open_grant(key: bytes, blob: object) -> LedgerGrant | None:
    payload = decrypt(key, PURPOSE_GRANT, blob)
    return LedgerGrant.from_json(payload) if payload is not None else None


def seal_stage(key: bytes, grant: LedgerGrant, nonce_hash: str) -> str:
    """The grant between the ledger callback and the final one, bound to a browser."""
    return encrypt(key, PURPOSE_STAGE, {'g': grant.to_json(), 'n': nonce_hash})


def open_stage(key: bytes, blob: object, nonce_hash: str) -> LedgerGrant | None:
    """The staged grant, only for the browser whose nonce hash sealed it."""
    payload = decrypt(key, PURPOSE_STAGE, blob)
    if payload is None or not nonce_hash or payload.get('n') != nonce_hash:
        return None
    return LedgerGrant.from_json(payload.get('g'))


def is_wrapped_access_token(token: str) -> bool:
    return token.startswith(WRAPPED_ACCESS_PREFIX)


def wrap_access_token(key: bytes, access_token: str, grant: LedgerGrant) -> str:
    """The access token a client holds: the Auth0 one plus its ledger grant."""
    blob = encrypt(key, PURPOSE_ACCESS, {'a': access_token, 'g': grant.to_json()})
    return f'{WRAPPED_ACCESS_PREFIX}{blob}'


def unwrap_access_token(key: bytes, token: str) -> tuple[str, LedgerGrant] | None:
    """(Auth0 access token, ledger grant), or None unless this server wrapped it."""
    if not is_wrapped_access_token(token):
        return None
    payload = decrypt(key, PURPOSE_ACCESS, token.removeprefix(WRAPPED_ACCESS_PREFIX))
    if payload is None:
        return None
    inner = payload.get('a')
    grant = LedgerGrant.from_json(payload.get('g'))
    if not isinstance(inner, str) or not inner or grant is None:
        return None
    return inner, grant
