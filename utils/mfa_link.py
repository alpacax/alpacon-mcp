"""Fetch Alpacon's MFA link and read what its answer means.
The link carries a single-use ticket: never log it."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.error_handler import MfaStepUpRequired, UpstreamAuthError
from utils.logger import get_logger
from utils.types import JsonValue

if TYPE_CHECKING:  # http_client imports mfa_step_up, which imports this module
    from utils.http_client import AlpaconHTTPClient

logger = get_logger('mfa_link')

MFA_LINK_ENDPOINT = '/api/auth0/mfa/'
MFA_COMPLETION_ENDPOINT = '/api/auth0/mfa/completion/'


@dataclass(frozen=True)
class MFALink:
    url: str


@dataclass(frozen=True)
class MFAAlreadyDone:
    """Alpacon's answer when the token's MFA is still fresh."""


@dataclass(frozen=True)
class MFALinkRaised:
    """The fetch raised before Alpacon answered."""


@dataclass(frozen=True)
class MFALinkUnusable:
    body: JsonValue  # Alpacon's answer, which holds no link


type MFALinkFailed = MFALinkRaised | MFALinkUnusable
type MFALinkOutcome = MFALink | MFAAlreadyDone | MFALinkFailed


async def fetch_mfa_link(
    client: 'AlpaconHTTPClient', *, region: str, workspace: str, token: str | None
) -> MFALinkOutcome:
    """UpstreamAuthError and MfaStepUpRequired propagate; any other failure is
    MFALinkRaised or MFALinkUnusable."""
    try:
        body = await client.get(
            region,
            workspace,
            MFA_LINK_ENDPOINT,
            token=token,
            # cli on purpose: Alpacon stores no location, and its MFA success page
            # returns step_up_ticket only for cli (#427 step 3).
            params={'location': 'cli', 'workspace': workspace},
        )
    except (UpstreamAuthError, MfaStepUpRequired):
        raise
    except Exception as exc:
        logger.warning('MFA link fetch for %s.%s raised %s', workspace, region, exc)
        return MFALinkRaised()
    url = body.get('mfa_url') if isinstance(body, dict) else None
    if isinstance(url, str) and url:
        return MFALink(url)
    if isinstance(body, dict) and set(body) == {'detail'}:
        return MFAAlreadyDone()  # detail may be translated, so only its shape counts
    logger.warning(
        'MFA link fetch for %s.%s returned no link (keys: %s)',
        workspace,
        region,
        sorted(body) if isinstance(body, dict) else type(body).__name__,
    )
    return MFALinkUnusable(body)
