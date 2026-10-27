"""User authorization for the command pre-approval ledger.

The ledger is served by a separate resource server whose audience is not the
one Alpacon API tokens or remote-mode logins are minted for, and it accepts
only a person's token. So this module runs its own OAuth 2.0 device
authorization (RFC 8628) against the workspace's Auth0 tenant, for the ledger
audience only, and keeps the result in memory:

- No refresh token is requested. The ledger is an admin surface, and a
  long-lived refresh credential for it would be a standing privilege; when the
  access token expires, the person authorizes again.
- Nothing is written to disk. A restarted MCP process asks again.
- The flow never blocks a tool call. The first call starts it and returns the
  verification link for a person to open; a later call polls once and, when
  the person has approved, proceeds with the token.

Only a stdio server uses this. The cache is process-global and keyed by
workspace, not by caller, which is safe only where the process serves one
person; SSE and streamable-http may serve several from one process. Remote
mode carries its ledger token in each caller's credential instead (see
`utils.ledger_grant`).
"""

import asyncio
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import TypeGuard

import httpx

from utils.auth import decode_claims_unverified
from utils.common import error_response
from utils.ledger_grant import (
    DEFAULT_LEDGER_AUDIENCE,
    DEFAULT_LEDGER_URL,
    LEDGER_AUDIENCE_ENV,
    LEDGER_URL_ENV,
    ledger_audience,
    ledger_base_url,
)
from utils.logger import get_logger
from utils.types import JsonValue, ToolResponse

logger = get_logger('ledger_auth')

# The ledger host and audience moved to utils.ledger_grant, which the OAuth
# proxy imports without this module's dependencies; they stay importable here.
__all__ = [
    'AUTHORIZATION_REQUIRED',
    'DEFAULT_LEDGER_AUDIENCE',
    'DEFAULT_LEDGER_URL',
    'LEDGER_AUDIENCE_ENV',
    'LEDGER_URL_ENV',
    'LedgerAuthorizer',
    'LedgerTarget',
    'ledger_audience',
    'ledger_authorizer',
    'ledger_base_url',
]

AUTHORIZATION_REQUIRED = 'authorization_required'

_DEVICE_CODE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'
# RFC 8628 section 3.5: the default interval and the slow_down increment.
_DEFAULT_INTERVAL = 5
# Treat a token as expired this many seconds early, so a call does not leave
# with a token that lapses on the way.
_EXPIRY_SKEW = 60
_AUTH0_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _now() -> float:
    return time.monotonic()


@dataclass(frozen=True)
class LedgerTarget:
    """The Auth0 tenant and organization a ledger token is minted for.

    `org_name` is the workspace's schema name, which is its Auth0 organization
    name; the device flow names it as an `org:<name>` scope so the login action
    stamps the organization claim the ledger reads.
    """

    domain: str
    client_id: str
    org_name: str
    workspace_id: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.domain, self.client_id, self.org_name, ledger_audience())


@dataclass
class _PendingAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_at: float
    interval: int
    next_poll_at: float


@dataclass(frozen=True)
class _CachedToken:
    token: str
    expires_at: float


type _Auth0Body = dict[str, JsonValue]


def _is_number(value: JsonValue) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)  # bool is int


def _positive_int(value: JsonValue, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


async def _post_form(url: str, data: dict[str, str]) -> tuple[int, _Auth0Body]:
    """POST a form to Auth0 and return the status and the JSON object body."""
    async with httpx.AsyncClient(timeout=_AUTH0_TIMEOUT) as client:
        response = await client.post(
            url,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body if isinstance(body, dict) else {}


def _token_lifetime(body: _Auth0Body) -> float:
    """Seconds the issued token stays usable, from `expires_in` or its `exp`."""
    expires_in = body.get('expires_in')
    if _is_number(expires_in) and expires_in > 0:
        return float(expires_in)
    token = body.get('access_token')
    claims = (decode_claims_unverified(token) if isinstance(token, str) else None) or {}
    exp = claims.get('exp')
    if _is_number(exp):
        return float(exp) - time.time()
    return 0.0


class LedgerAuthorizer:
    """Device authorizations and their tokens, one per `LedgerTarget`."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str, str, str], _CachedToken] = {}
        self._pending: dict[tuple[str, str, str, str], _PendingAuthorization] = {}
        self._lock = asyncio.Lock()

    def has_token(self, target: LedgerTarget) -> bool:
        """Whether an unexpired token is cached, so the next call reuses it."""
        cached = self._tokens.get(target.key)
        return cached is not None and cached.expires_at > _now()

    def forget(self, target: LedgerTarget) -> None:
        """Drop the cached token, e.g. after the ledger answered 401."""
        self._tokens.pop(target.key, None)

    def clear(self) -> None:
        """Drop every token and pending authorization."""
        self._tokens.clear()
        self._pending.clear()

    async def token_for(self, target: LedgerTarget) -> str | ToolResponse:
        """Return a ledger token, or the response telling a person to authorize.

        Returns:
            The access token string, or a response dict: `authorization_required`
            with the verification link, or an error.
        """
        async with self._lock:
            key = target.key
            cached = self._tokens.get(key)
            if cached is not None and cached.expires_at > _now():
                return cached.token
            self._tokens.pop(key, None)

            pending = self._pending.get(key)
            if pending is not None and pending.expires_at <= _now():
                self._pending.pop(key, None)
                pending = None

            if pending is not None:
                if _now() < pending.next_poll_at:
                    return _authorization_required(pending)
                outcome = await self._poll(target, pending)
                return (
                    outcome if outcome is not None else _authorization_required(pending)
                )

            return await self._start(target)

    async def _start(self, target: LedgerTarget) -> ToolResponse:
        data = {
            'client_id': target.client_id,
            'audience': ledger_audience(),
            # No offline_access: a refresh credential for an admin surface
            # would be a standing privilege.
            'scope': f'openid profile email org:{target.org_name}',
        }
        try:
            status, body = await _post_form(
                f'https://{target.domain}/oauth/device/code', data
            )
        except httpx.HTTPError as e:
            logger.error('Device authorization request failed: %s', e)
            return error_response(
                'Could not reach the sign-in service to authorize the command '
                'pre-approval ledger. Retry later.'
            )

        if status != HTTPStatus.OK or not body.get('device_code'):
            logger.warning(
                'Device authorization refused - status: %s, error: %s',
                status,
                body.get('error', 'unknown'),
            )
            return error_response(
                'The sign-in service refused to start an authorization for the '
                'command pre-approval ledger.',
                status_code=status,
                error_code=body.get('error'),
                detail=body.get('error_description'),
            )

        now = _now()
        interval = _positive_int(body.get('interval'), _DEFAULT_INTERVAL)
        expires_in = _positive_int(body.get('expires_in'), 900)
        verification_uri = str(body.get('verification_uri', ''))
        pending = _PendingAuthorization(
            device_code=str(body['device_code']),
            user_code=str(body.get('user_code', '')),
            verification_uri=verification_uri,
            verification_uri_complete=str(
                body.get('verification_uri_complete') or verification_uri
            ),
            expires_at=now + expires_in,
            interval=interval,
            next_poll_at=now + interval,
        )
        self._pending[target.key] = pending
        return _authorization_required(pending)

    async def _poll(
        self, target: LedgerTarget, pending: _PendingAuthorization
    ) -> str | ToolResponse | None:
        """Poll once. A token or a terminal answer is returned; None keeps waiting."""
        key = target.key
        data = {
            'grant_type': _DEVICE_CODE_GRANT,
            'device_code': pending.device_code,
            'client_id': target.client_id,
        }
        try:
            status, body = await _post_form(
                f'https://{target.domain}/oauth/token', data
            )
        except httpx.HTTPError as e:
            logger.warning('Device token poll failed: %s', e)
            pending.next_poll_at = _now() + pending.interval
            return None

        token = body.get('access_token')
        if status == HTTPStatus.OK and isinstance(token, str) and token:
            self._pending.pop(key, None)
            lifetime = _token_lifetime(body) - _EXPIRY_SKEW
            if lifetime > 0:
                self._tokens[key] = _CachedToken(token, _now() + lifetime)
            return token

        error = body.get('error')
        if error == 'authorization_pending':
            pending.next_poll_at = _now() + pending.interval
            return None
        if error == 'slow_down':
            pending.interval += _DEFAULT_INTERVAL
            pending.next_poll_at = _now() + pending.interval
            return None

        self._pending.pop(key, None)
        if error == 'expired_token':
            # Start over below with a fresh link.
            return await self._start(target)
        logger.warning(
            'Device authorization ended - status: %s, error: %s', status, error
        )
        return error_response(
            'Authorization for the command pre-approval ledger was not granted. '
            'Call the tool again to get a new link.',
            status_code=status,
            error_code=error,
            detail=body.get('error_description'),
        )


def _authorization_required(pending: _PendingAuthorization) -> ToolResponse:
    remaining = max(0, int(pending.expires_at - _now()))
    return {
        'status': AUTHORIZATION_REQUIRED,
        'message': (
            'The command pre-approval ledger needs a separate sign-in by a '
            'person. Show this link to the user, ask them to open it, confirm '
            'the code and sign in, then call the same tool again. The agent '
            'cannot complete this step itself.'
        ),
        'verification_uri_complete': pending.verification_uri_complete,
        'verification_uri': pending.verification_uri,
        'user_code': pending.user_code,
        'expires_in': remaining,
        'requires_human_action': True,
    }


ledger_authorizer = LedgerAuthorizer()
