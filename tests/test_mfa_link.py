"""fetch_mfa_link reads Alpacon's /api/auth0/mfa/ answer into one outcome."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import LINK_LOGGER
from utils.error_handler import MfaStepUpRequired, UpstreamAuthError
from utils.mfa_link import (
    MFAAlreadyDone,
    MFALink,
    MFALinkRaised,
    MFALinkUnusable,
    fetch_mfa_link,
)

JWT = 'header.payload.signature'
LINK = 'https://tenant.auth0.com/authorize?step_up_ticket=secret'

pytestmark = pytest.mark.asyncio


def _client(answer: object) -> MagicMock:
    get = (
        AsyncMock(side_effect=answer)
        if isinstance(answer, BaseException)
        else (AsyncMock(return_value=answer))
    )
    return MagicMock(get=get)


async def _fetch(client: MagicMock):
    return await fetch_mfa_link(client, region='ap1', workspace='acme', token=JWT)


async def test_a_link_answer_is_the_link():
    client = _client({'mfa_url': LINK})

    outcome = await _fetch(client)

    assert outcome == MFALink(LINK)
    client.get.assert_awaited_once_with(
        'ap1',
        'acme',
        '/api/auth0/mfa/',
        token=JWT,
        params={'location': 'cli', 'workspace': 'acme'},
    )


@pytest.mark.parametrize(
    'answer',
    [{'detail': 'MFA is already done.'}, {'detail': 'MFA는 이미 완료되었습니다.'}],
    ids=['english', 'translated'],
)
async def test_a_detail_only_answer_means_mfa_is_already_done(answer):
    assert await _fetch(_client(answer)) == MFAAlreadyDone()


@pytest.mark.parametrize(
    'answer',
    [
        {'mfa_url': ''},
        {'mfa_url': 7},
        {'unexpected': 'shape'},
        {'detail': 'x', 'extra': 1},
        ['not', 'a', 'dict'],
        None,
    ],
    ids=[
        'empty-link',
        'non-string-link',
        'unknown-keys',
        'detail-plus',
        'list',
        'none',
    ],
)
async def test_an_answer_without_a_link_is_unusable_and_logs_its_shape(answer, caplog):
    with caplog.at_level(logging.WARNING, logger=LINK_LOGGER):
        outcome = await _fetch(_client(answer))

    assert outcome == MFALinkUnusable(answer)
    [record] = [r for r in caplog.records if r.name == LINK_LOGGER]
    assert 'returned no link' in record.getMessage()


async def test_a_raised_fetch_is_raised_and_logs_why(caplog):
    with caplog.at_level(logging.WARNING, logger=LINK_LOGGER):
        outcome = await _fetch(_client(RuntimeError('connect timeout')))

    assert outcome == MFALinkRaised()
    [record] = [r for r in caplog.records if r.name == LINK_LOGGER]
    assert 'connect timeout' in record.getMessage()


@pytest.mark.parametrize(
    'refusal',
    [UpstreamAuthError(mfa_required=True), MfaStepUpRequired('auth')],
    ids=['re-auth', 'mfa-step-up'],
)
async def test_an_auth_refusal_propagates(refusal):
    with pytest.raises(type(refusal)):
        await _fetch(_client(refusal))


async def test_the_link_is_never_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        await _fetch(_client({'unexpected': LINK}))

    assert all(LINK not in r.getMessage() for r in caplog.records)
