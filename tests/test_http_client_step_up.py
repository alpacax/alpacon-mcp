"""Action MFA answered with a step-up link, a wait, and one resend."""

import asyncio
import contextlib
import json
from http import HTTPStatus

import httpx
import jwt
import pytest

from utils import request_signal, request_workspace
from utils.error_handler import UpstreamAuthError
from utils.http_client import AlpaconHTTPClient
from utils.step_up import StepUp, StepUpLinks

ORIGIN = 'https://alpacax.dev.alpacon.io'
OTHER_ORIGIN = 'https://other.dev.alpacon.io'
ACTION_URL = f'{ORIGIN}/api/webftp/sessions/'
LINK = 'https://auth.dev.alpacon.io/authorize?step_up_ticket=t1'
OTHER_LINK = 'https://auth.dev.alpacon.io/authorize?step_up_ticket=t2'
NAMESPACE = 'https://alpacon.io/'
KEY = ('auth0|alice', 'mfa_c_device-1', ORIGIN)


def make_jwt(sub='auth0|alice', instance='mfa_c_device-1'):
    claims = {'sub': sub}
    if instance is not None:
        claims[f'{NAMESPACE}client_instance'] = instance
    return jwt.encode(claims, 'test-secret-for-step-up-claims-only', algorithm='HS256')


MFA_REFUSAL = {'code': 'auth_mfa_required', 'source': 'webftp'}
REAUTH_SIGNAL = {'mfa_required': True, 'source': 'webftp', 'code': 'auth_mfa_required'}


class Upstream:
    """A scripted Alpacon API that records every request it receives."""

    def __init__(self, action, link=None, completion=None):
        self.action = list(action)
        self.link = link if link is not None else [(HTTPStatus.OK, {'mfa_url': LINK})]
        self.completion = list(completion or [])
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == '/api/auth0/mfa/':
            status, body = self.link.pop(0)
        elif path == '/api/auth0/mfa/completion/':
            status, body = self.completion.pop(0)
        else:
            status, body = self.action.pop(0)
        if isinstance(body, Exception):
            raise body
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    def paths(self):
        return [c.url.path for c in self.calls]

    def action_calls(self):
        return [c for c in self.calls if c.url.path == '/api/webftp/sessions/']


class FakeTime:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


async def pass_through(awaitable, seconds):
    return await awaitable


@pytest.fixture
def fake_time():
    return FakeTime()


@pytest.fixture
def links(fake_time):
    return StepUpLinks(clock=fake_time.monotonic)


@pytest.fixture(autouse=True)
def bound_workspace():
    token = request_workspace.bind_workspace('alpacax')
    yield
    request_workspace.reset_workspace(token)


@pytest.fixture
def signal():
    holder = request_signal.begin_request()
    yield holder
    request_signal.end_request()


@pytest.fixture
def stdio_mode(monkeypatch):
    monkeypatch.delenv('ALPACON_MCP_AUTH_ENABLED', raising=False)


@pytest.fixture
def remote_mode(monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'true')


def make_client(upstream, fake_time, links, run_within=pass_through):
    step_up = StepUp(
        links=links,
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
        run_within=run_within,
    )
    return AlpaconHTTPClient(transport=httpx.MockTransport(upstream), step_up=step_up)


async def post(client, token=None, url=ACTION_URL, body=None):
    return await client.request(
        'POST', url, token=token or make_jwt(), json_data=body or {}
    )


async def test_first_refusal_returns_a_link_without_waiting(fake_time, links):
    # Given the API refuses the action for MFA
    upstream = Upstream(action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)])
    client = make_client(upstream, fake_time, links)
    token = make_jwt()

    # When the tool's request runs
    result = await post(client, token)

    # Then the link comes back at once in the field and the message
    assert result['mfa_url'] == LINK
    assert LINK in result['message']
    assert result['error'] == 'MFA Required'
    assert result['status_code'] == HTTPStatus.UNAUTHORIZED
    assert result['mfa_required'] is True
    assert fake_time.now == 0.0

    # And the link was asked for once with location=cli, and is remembered
    assert upstream.paths().count('/api/auth0/mfa/') == 1
    link_call = upstream.calls[1]
    assert link_call.url.params['location'] == 'cli'
    assert link_call.url.params['workspace'] == 'alpacax'
    assert links.get(KEY) == LINK

    # And the link request authenticates with the caller's token
    assert link_call.headers['Authorization'] == f'Bearer {token}'


async def test_second_call_waits_for_the_mfa_then_resends(fake_time, links):
    # Given the first call was refused and answered with a link
    upstream = Upstream(
        action=[
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.CREATED, {'id': 'ftp-1'}),
        ],
        completion=[
            (HTTPStatus.OK, {'completed': False}),
            (HTTPStatus.OK, {'completed': True}),
        ],
    )
    client = make_client(upstream, fake_time, links)
    token = make_jwt()
    request_workspace.bind_minted()
    first = await post(client, token)
    request_workspace.bind_minted()

    # When the tool is called again with the same arguments
    second = await post(client, token)

    # Then the first returned the link, and the second waited and resent
    assert first['mfa_url'] == LINK
    assert second == {'id': 'ftp-1'}
    assert upstream.paths().count('/api/auth0/mfa/') == 1
    assert upstream.paths().count('/api/auth0/mfa/completion/') == 2
    assert len(upstream.action_calls()) == 3
    assert fake_time.now == 2.0

    # And every completion check authenticates with the caller's token
    checks = [c for c in upstream.calls if c.url.path.endswith('/mfa/completion/')]
    assert [c.headers['Authorization'] for c in checks] == [f'Bearer {token}'] * 2


async def test_retry_after_mfa_resends_the_refused_request_once(fake_time, links):
    # Given a link already issued, and MFA completed on the second check
    links.remember(KEY, LINK)
    upstream = Upstream(
        action=[
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.CREATED, {'id': 'ftp-1'}),
        ],
        completion=[
            (HTTPStatus.OK, {'completed': False}),
            (HTTPStatus.OK, {'completed': True}),
        ],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool is called again
    result = await post(client, body={'username': 'root'})

    # Then the refused request is sent again with the same body, and its answer returned
    assert result == {'id': 'ftp-1'}
    action_calls = upstream.action_calls()
    assert len(action_calls) == 2
    assert json.loads(action_calls[1].content) == {'username': 'root'}
    assert '/api/auth0/mfa/' not in upstream.paths()
    assert links.get(KEY) is None


async def test_unfinished_mfa_returns_the_same_link_after_forty_seconds(
    fake_time, links
):
    # Given a link already issued and MFA never completed
    links.remember(KEY, LINK)
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        completion=[(HTTPStatus.OK, {'completed': False})] * 40,
    )
    client = make_client(upstream, fake_time, links)

    # When the tool is called again
    result = await post(client)

    # Then after exactly 40 seconds the remembered link comes back, and no new link is minted
    assert result['mfa_url'] == LINK
    assert fake_time.now == 40.0
    assert '/api/auth0/mfa/' not in upstream.paths()
    assert len(upstream.action_calls()) == 1


async def test_failing_completion_checks_count_as_not_done(fake_time, links):
    # Given a link already issued and every completion check failing
    links.remember(KEY, LINK)
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        completion=[(HTTPStatus.BAD_GATEWAY, {'detail': 'down'})] * 40,
    )
    client = make_client(upstream, fake_time, links)

    # When the tool is called again
    result = await post(client)

    # Then the remembered link comes back after exactly 40 seconds, with nothing resent
    assert result['mfa_url'] == LINK
    assert fake_time.now == 40.0
    assert len(upstream.action_calls()) == 1


async def test_resend_refused_again_returns_the_same_link_without_waiting(
    fake_time, links
):
    # Given MFA completes but the resent request is refused for MFA again
    links.remember(KEY, LINK)
    upstream = Upstream(
        action=[
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
        ],
        completion=[(HTTPStatus.OK, {'completed': True})],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool is called again
    result = await post(client)

    # Then the request was resent after one completion check, and the same link
    # comes back with no further wait and stays remembered
    assert len(upstream.action_calls()) == 2
    assert upstream.paths().count('/api/auth0/mfa/completion/') == 1
    assert result['mfa_url'] == LINK
    assert fake_time.now == 0.0
    assert links.get(KEY) == LINK


async def test_refused_resend_does_not_extend_the_links_life(fake_time, links):
    # Given a link remembered at time 0, and a call 300 seconds later whose resend is refused
    links.remember(KEY, LINK)
    fake_time.now = 300.0
    upstream = Upstream(
        action=[
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
        ],
        completion=[(HTTPStatus.OK, {'completed': True})],
    )
    client = make_client(upstream, fake_time, links)
    await post(client)

    # When 600 seconds have passed since the link was first remembered
    fake_time.now = 599.0
    still_there = links.get(KEY)
    fake_time.now = 600.0
    expired = links.get(KEY)

    # Then the link lived exactly its original 600 seconds
    assert still_there == LINK
    assert expired is None


async def test_already_done_answer_asks_to_call_again(fake_time, links):
    # Given the link endpoint says MFA is already done
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, {'detail': 'MFA is already done.'})],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client)

    # Then the answer asks for a retry and carries no link
    assert result['message'] == (
        'MFA was just completed. Call this tool again with the same arguments.'
    )
    assert 'mfa_url' not in result


async def test_token_without_client_instance_in_remote_mode_falls_back_to_the_403(
    fake_time, links, remote_mode, signal
):
    # Given remote mode and a token with no client instance claim
    upstream = Upstream(action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)])
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    with pytest.raises(UpstreamAuthError) as raised:
        await post(client, make_jwt(instance=None))

    # Then no link is requested and the request is signalled for the 403
    assert upstream.paths() == ['/api/webftp/sessions/']
    assert signal == REAUTH_SIGNAL
    assert raised.value.source == 'webftp'


async def test_token_without_client_instance_in_stdio_mode_returns_the_plain_error(
    fake_time, links, stdio_mode
):
    # Given stdio mode and a token with no client instance claim
    upstream = Upstream(action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)])
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client, make_jwt(instance=None))

    # Then no link is requested and the plain MFA error comes back
    assert upstream.paths() == ['/api/webftp/sessions/']
    assert result['mfa_required'] is True
    assert result['message'] == 'MFA verification required'
    assert 'mfa_url' not in result


async def test_link_remembered_for_one_origin_is_not_used_for_another(fake_time, links):
    # Given a link remembered for the first origin
    links.remember(KEY, LINK)
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, {'mfa_url': OTHER_LINK})],
    )
    client = make_client(upstream, fake_time, links)

    # When the same person is refused on another origin
    result = await post(client, url=f'{OTHER_ORIGIN}/api/webftp/sessions/')

    # Then that refusal requests its own link, from its own origin, without waiting
    assert result['mfa_url'] == OTHER_LINK
    assert upstream.calls[1].url.host == 'other.dev.alpacon.io'
    assert '/api/auth0/mfa/completion/' not in upstream.paths()
    assert links.get(KEY) == LINK


@pytest.mark.parametrize(
    'other_token',
    [
        make_jwt(sub='auth0|bob'),
        make_jwt(instance='mfa_c_device-2'),
    ],
    ids=['another-person', 'another-client-instance'],
)
async def test_link_is_kept_per_person_and_client_instance(
    fake_time, links, other_token
):
    # Given a link remembered for alice on device-1
    links.remember(KEY, LINK)
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, {'mfa_url': OTHER_LINK})],
    )
    client = make_client(upstream, fake_time, links)

    # When a different token is refused
    result = await post(client, other_token)

    # Then it gets its own link, without waiting on alice's
    assert result['mfa_url'] == OTHER_LINK
    assert '/api/auth0/mfa/completion/' not in upstream.paths()
    assert links.get(KEY) == LINK


async def test_link_remembered_six_hundred_seconds_ago_is_not_used(fake_time, links):
    # Given a link remembered at time 0, and a refusal 600 seconds later
    links.remember(KEY, LINK)
    fake_time.now = 600.0
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, {'mfa_url': OTHER_LINK})],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool is called
    result = await post(client)

    # Then a new link is requested and no completion check is made
    assert result['mfa_url'] == OTHER_LINK
    assert upstream.paths().count('/api/auth0/mfa/') == 1
    assert '/api/auth0/mfa/completion/' not in upstream.paths()


async def test_link_request_failure_in_remote_mode_falls_back_to_the_403(
    fake_time, links, remote_mode, signal
):
    # Given remote mode and a link endpoint that fails
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.INTERNAL_SERVER_ERROR, {'detail': 'boom'})],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    with pytest.raises(UpstreamAuthError) as raised:
        await post(client)

    # Then the request is signalled for the 403 challenge
    assert signal == REAUTH_SIGNAL
    assert raised.value.source == 'webftp'


async def test_link_request_failure_in_stdio_mode_returns_the_plain_mfa_error(
    fake_time, links, stdio_mode
):
    # Given stdio mode and a link endpoint that fails
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.INTERNAL_SERVER_ERROR, {'detail': 'boom'})],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client)

    # Then the plain MFA error comes back without a link
    assert result['mfa_required'] is True
    assert 'mfa_url' not in result


async def test_unknown_workspace_in_stdio_mode_returns_the_plain_error_without_a_link(
    fake_time, links, stdio_mode
):
    # Given stdio mode and no workspace bound for this call
    request_workspace.bind_workspace(None)
    upstream = Upstream(action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)])
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client)

    # Then no link is requested and the plain MFA error comes back
    assert '/api/auth0/mfa/' not in upstream.paths()
    assert 'mfa_url' not in result


async def test_unknown_workspace_in_stdio_mode_ignores_a_remembered_link(
    fake_time, links, stdio_mode
):
    # Given a remembered link but no workspace bound for this call
    links.remember(KEY, LINK)
    request_workspace.bind_workspace(None)
    upstream = Upstream(action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)])
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client)

    # Then the plain error comes back, with no completion check or link request
    assert result['mfa_required'] is True
    assert 'mfa_url' not in result
    assert upstream.paths() == ['/api/webftp/sessions/']


async def test_unknown_workspace_in_remote_mode_ignores_a_remembered_link(
    fake_time, links, remote_mode, signal
):
    # Given a remembered link but no workspace bound for this call
    links.remember(KEY, LINK)
    request_workspace.bind_workspace(None)
    upstream = Upstream(action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)])
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    with pytest.raises(UpstreamAuthError) as raised:
        await post(client)

    # Then the request is signalled for the 403, with no completion check or link request
    assert signal == REAUTH_SIGNAL
    assert raised.value.source == 'webftp'
    assert upstream.paths() == ['/api/webftp/sessions/']


async def test_sign_in_mfa_signal_requests_no_link(fake_time, links, stdio_mode):
    # Given stdio mode and a token refused for missing sign-in MFA
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, {'code': 'auth_token_mfa_missing'})]
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client)

    # Then no link is requested and the existing MFA error comes back
    assert '/api/auth0/mfa/' not in upstream.paths()
    assert result['mfa_required'] is True
    assert 'mfa_url' not in result


async def test_api_token_gets_the_plain_error_and_no_link(fake_time, links, stdio_mode):
    # Given stdio mode with a static API token
    upstream = Upstream(action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)])
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client, token='static-api-token')

    # Then no link is requested and the plain MFA error comes back
    assert '/api/auth0/mfa/' not in upstream.paths()
    assert result['mfa_required'] is True
    assert result['status_code'] == HTTPStatus.UNAUTHORIZED
    assert 'mfa_url' not in result


async def test_a_check_still_running_at_the_deadline_is_cancelled(fake_time, links):
    # Given a remembered link and a completion check that never answers
    links.remember(KEY, LINK)
    check_started = asyncio.Event()
    cancelled = []
    limits = []
    action_calls = []

    async def upstream(request):
        if request.url.path == '/api/webftp/sessions/':
            action_calls.append(request)
        if request.url.path == '/api/auth0/mfa/completion/':
            check_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(request.url.path)
                raise
        return httpx.Response(HTTPStatus.UNAUTHORIZED, json=MFA_REFUSAL)

    async def run_within(awaitable, seconds):
        # A manual timer standing in for asyncio.wait_for: once the check is in
        # flight, the fake clock reaches the limit and the check is cancelled.
        limits.append(seconds)
        check = asyncio.ensure_future(awaitable)
        await check_started.wait()
        fake_time.now += seconds
        check.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await check
        raise TimeoutError

    client = make_client(upstream, fake_time, links, run_within=run_within)

    # When the tool is called again
    result = await post(client)

    # Then the in-flight check was cancelled at the deadline and the same link returns
    assert cancelled == ['/api/auth0/mfa/completion/']
    assert limits == [40.0]
    assert fake_time.now == 40.0
    assert result['mfa_url'] == LINK
    assert len(action_calls) == 1
    assert links.get(KEY) == LINK


async def test_a_done_answer_after_the_deadline_leads_to_the_resend(fake_time, links):
    # Given a remembered link and a check that answers "done" only past the deadline
    links.remember(KEY, LINK)

    class LateUpstream(Upstream):
        def __call__(self, request):
            if request.url.path == '/api/auth0/mfa/completion/':
                fake_time.now += 61.0
            return super().__call__(request)

    upstream = LateUpstream(
        action=[
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.CREATED, {'id': 'ftp-1'}),
        ],
        completion=[(HTTPStatus.OK, {'completed': True})],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool is called again
    result = await post(client)

    # Then the action is resent and its answer returned
    assert result == {'id': 'ftp-1'}
    assert len(upstream.action_calls()) == 2


@pytest.mark.parametrize(
    'body', [{}, [], {'mfa_url': ''}, {'detail': 'Unexpected response'}]
)
async def test_malformed_link_response_in_remote_mode_falls_back_to_the_403(
    fake_time, links, remote_mode, signal, body
):
    # Given a link endpoint that answers 200 with neither a link nor the done notice
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, body)],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    with pytest.raises(UpstreamAuthError) as raised:
        await post(client)

    # Then the request is signalled for the 403 challenge
    assert signal == REAUTH_SIGNAL
    assert raised.value.source == 'webftp'


@pytest.mark.parametrize(
    'body', [{}, [], {'mfa_url': ''}, {'detail': 'Unexpected response'}]
)
async def test_malformed_link_response_in_stdio_mode_is_not_taken_for_completed_mfa(
    fake_time, links, stdio_mode, body
):
    # Given a link endpoint that answers 200 with neither a link nor the done notice
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, body)],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client)

    # Then the existing MFA error comes back, not the "just completed" notice
    assert result['message'] == 'MFA verification required'


async def test_link_request_transport_failure_in_remote_mode_falls_back_to_the_403(
    fake_time, links, remote_mode, signal
):
    # Given remote mode and a link endpoint that cannot be reached
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, httpx.ConnectError('refused'))],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    with pytest.raises(UpstreamAuthError) as raised:
        await post(client)

    # Then the request is signalled for the 403 challenge and no link is kept
    assert signal == REAUTH_SIGNAL
    assert raised.value.source == 'webftp'
    assert links.get(KEY) is None


async def test_link_request_transport_failure_in_stdio_mode_returns_the_plain_error(
    fake_time, links, stdio_mode
):
    # Given stdio mode and a link endpoint that cannot be reached
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, httpx.ConnectError('refused'))],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client)

    # Then the plain MFA error comes back without a link
    assert result['message'] == 'MFA verification required'
    assert 'mfa_url' not in result


async def test_non_json_link_response_falls_back_to_the_plain_error(
    fake_time, links, stdio_mode
):
    # Given a link endpoint that answers 200 with a body that is not JSON
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        link=[(HTTPStatus.OK, b'<html>gateway</html>')],
    )
    client = make_client(upstream, fake_time, links)

    # When the tool's request runs
    result = await post(client)

    # Then the plain MFA error comes back, not the "just completed" notice
    assert result['message'] == 'MFA verification required'
    assert 'mfa_url' not in result


async def test_completion_check_transport_failure_counts_as_not_done(fake_time, links):
    # Given a remembered link and completion checks that cannot reach the server
    links.remember(KEY, LINK)
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        completion=[(HTTPStatus.OK, httpx.ConnectError('refused'))] * 40,
    )
    client = make_client(upstream, fake_time, links)

    # When the tool is called again
    result = await post(client)

    # Then the remembered link comes back after exactly 40 seconds, with nothing resent
    assert result['mfa_url'] == LINK
    assert fake_time.now == 40.0
    assert len(upstream.action_calls()) == 1


async def test_non_json_completion_response_counts_as_not_done(fake_time, links):
    # Given a remembered link and completion checks answering 200 with non-JSON
    links.remember(KEY, LINK)
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)],
        completion=[(HTTPStatus.OK, b'<html>gateway</html>')] * 40,
    )
    client = make_client(upstream, fake_time, links)

    # When the tool is called again
    result = await post(client)

    # Then the remembered link comes back after exactly 40 seconds, with nothing resent
    assert result['mfa_url'] == LINK
    assert fake_time.now == 40.0
    assert len(upstream.action_calls()) == 1


async def test_second_refusal_in_the_same_call_returns_its_link_without_waiting(
    fake_time, links
):
    # Given one tool call whose first request was refused and answered with a link
    upstream = Upstream(
        action=[
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
        ]
    )
    client = make_client(upstream, fake_time, links)
    token = make_jwt()
    request_workspace.bind_minted()
    first = await post(client, token)

    # When a later request of the same call is refused too
    second = await post(client, token)

    # Then it gets the same link at once: no wait, no resend, no second link request
    assert first['mfa_url'] == LINK
    assert second['mfa_url'] == LINK
    assert fake_time.now == 0.0
    assert upstream.paths().count('/api/auth0/mfa/') == 1
    assert '/api/auth0/mfa/completion/' not in upstream.paths()
    assert len(upstream.action_calls()) == 2


async def test_refusal_in_the_next_call_waits_and_resends(fake_time, links):
    # Given a link minted by an earlier tool call
    upstream = Upstream(
        action=[
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.UNAUTHORIZED, MFA_REFUSAL),
            (HTTPStatus.CREATED, {'id': 'ftp-1'}),
        ],
        completion=[(HTTPStatus.OK, {'completed': True})],
    )
    client = make_client(upstream, fake_time, links)
    token = make_jwt()
    request_workspace.bind_minted()
    await post(client, token)
    request_workspace.bind_minted()

    # When the next tool call is refused
    result = await post(client, token)

    # Then it waits for the MFA and resends instead of returning the link
    assert result == {'id': 'ftp-1'}
    assert upstream.paths().count('/api/auth0/mfa/') == 1
    assert upstream.paths().count('/api/auth0/mfa/completion/') == 1
    assert len(upstream.action_calls()) == 3


async def test_a_resend_that_times_out_is_not_retried(fake_time, links):
    # Given a remembered link, MFA completed, and a resend that times out
    links.remember(KEY, LINK)
    timeout = httpx.ReadTimeout('read timed out')
    upstream = Upstream(
        action=[(HTTPStatus.UNAUTHORIZED, MFA_REFUSAL)]
        + [(HTTPStatus.OK, timeout)] * 3,
        completion=[(HTTPStatus.OK, {'completed': True})],
    )
    client = make_client(upstream, fake_time, links)
    client.retry_delay = 0

    # When the tool is called again
    result = await post(client)

    # Then the resend is tried once, so the wait and the resend fit one client timeout
    assert len(upstream.action_calls()) == 2
    assert result['error'] == 'Timeout'
