"""Step-up links for actions refused for MFA, and the flow that answers them.
A link credits a browser MFA to the client that asked, so a retry waits for it."""

import asyncio
import enum
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, NoReturn

import httpx

from utils import request_signal
from utils.auth import decode_claims_unverified
from utils.common import MCP_USER_AGENT, JsonValue, is_auth_enabled
from utils.declared_agent import declared_agent_headers
from utils.error_handler import ACTION_MFA_CODE, UpstreamAuthError
from utils.logger import get_logger
from utils.request_workspace import current_workspace, minted_in_call

logger = get_logger('step_up')

STEP_UP_LINK_TTL = 600.0  # The server's step-up ticket lives this long.
STEP_UP_WAIT_SECONDS = 60.0  # The alpacon CLI waits as long for a step-up.
STEP_UP_POLL_INTERVAL = 2.0
_MAX_LINKS = 1024
_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

ERR_MFA_REQUIRED = 'MFA Required'
_MFA_ALREADY_DONE_DETAIL = 'MFA is already done.'
_MSG_MFA_LINK = (
    'MFA is required for this action. Open this link in a browser, complete MFA, '
    'then call this tool again with the same arguments: {url}'
)
_MSG_MFA_JUST_DONE = (
    'MFA was just completed. Call this tool again with the same arguments.'
)

StepUpKey = tuple[str, str, str]
RawGet = Callable[..., Awaitable[httpx.Response]]


class ActionMfaRequired(Exception):  # noqa: N818 - a signal for request(), not an error
    """A JWT request refused for action MFA; request() answers it with a link."""

    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.source = source


class LinkKind(enum.Enum):
    ISSUED = enum.auto()
    ALREADY_DONE = enum.auto()
    UNAVAILABLE = enum.auto()


@dataclass(frozen=True)
class LinkOutcome:
    kind: LinkKind
    url: str | None = None


def mfa_error(message: str, mfa_url: str | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {
        'error': ERR_MFA_REQUIRED,
        'status_code': HTTPStatus.UNAUTHORIZED,
        'message': message,
        'mfa_required': True,
    }
    if mfa_url is not None:
        error['mfa_url'] = mfa_url
    return error


def link_error(mfa_url: str) -> dict[str, Any]:
    return mfa_error(_MSG_MFA_LINK.format(url=mfa_url), mfa_url)


def signal_reauth(source: str, *, mfa_required: bool, code: str) -> NoReturn:
    """Record the re-auth signal the ASGI middleware reads, and cut the call short."""
    request_signal.signal_upstream_auth_error(
        {'mfa_required': mfa_required, 'source': source, 'code': code}
    )
    raise UpstreamAuthError(mfa_required=mfa_required, source=source)


def origin_of(url: str) -> str:
    parsed = httpx.URL(url)
    return f'{parsed.scheme}://{parsed.netloc.decode()}'


def _client_instance_claim() -> str:
    namespace = os.getenv('AUTH0_NAMESPACE', 'https://alpacon.io/').rstrip('/') + '/'
    return f'{namespace}client_instance'


def step_up_key(token: str, origin: str) -> StepUpKey | None:
    """The (sub, client instance, origin) a link is for; None without an instance.
    Without one no step-up ticket is issued, so a link cannot unlock the action."""
    claims = decode_claims_unverified(token)
    if not claims:
        return None
    sub = claims.get('sub')
    instance = claims.get(_client_instance_claim())
    if not isinstance(sub, str) or not sub:
        return None
    if not isinstance(instance, str) or not instance:
        return None
    return (sub, instance, origin)


class StepUpLinks:
    def __init__(
        self,
        ttl: float = STEP_UP_LINK_TTL,
        max_entries: int = _MAX_LINKS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock
        self._links: dict[StepUpKey, tuple[str, float]] = {}

    def get(self, key: StepUpKey) -> str | None:
        entry = self._links.get(key)
        if entry is None:
            return None
        url, stored_at = entry
        if self._clock() - stored_at >= self._ttl:
            del self._links[key]
            return None
        return url

    def remember(self, key: StepUpKey, url: str) -> None:
        now = self._clock()
        self._prune(now)
        if key not in self._links and len(self._links) >= self._max_entries:
            oldest = min(self._links, key=lambda k: self._links[k][1])
            del self._links[oldest]
        self._links[key] = (url, now)

    def forget(self, key: StepUpKey) -> None:
        self._links.pop(key, None)

    def _prune(self, now: float) -> None:
        expired = [k for k, (_, t) in self._links.items() if now - t >= self._ttl]
        for key in expired:
            del self._links[key]


step_up_links = StepUpLinks()


class StepUp:
    def __init__(
        self,
        links: StepUpLinks = step_up_links,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        run_within: Callable[[Awaitable[bool], float], Awaitable[bool]] = (
            asyncio.wait_for
        ),
    ) -> None:
        self.links = links
        self._sleep = sleep
        self._monotonic = monotonic
        self._run_within = run_within

    async def answer(
        self,
        url: str,
        token: str,
        source: str,
        resend: Callable[[], Awaitable[JsonValue]],
        get: RawGet,
    ) -> JsonValue:
        """First refusal returns a fresh link; with one remembered, wait, then resend.
        The API stopped the request at the MFA gate, so the resend runs it once."""
        if not current_workspace():
            logger.warning('Step-up skipped: no workspace bound for this call')
            return self._fall_back_to_reauth(source)
        origin = origin_of(url)
        key = step_up_key(token, origin)
        if key is None:
            logger.warning('Step-up skipped: the token has no client instance')
            return self._fall_back_to_reauth(source)
        remembered = self.links.get(key)
        if remembered is None:
            return await self._issue_link(origin, token, key, source, get)
        if key in (minted_in_call() or ()):
            return link_error(remembered)

        if not await self._wait_for_mfa(origin, token, get):
            return link_error(remembered)

        try:
            result = await resend()
        except ActionMfaRequired:
            return link_error(remembered)
        self.links.forget(key)
        return result

    async def _issue_link(
        self, origin: str, token: str, key: StepUpKey, source: str, get: RawGet
    ) -> JsonValue:
        outcome = await self._fetch_link(origin, token, get)
        if outcome.kind is LinkKind.ALREADY_DONE:
            return mfa_error(_MSG_MFA_JUST_DONE)
        if outcome.url is None:
            return self._fall_back_to_reauth(source)
        self.links.remember(key, outcome.url)
        minted = minted_in_call()
        if minted is not None:
            minted.add(key)
        return link_error(outcome.url)

    @staticmethod
    def _fall_back_to_reauth(source: str) -> JsonValue:
        """No link to give: a 403 challenge in remote mode, else the plain MFA error."""
        if is_auth_enabled():
            signal_reauth(source, mfa_required=True, code=ACTION_MFA_CODE)
        return mfa_error('MFA verification required')

    async def _fetch_link(self, origin: str, token: str, get: RawGet) -> LinkOutcome:
        try:
            response = await get(
                f'{origin}/api/auth0/mfa/',
                params={'location': 'cli', 'workspace': current_workspace()},
                headers=_headers(token),
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as e:
            logger.warning('Step-up link request failed: %s', type(e).__name__)
            return LinkOutcome(LinkKind.UNAVAILABLE)
        if not isinstance(body, dict):
            return LinkOutcome(LinkKind.UNAVAILABLE)
        mfa_url = body.get('mfa_url')
        if isinstance(mfa_url, str) and mfa_url:
            return LinkOutcome(LinkKind.ISSUED, mfa_url)
        if body.get('detail') == _MFA_ALREADY_DONE_DETAIL:
            return LinkOutcome(LinkKind.ALREADY_DONE)
        logger.warning('Step-up link response had neither a link nor a done notice')
        return LinkOutcome(LinkKind.UNAVAILABLE)

    async def _wait_for_mfa(self, origin: str, token: str, get: RawGet) -> bool:
        """Poll for the MFA; checks and sleeps never run past the wait budget."""
        deadline = self._monotonic() + STEP_UP_WAIT_SECONDS
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return False
            budget = httpx.Timeout(
                min(_REQUEST_TIMEOUT.read or remaining, remaining),
                connect=min(_REQUEST_TIMEOUT.connect or remaining, remaining),
            )
            try:
                # httpx timeouts are per phase; this bounds the whole check
                completed = await self._run_within(
                    self._mfa_completed(origin, token, budget, get), remaining
                )
            except TimeoutError:
                return False
            if completed:
                return True
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return False
            await self._sleep(min(STEP_UP_POLL_INTERVAL, remaining))

    @staticmethod
    async def _mfa_completed(
        origin: str, token: str, timeout: httpx.Timeout, get: RawGet
    ) -> bool:
        """One completion check; any failure reads as not done yet."""
        try:
            response = await get(
                f'{origin}/api/auth0/mfa/completion/',
                headers=_headers(token),
                timeout=timeout,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as e:
            logger.debug('Step-up completion check failed: %s', type(e).__name__)
            return False
        return isinstance(body, dict) and body.get('completed') is True


def _headers(token: str) -> dict[str, str]:
    return {
        'Accept': 'application/json',
        'User-Agent': MCP_USER_AGENT,
        'Authorization': f'Bearer {token}',
        **declared_agent_headers(),
    }
