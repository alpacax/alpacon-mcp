"""Host progress and poll timing schedules for the host-transfer waits."""

import itertools
import math
from http import HTTPStatus

import pytest

from tests.conftest import http_client_fixture
from utils.host_transfer import (
    CommandHidden,
    Failed,
    Refused,
    TimedOut,
    await_command_handled,
    await_transfer_success,
    deadline_after,
)
from utils.types import JsonValue

mock_http_client = http_client_fixture('utils.host_transfer')

_COMMAND = '/api/events/commands/cmd/'
_STATUS = '/api/webftp/downloads/dl/status/'
_TIMEOUT = 3
_HANDLED = {'status': 'success', 'handled_at': 'now', 'success': True}
_RUNNING = {'status': 'running', 'handled_at': None}
_REFUSAL: JsonValue = {'error': 'HTTP Error', 'status_code': HTTPStatus.FORBIDDEN}
_MOMENTS = [step / 2 for step in range(10)]  # 0s to 4.5s, past the deadline


async def _wait_command(timeout=_TIMEOUT):
    return await await_command_handled(
        'cmd',
        region='ap1',
        workspace='ws',
        token='t',
        deadline=deadline_after(timeout),
        interval=1,
    )


async def _wait_transfer(timeout=_TIMEOUT, deadline=None):
    return await await_transfer_success(
        _STATUS,
        region='ap1',
        workspace='ws',
        token='t',
        deadline=deadline_after(timeout) if deadline is None else deadline,
        interval=1,
    )


def _expected(handled_at, settled_at, ok):
    """The outcome and call log a caller sees, polling at 0s, 1s, 2s and 3s."""
    handled_on = math.ceil(handled_at)
    if handled_on > _TIMEOUT:
        return TimedOut(), ['command'] * (_TIMEOUT + 1)
    log = ['command'] * (handled_on + 1) + ['fetch']
    settled_on = max(handled_on, math.ceil(settled_at))
    if settled_on > _TIMEOUT:
        return TimedOut(), log + ['status'] * (
            max(_TIMEOUT, handled_on) - handled_on + 1
        )
    return (None if ok else Failed('broke')), log + ['status'] * (
        settled_on - handled_on + 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('handled_at', 'settled_at', 'ok'),
    [
        (handled, settled, ok)
        for handled, settled, ok in itertools.product(_MOMENTS, _MOMENTS, (True, False))
        if settled >= handled
    ],
)
async def test_wait_outcome_matches_host_progress_for_every_schedule(
    mock_http_client, fake_clock, handled_at, settled_at, ok
):
    log: list[str] = []

    async def _get(*, endpoint, **_):
        if endpoint == _COMMAND:
            log.append('command')
            return _HANDLED if fake_clock.now >= handled_at else _RUNNING
        log.append('status')
        settled = fake_clock.now >= settled_at
        return {'success': ok if settled else None, 'message': 'broke'}

    mock_http_client.get.side_effect = _get

    deadline = deadline_after(_TIMEOUT)
    outcome = await _wait_command()
    if outcome is None:
        log.append('fetch')
        outcome = await _wait_transfer(deadline=deadline)

    assert (outcome, log) == _expected(handled_at, settled_at, ok)


@pytest.mark.asyncio
async def test_a_wait_does_not_sleep_after_its_final_poll(mock_http_client, fake_clock):
    mock_http_client.get.return_value = _RUNNING

    outcome = await _wait_command(timeout=2.5)

    assert outcome == TimedOut()
    assert fake_clock.sleeps == [1, 1, 0.5]
    assert mock_http_client.get.call_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('wait', [_wait_command, _wait_transfer])
async def test_a_negative_timeout_checks_once_and_times_out(
    mock_http_client, fake_clock, wait
):
    mock_http_client.get.return_value = {**_RUNNING, 'success': None}

    outcome = await wait(timeout=-1)

    assert outcome == TimedOut()
    assert mock_http_client.get.call_count == 1
    assert fake_clock.sleeps == []


@pytest.mark.asyncio
@pytest.mark.parametrize('wait', [_wait_command, _wait_transfer])
async def test_a_refused_poll_hands_back_the_envelope(
    mock_http_client, fake_clock, wait
):
    mock_http_client.get.return_value = _REFUSAL

    outcome = await wait()

    assert outcome == Refused(_REFUSAL)
    assert mock_http_client.get.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('wait', [_wait_command, _wait_transfer])
async def test_a_non_object_poll_is_a_failure(mock_http_client, fake_clock, wait):
    mock_http_client.get.return_value = ['not', 'an', 'object']

    outcome = await wait()

    assert isinstance(outcome, Failed)
    assert outcome.reason is not None
    assert outcome.reason.startswith('Unexpected upstream response shape: <root>: ')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['denied', 'rejected', 'stuck'])
async def test_a_command_that_never_ran_fails_at_once(
    mock_http_client, fake_clock, status
):
    mock_http_client.get.return_value = {'status': status, 'handled_at': None}

    outcome = await _wait_command()

    assert outcome == Failed(f'the transfer command ended as {status}')
    assert mock_http_client.get.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('result', ['Permission denied', None])
async def test_a_command_handled_unsuccessfully_fails_with_its_result(
    mock_http_client, fake_clock, result
):
    mock_http_client.get.return_value = {**_HANDLED, 'success': False, 'result': result}

    outcome = await _wait_command()

    assert outcome == Failed(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('code', 'expected'),
    [
        pytest.param('api_token_scope_missing', CommandHidden(), id='scope-missing'),
        pytest.param('work_session_required', None, id='other-refusal'),
    ],
)
async def test_only_a_missing_scope_hides_the_command(
    mock_http_client, fake_clock, code, expected
):
    refusal: JsonValue = {
        'error': 'HTTP Error',
        'status_code': HTTPStatus.FORBIDDEN,
        'response': f'{{"code":"{code}"}}',
    }
    mock_http_client.get.return_value = refusal

    outcome = await _wait_command()

    assert outcome == (expected or Refused(refusal))
    assert mock_http_client.get.call_count == 1
