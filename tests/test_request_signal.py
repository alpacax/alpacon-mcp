"""Per-request carrying of the upstream auth signal."""

import asyncio

import pytest

from utils import request_signal


def test_signal_without_a_request_is_dropped():
    # Given no request in flight, When a signal is written, Then nothing raises.
    request_signal.signal_upstream_auth_error({'mfa_required': True})

    assert request_signal.current_signal() is None


def test_signal_lands_in_the_request_that_began_it():
    # Given a request, When a signal is written, Then the request's dict holds it.
    holder = request_signal.begin_request()

    request_signal.signal_upstream_auth_error({'mfa_required': True, 'source': 'exec'})

    assert holder == {'mfa_required': True, 'source': 'exec'}
    assert request_signal.current_signal() is holder


def test_mfa_required_is_not_downgraded_by_a_later_signal():
    """A tool may call several APIs. Once one of them demands MFA, a later plain
    401 must not erase that."""
    holder = request_signal.begin_request()

    request_signal.signal_upstream_auth_error({'mfa_required': True, 'source': 'exec'})
    request_signal.signal_upstream_auth_error({'mfa_required': False, 'source': ''})

    assert holder['mfa_required'] is True


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_share_a_signal():
    """Two requests carrying the same token must not see each other's signal."""
    seen = {}

    async def request(name: str, fails: bool) -> None:
        holder = request_signal.begin_request()
        await asyncio.sleep(0)
        if fails:
            request_signal.signal_upstream_auth_error({'mfa_required': True})
        await asyncio.sleep(0)
        seen[name] = dict(holder)

    await asyncio.gather(request('failing', True), request('ok', False))

    assert seen['failing'] == {'mfa_required': True}
    assert seen['ok'] == {}


@pytest.mark.asyncio
async def test_a_child_task_writes_into_the_request_that_spawned_it():
    """MCP runs tool handlers in a separate task. Rebinding a ContextVar there is
    invisible to the parent, but mutating the object it holds is not."""
    holder = request_signal.begin_request()

    async def tool() -> None:
        request_signal.signal_upstream_auth_error({'mfa_required': True})

    await asyncio.create_task(tool())

    assert holder == {'mfa_required': True}
