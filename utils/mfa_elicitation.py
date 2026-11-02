"""
Ask a 2026-07-28 client that declares elicitation.url for an MFA step-up as a URL
elicitation, in place of the mfa_required link result.
"""

import asyncio
from typing import Literal, TypedDict

from mcp.types import (
    ElicitRequest,
    ElicitRequestURLParams,
    ElicitResult,
    InputRequiredResult,
)
from mcp_types.version import is_version_at_least
from pydantic import TypeAdapter, ValidationError

from utils.client_surfaces import PER_REQUEST_CAPABILITIES_VERSION, current_round
from utils.error_handler import UpstreamAuthError
from utils.http_client import http_client
from utils.logger import get_logger
from utils.types import JsonValue

logger = get_logger('mfa_elicitation')

COMPLETION_ENDPOINT = '/api/auth0/mfa/completion/'
INPUT_KEY = 'alpacon_mfa'
MAX_ASKS = 3  # elicitations in all for one call, the first included
# The whole tools/call is one JSON response, so the poll holds its connection open.
POLL_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 1.0

_MESSAGE = (
    'Alpacon needs a fresh MFA check before it runs this action. '
    'Complete MFA on the page that opens, then come back here.'
)

type Answer = Literal['accept', 'decline', 'cancel']


class _State(TypedDict):
    source: str
    asked: int


_STATE = TypeAdapter(_State)

# The sealed state this call retries, and the client's answer (None when it sent none).
type Resumed = tuple[_State, Answer | None]


def _can_elicit() -> bool:
    """URL mode needs the per-request handshake, which only 2026-07-28 sends."""
    round_ = current_round()
    if round_ is None:
        return False
    return round_.surfaces.url_elicitation == 'declared' and is_version_at_least(
        round_.protocol_version, PER_REQUEST_CAPABILITIES_VERSION
    )


def resumed() -> Resumed | None:
    """The elicitation this call retries, or None on a first round."""
    round_ = current_round()
    if round_ is None or round_.request_state is None:
        return None
    try:
        state = _STATE.validate_json(round_.request_state)
    except ValidationError:
        return None
    response = round_.input_responses.get(INPUT_KEY)
    return state, response.action if isinstance(response, ElicitResult) else None


def _next_ask(previous: Resumed | None) -> int | None:
    """The count the next elicitation carries, or None to answer with the link."""
    if not _can_elicit():
        return None
    if previous is None:
        return 1
    state, answer = previous
    if answer != 'accept' or state['asked'] >= MAX_ASKS:
        return None
    return state['asked'] + 1


async def _mfa_pending(region: str, workspace: str, token: str) -> bool:
    """Poll until Alpacon reports MFA done; True only when it said not done until the
    timeout. No verdict is False, which leaves the decision to the upstream call."""
    pending = False
    try:
        async with asyncio.timeout(POLL_SECONDS):
            while True:
                body = await http_client.get(
                    region, workspace, COMPLETION_ENDPOINT, token=token
                )
                pending = isinstance(body, dict) and body.get('completed') is False
                if not pending:
                    return False
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except TimeoutError:
        return pending
    except UpstreamAuthError:
        raise
    except (
        Exception
    ) as exc:  # the probe never decides MFA, so its failure is no verdict
        logger.warning(
            'MFA completion probe for %s.%s raised %s', workspace, region, exc
        )
        return False


async def unfinished(
    previous: Resumed, *, region: str, workspace: str, token: object
) -> bool:
    """True when the user did not accept, or Alpacon still reports MFA not done."""
    if previous[1] != 'accept':
        return True
    return isinstance(token, str) and await _mfa_pending(region, workspace, token)


def elicitation(
    result: dict[str, JsonValue], previous: Resumed | None
) -> InputRequiredResult | None:
    """The URL elicitation standing in for a whole-retry mfa_required result, or None
    when the client cannot take one, the bound is reached, or there is no link."""
    url, source = result.get('mfa_url'), result.get('source', '')
    if not isinstance(url, str) or not isinstance(source, str):
        return None
    asked = _next_ask(previous)
    if asked is None:
        return None
    logger.info('MFA step-up for %s: URL elicitation %d of %d', source, asked, MAX_ASKS)
    request = ElicitRequest(params=ElicitRequestURLParams(message=_MESSAGE, url=url))
    state: _State = {'source': source, 'asked': asked}
    return InputRequiredResult(
        input_requests={INPUT_KEY: request},
        request_state=_STATE.dump_json(state).decode(),
    )
