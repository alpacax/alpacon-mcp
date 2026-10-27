"""A remote caller's command pre-approval ledger token, carried in its own credential.

The ledger accepts only a person's token for its own audience and issues no
refresh token, so a remote session needs a second authorization for it. Where
that token lives decides who can use it. A process-wide cache would be shared
by everyone the process serves, and a streamable-http deployment is stateless
and may run several replicas, so a per-process store would not even find it.

So the token is never stored here. The OAuth proxy obtains it during the
caller's own sign-in and encrypts it into the access token it hands that one
client. Every request carries it back, and every replica can decrypt it,
because the key is derived from the grant secret the replicas already share.
No other connection holds that credential, so no other connection can use it,
and the token verifier drops a ledger token whose subject is not the session's.

Three envelopes share one AES-GCM key and are kept apart by their associated
data, so none can be replayed as another:

- `stage`: the token between the two Auth0 callbacks of one sign-in, in a
  cookie, bound to that browser's nonce.
- `grant`: the token inside a sealed authorization code or refresh token.
- `access`: the access token a client presents, wrapping the Auth0 one.
"""

import base64
import binascii
import json
import os
import time
from dataclasses import dataclass
from typing import Self

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

_NONCE_BYTES = 12


@dataclass(frozen=True)
class LedgerGrant:
    """A ledger access token and what it was issued for.

    `org` is the workspace schema name the token's organization was requested
    for; `subject` is the token's own `sub`; `expires_at` is epoch seconds.
    """

    token: str
    org: str
    subject: str
    expires_at: int

    def usable_for(self, org: str, now: float | None = None) -> bool:
        """Whether this grant may be presented for `org` right now."""
        current = time.time() if now is None else now
        return self.org == org and self.expires_at - EXPIRY_SKEW_SECONDS > current

    def to_json(self) -> dict[str, JsonValue]:
        return {
            't': self.token,
            'o': self.org,
            's': self.subject,
            'e': self.expires_at,
        }

    @classmethod
    def from_json(cls, value: JsonValue) -> Self | None:
        if not isinstance(value, dict):
            return None
        token, org, subject, expires_at = (
            value.get('t'),
            value.get('o'),
            value.get('s'),
            value.get('e'),
        )
        if not (
            isinstance(token, str)
            and token
            and isinstance(org, str)
            and org
            and isinstance(subject, str)
            and subject
            and isinstance(expires_at, int)
            and not isinstance(expires_at, bool)
        ):
            return None
        return cls(token=token, org=org, subject=subject, expires_at=expires_at)


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
    """Build a grant from an Auth0 token response for the ledger audience.

    The body came straight from Auth0 over the server's own back channel, so its
    claims are read without verifying the signature; the ledger verifies the
    token itself on every call. A token without a subject or a lifetime is
    refused rather than guessed.
    """
    token = body.get('access_token')
    if not isinstance(token, str) or not token:
        return None
    claims = _claims_unverified(token)
    subject = claims.get('sub')
    if not isinstance(subject, str) or not subject:
        return None
    exp = claims.get('exp')
    if isinstance(exp, int) and not isinstance(exp, bool):
        expires_at = exp
    else:
        expires_in = body.get('expires_in')
        if not isinstance(expires_in, int) or isinstance(expires_in, bool):
            return None
        expires_at = int(time.time() if now is None else now) + expires_in
    return LedgerGrant(token=token, org=org, subject=subject, expires_at=expires_at)


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
