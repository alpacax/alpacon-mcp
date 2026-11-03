"""
A 2026-07-28 client that declares elicitation.url gets the MFA link as a URL
elicitation; driven through the real server, SDK client and a real tool.
"""

import json
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from mcp import Client
from mcp.client import advertise
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from mcp.types import CallToolResult, ElicitRequestURLParams, ElicitResult, TextContent

from server import mcp
from tools.server_tools import list_servers  # importing registers the tool
from utils import mfa_elicitation, request_signal
from utils.http_client import AlpaconHTTPClient
from utils.mfa_elicitation import Answer

pytestmark = pytest.mark.asyncio

JWT = 'header.payload.signature'
CLAIMS = [{'schema_name': 'acme', 'region': 'ap1'}]
SERVERS = {'count': 0, 'results': []}
MODERN = '2026-07-28'
ACCEPT: Answer = 'accept'


def _link(fetch: int) -> str:
    return f'https://auth.example/authorize?step_up_ticket=t{fetch}'


class FakeAlpacon:
    """Refuses /api/servers/servers/ with auth_mfa_required until MFA is done."""

    def __init__(self) -> None:
        self.mfa_done = False
        self.done_after_probes = 0  # MFA completes on this probe, 0 for never
        self.server_calls = 0
        self.link_fetches = 0
        self.completion_probes = 0
        self.completion_body: object = None

    async def get(self, region, workspace, endpoint, token=None, params=None):
        if endpoint == '/api/auth0/mfa/':
            self.link_fetches += 1
            return (
                {'detail': 'MFA is already done.'}
                if self.mfa_done
                else {'mfa_url': _link(self.link_fetches)}
            )
        if endpoint == '/api/auth0/mfa/completion/':
            self.completion_probes += 1
            if self.completion_probes == self.done_after_probes:
                self.mfa_done = True
            body = self.completion_body
            if isinstance(body, Exception):
                raise body
            return {'completed': self.mfa_done} if body is None else body
        self.server_calls += 1
        if self.mfa_done:
            return SERVERS
        response = MagicMock()
        response.status_code = HTTPStatus.UNAUTHORIZED
        response.json.return_value = {'code': 'auth_mfa_required', 'source': 'server'}
        refusal = httpx.HTTPStatusError('401', request=MagicMock(), response=response)
        return AlpaconHTTPClient._handle_upstream_401(refusal, token=token)


@pytest.fixture
def alpacon(monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'true')
    monkeypatch.setattr(mfa_elicitation, 'POLL_SECONDS', 0.2)
    monkeypatch.setattr(mfa_elicitation, 'POLL_INTERVAL_SECONDS', 0.01)
    fake = FakeAlpacon()
    with (
        patch('utils.decorators._get_jwt_token', return_value=JWT),
        patch('utils.decorators.get_token_workspaces', return_value=CLAIMS),
        patch('utils.http_client.http_client.get', side_effect=fake.get),
    ):
        request_signal.begin_request()
        yield fake
    request_signal.end_request()


def _answering(*actions: Answer, alpacon: FakeAlpacon | None = None, done_on: int = 0):
    """An elicitation callback answering in turn; completes MFA on answer done_on."""
    asked: list[ElicitRequestURLParams] = []

    async def callback(context, params):
        asked.append(params)
        if alpacon is not None and len(asked) == done_on:
            alpacon.mfa_done = True
        return ElicitResult(action=actions[len(asked) - 1])

    return SimpleNamespace(callback=callback, asked=asked)


async def _list_servers(**client_options) -> CallToolResult:
    async with Client(mcp, **client_options) as client:
        return await client.call_tool(list_servers.__name__, {'workspace': 'acme'})


def _body(result: CallToolResult) -> dict[str, object]:
    assert result.is_error is False
    content = result.content[0]
    assert isinstance(content, TextContent)
    body: dict[str, object] = json.loads(content.text)
    return body


async def test_accept_then_completed_mfa_runs_the_call(alpacon):
    user = _answering(ACCEPT, alpacon=alpacon, done_on=1)

    result = await _list_servers(mode=MODERN, elicitation_callback=user.callback)

    assert _body(result)['status'] == 'success'
    assert [(p.mode, p.url) for p in user.asked] == [('url', _link(1))]
    assert alpacon.server_calls == 2
    assert alpacon.completion_probes == 1


async def test_a_client_declaring_mcp_apps_too_is_asked_through_elicitation(alpacon):
    user = _answering(ACCEPT, alpacon=alpacon, done_on=1)
    apps = advertise(EXTENSION_ID, {'mimeTypes': [APP_MIME_TYPE]})

    result = await _list_servers(
        mode=MODERN, elicitation_callback=user.callback, extensions=[apps]
    )

    assert _body(result)['status'] == 'success'
    assert [(p.mode, p.url) for p in user.asked] == [('url', _link(1))]


async def test_mfa_completed_during_the_poll_runs_the_call(alpacon):
    alpacon.done_after_probes = 3
    user = _answering(ACCEPT)

    result = await _list_servers(mode=MODERN, elicitation_callback=user.callback)

    assert _body(result)['status'] == 'success'
    assert len(user.asked) == 1
    assert alpacon.completion_probes == 3


async def test_accept_without_completed_mfa_asks_again_up_to_the_bound(alpacon):
    user = _answering(*[ACCEPT] * mfa_elicitation.MAX_ASKS)

    result = await _list_servers(mode=MODERN, elicitation_callback=user.callback)

    asks = mfa_elicitation.MAX_ASKS
    body = _body(result)
    assert (body['status'], body['mfa_url']) == ('mfa_required', _link(asks + 1))
    assert [p.url for p in user.asked] == [_link(n) for n in range(1, asks + 1)]
    assert alpacon.server_calls == 1  # an incomplete MFA never reaches Alpacon again


async def test_accept_completing_on_the_last_ask_still_runs_the_call(alpacon):
    asks = mfa_elicitation.MAX_ASKS
    user = _answering(*[ACCEPT] * asks, alpacon=alpacon, done_on=asks)

    result = await _list_servers(mode=MODERN, elicitation_callback=user.callback)

    assert _body(result)['status'] == 'success'
    assert len(user.asked) == asks


@pytest.mark.parametrize('action', ['cancel', 'decline'])
async def test_cancel_or_decline_falls_back_to_the_link(alpacon, action):
    user = _answering(action)

    result = await _list_servers(mode=MODERN, elicitation_callback=user.callback)

    body = _body(result)
    assert (body['status'], body['mfa_url'], body['source']) == (
        'mfa_required',
        _link(2),
        'server',
    )
    assert len(user.asked) == 1
    assert alpacon.completion_probes == 0
    assert alpacon.server_calls == 1


async def test_cancel_after_mfa_was_done_answers_that_mfa_is_done(alpacon):
    user = _answering('cancel', alpacon=alpacon, done_on=1)

    result = await _list_servers(mode=MODERN, elicitation_callback=user.callback)

    body = _body(result)
    assert (body['status'], body['mfa_url']) == ('mfa_required', None)
    assert 'already completed' in str(body['message'])
    assert alpacon.server_calls == 1


async def test_probe_without_a_verdict_leaves_the_decision_to_alpacon(alpacon):
    alpacon.completion_body = {'error': 'HTTP Error', 'status_code': 404}
    user = _answering(ACCEPT, alpacon=alpacon, done_on=1)

    result = await _list_servers(mode=MODERN, elicitation_callback=user.callback)

    assert _body(result)['status'] == 'success'
    assert alpacon.server_calls == 2


async def test_probe_that_raises_leaves_the_decision_to_alpacon(alpacon):
    alpacon.completion_body = RuntimeError('probe failed')
    user = _answering(ACCEPT, alpacon=alpacon, done_on=1)

    result = await _list_servers(mode=MODERN, elicitation_callback=user.callback)

    assert _body(result)['status'] == 'success'
    assert alpacon.server_calls == 2


async def test_modern_client_without_url_elicitation_gets_the_link(alpacon):
    result = await _list_servers(mode=MODERN)

    assert _body(result)['status'] == 'mfa_required'
    assert alpacon.server_calls == 1


async def test_pre_2026_client_gets_the_link_even_with_elicitation(alpacon):
    user = _answering(ACCEPT)

    result = await _list_servers(mode='legacy', elicitation_callback=user.callback)

    assert _body(result)['status'] == 'mfa_required'
    assert user.asked == []
