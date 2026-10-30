"""An auth_mfa_required 401 in remote mode answers mfa_required with a link (#427)."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tools import command_tools, system_info_tools
from utils import mfa_step_up, request_signal
from utils.decorators import with_error_handling
from utils.error_handler import UpstreamAuthError
from utils.http_client import AlpaconHTTPClient, http_client

JWT = 'header.payload.signature'
LINK = 'https://tenant.auth0.com/authorize?ticket=secret'
STEP_UP_LOGGER = 'alpacon_mcp.mfa_step_up'


def _401_with_body(body: dict[str, object]) -> httpx.HTTPStatusError:
    response = MagicMock()
    response.status_code = 401
    response.text = ''
    response.json.return_value = body
    return httpx.HTTPStatusError('HTTP 401', request=MagicMock(), response=response)


def _401(code: str, source: str = 'command') -> httpx.HTTPStatusError:
    return _401_with_body({'code': code, 'source': source})


def _refuse(code: str = 'auth_mfa_required', source: str = 'command') -> None:
    AlpaconHTTPClient._handle_upstream_401(_401(code, source), token=JWT)


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> request_signal.AuthSignal:
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'true')
    return request_signal.begin_request()


@pytest.fixture
def mfa_fetch():
    """Alpacon's /api/auth0/mfa/ answer; tests set return_value or side_effect."""
    fetch = AsyncMock(return_value={'mfa_url': LINK})
    with patch('utils.decorators.http_client.get', fetch):
        yield fetch


@with_error_handling
async def refused_tool(workspace='acme', region='ap1', **kwargs):
    _refuse()
    return {'status': 'success'}


class TestMfaRequiredResult:
    @pytest.mark.asyncio
    async def test_step_up_in_remote_mode_returns_the_link_and_leaves_the_signal_empty(
        self, remote, mfa_fetch
    ):
        result = await refused_tool(token=JWT)

        assert result['status'] == 'mfa_required'
        assert result['mfa_url'] == LINK
        assert result['source'] == 'command'
        assert (result['workspace'], result['region']) == ('acme', 'ap1')
        assert 'retry the same call once' in result['message']
        assert remote == {}

    @pytest.mark.asyncio
    async def test_link_is_fetched_with_cli_location_workspace_and_callers_token(
        self, remote, mfa_fetch
    ):
        await refused_tool(token=JWT)

        mfa_fetch.assert_awaited_once_with(
            'ap1',
            'acme',
            '/api/auth0/mfa/',
            token=JWT,
            params={'location': 'cli', 'workspace': 'acme'},
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'answer',
        [{'detail': 'MFA is already done.'}, {'detail': 'MFA는 이미 완료되었습니다.'}],
        ids=['english', 'translated'],
    )
    async def test_already_done_answer_returns_no_link_and_says_retry(
        self, remote, mfa_fetch, answer
    ):
        mfa_fetch.return_value = answer

        result = await refused_tool(token=JWT)

        assert result['status'] == 'mfa_required'
        assert result['mfa_url'] is None
        assert 'already completed' in result['message']
        assert 'retry' in result['message']

    @pytest.mark.parametrize(
        'failure',
        [
            {'error': 'HTTP Error', 'status_code': 500},
            ['not', 'a', 'dict'],
            {'unexpected': 'shape'},
            {'mfa_url': ''},
            RuntimeError('boom'),
        ],
        ids=['error-dict', 'not-a-dict', 'unknown-body', 'empty-link', 'exception'],
    )
    @pytest.mark.asyncio
    async def test_failed_link_fetch_returns_no_link_and_points_to_the_console(
        self, remote, mfa_fetch, failure, caplog
    ):
        if isinstance(failure, Exception):
            mfa_fetch.side_effect = failure
        else:
            mfa_fetch.return_value = failure

        with caplog.at_level(logging.WARNING, logger=STEP_UP_LOGGER):
            result = await refused_tool(token=JWT)

        assert result['status'] == 'mfa_required'
        assert result['mfa_url'] is None
        assert 'web console' in result['message']
        assert any(
            r.levelno == logging.WARNING and r.name == STEP_UP_LOGGER
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_link_is_not_written_to_the_log(self, remote, mfa_fetch, caplog):
        with caplog.at_level(logging.DEBUG):
            await refused_tool(token=JWT)

        assert 'ticket=secret' not in caplog.text

    @pytest.mark.asyncio
    async def test_bad_token_on_the_link_fetch_propagates(self, remote, mfa_fetch):
        mfa_fetch.side_effect = UpstreamAuthError()

        with pytest.raises(UpstreamAuthError):
            await refused_tool(token=JWT)

    @pytest.mark.asyncio
    async def test_a_later_call_without_step_up_is_unaffected(self, remote, mfa_fetch):
        await refused_tool(token=JWT)

        @with_error_handling
        async def fine_tool(workspace='acme', region='ap1', **kwargs):
            return {'status': 'success'}

        assert await fine_tool(token=JWT) == {'status': 'success'}


class TestOtherRefusalsKeepTheirPath:
    @pytest.mark.asyncio
    async def test_sign_in_mfa_missing_still_signals_and_raises(self, remote):
        @with_error_handling
        async def tool(workspace='acme', region='ap1', **kwargs):
            _refuse('auth_token_mfa_missing')

        with pytest.raises(UpstreamAuthError) as raised:
            await tool(token=JWT)

        assert raised.value.mfa_required is True
        assert remote == {'mfa_required': True, 'source': 'command'}

    @pytest.mark.asyncio
    async def test_plain_401_still_signals_and_raises(self, remote):
        @with_error_handling
        async def tool(workspace='acme', region='ap1', **kwargs):
            _refuse('auth_token_missing')

        with pytest.raises(UpstreamAuthError):
            await tool(token=JWT)

        assert remote['mfa_required'] is False

    @pytest.mark.asyncio
    async def test_stdio_mode_still_returns_the_error_dict(self, monkeypatch):
        monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'false')

        @with_error_handling
        async def tool(workspace='acme', region='ap1', **kwargs):
            return AlpaconHTTPClient._handle_upstream_401(
                _401('auth_mfa_required'), token=JWT
            )

        result = await tool(token=JWT)

        assert result['error'] == 'MFA Required'
        assert result['mfa_required'] is True
        assert 'mfa_url' not in result


class TestFanOutAndNesting:
    @pytest.mark.asyncio
    async def test_fan_out_that_swallows_the_exception_still_answers_mfa_required(
        self, remote, mfa_fetch
    ):
        async def child(refuse: bool):
            if refuse:
                _refuse()
            return {'ok': True}

        @with_error_handling
        async def fan_out(workspace='acme', region='ap1', **kwargs):
            gathered = await asyncio.gather(
                child(False), child(True), return_exceptions=True
            )
            return {'status': 'success', 'parts': [str(g) for g in gathered]}

        result = await fan_out(token=JWT)

        assert result['status'] == 'mfa_required'
        assert result['mfa_url'] == LINK
        assert remote == {}

    @pytest.mark.asyncio
    async def test_nested_decorated_call_answers_once(self, remote, mfa_fetch):
        @with_error_handling
        async def inner(workspace='acme', region='ap1', **kwargs):
            _refuse()

        @with_error_handling
        async def outer(workspace='acme', region='ap1', **kwargs):
            gathered = await asyncio.gather(
                inner(token=JWT), inner(token=JWT), return_exceptions=True
            )
            return {'status': 'success', 'errors': len(gathered)}

        result = await outer(token=JWT)

        assert result['status'] == 'mfa_required'
        mfa_fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_nested_call_lets_the_step_up_propagate_to_the_outer_call(
        self, remote, mfa_fetch
    ):
        @with_error_handling
        async def inner(workspace='acme', region='ap1', **kwargs):
            _refuse()

        @with_error_handling
        async def outer(workspace='acme', region='ap1', **kwargs):
            return await inner(token=JWT)

        result = await outer(token=JWT)

        assert result['status'] == 'mfa_required'
        mfa_fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_server_overview_answers_mfa_required_when_every_sub_call_is_refused(
        self, remote
    ):
        async def refuse_but_the_link(*args, **kwargs):
            if kwargs.get('endpoint') == '/api/auth0/mfa/' or '/api/auth0/mfa/' in args:
                return {'mfa_url': LINK}
            _refuse()

        claims = [{'schema_name': 'acme', 'region': 'ap1'}]
        with (
            patch('utils.decorators.http_client.get', refuse_but_the_link),
            patch('utils.decorators._get_jwt_token', return_value=JWT),
            patch('utils.decorators.get_token_workspaces', return_value=claims),
        ):
            result = await system_info_tools.get_server_overview(
                '550e8400-e29b-41d4-a716-446655440000', 'acme', 'ap1'
            )

        assert result['status'] == 'mfa_required'
        assert result['mfa_url'] == LINK
        assert 'retry the same call once with the same arguments' in result['message']
        assert 'partial_result' not in result

    @pytest.mark.asyncio
    async def test_a_concurrent_call_without_step_up_is_unaffected(
        self, remote, mfa_fetch
    ):
        @with_error_handling
        async def fine_tool(workspace='acme', region='ap1', **kwargs):
            await asyncio.sleep(0)
            return {'status': 'success'}

        refused, fine = await asyncio.gather(
            refused_tool(token=JWT), fine_tool(token=JWT)
        )

        assert refused['status'] == 'mfa_required'
        assert fine == {'status': 'success'}

    @pytest.mark.asyncio
    async def test_holder_is_released_after_each_call(self, remote, mfa_fetch):
        await refused_tool(token=JWT)
        await refused_tool(token=JWT)

        assert mfa_fetch.await_count == 2
        with mfa_step_up.tool_call() as call:
            assert call is not None
            assert call.required is False


class TestSourceBoundary:
    @pytest.mark.parametrize(
        'body',
        [
            {'code': 'auth_mfa_required'},
            {'code': 'auth_mfa_required', 'source': None},
            {'code': 'auth_mfa_required', 'source': 5},
        ],
        ids=['absent', 'null', 'not-a-string'],
    )
    @pytest.mark.asyncio
    async def test_a_step_up_without_a_usable_source_still_answers_mfa_required(
        self, remote, mfa_fetch, body
    ):
        @with_error_handling
        async def tool(workspace='acme', region='ap1', **kwargs):
            AlpaconHTTPClient._handle_upstream_401(_401_with_body(body), token=JWT)

        result = await tool(token=JWT)

        assert result['status'] == 'mfa_required'
        assert 'source' not in result

    @pytest.mark.asyncio
    async def test_the_first_source_wins(self, remote, mfa_fetch):
        @with_error_handling
        async def tool(workspace='acme', region='ap1', **kwargs):
            for source in ('command', 'webftp'):
                try:
                    _refuse(source=source)
                except mfa_step_up.MfaStepUpRequired:
                    pass
            return {'status': 'success'}

        result = await tool(token=JWT)

        assert result['source'] == 'command'


class TestReadOnlyRetriesWhole:
    @pytest.mark.asyncio
    async def test_a_read_only_tool_that_returned_normally_asks_for_the_whole_call(
        self, remote, mfa_fetch
    ):
        async def child():
            _refuse()

        async def read_tool(workspace='acme', region='ap1', **kwargs):
            await asyncio.gather(child(), return_exceptions=True)
            return {'status': 'success', 'parts': []}

        result = await with_error_handling(read_tool, read_only=True)(token=JWT)

        assert result['status'] == 'mfa_required'
        assert 'partial_result' not in result
        assert 'retry the same call once with the same arguments' in result['message']

    @pytest.mark.asyncio
    async def test_a_tool_that_is_not_read_only_keeps_partial_result(
        self, remote, mfa_fetch
    ):
        async def write_tool(workspace='acme', region='ap1', **kwargs):
            await asyncio.gather(_refusing_child(), return_exceptions=True)
            return {'status': 'success', 'ran': 1}

        result = await with_error_handling(write_tool)(token=JWT)

        assert result['partial_result'] == {'status': 'success', 'ran': 1}
        assert 'never the whole call' in result['message']


class TestPartialWrites:
    @pytest.mark.asyncio
    async def test_a_fan_out_with_one_success_keeps_it_in_partial_result(
        self, remote, mfa_fetch
    ):
        async def run_on(server: str):
            if server == 'refused':
                _refuse()
            return {'server': server, 'status': 'success'}

        @with_error_handling
        async def execute_command_multi_server(
            workspace='acme', region='ap1', **kwargs
        ):
            outcomes = await asyncio.gather(
                run_on('fine'), run_on('refused'), return_exceptions=True
            )
            return {
                'status': 'success',
                'results': [
                    o if isinstance(o, dict) else {'server': 'refused', 'error': str(o)}
                    for o in outcomes
                ],
            }

        result = await execute_command_multi_server(token=JWT)

        assert result['status'] == 'mfa_required'
        assert result['mfa_url'] == LINK
        assert {'server': 'fine', 'status': 'success'} in result['partial_result'][
            'results'
        ]
        assert 'partial_result shows what already ran' in result['message']
        assert 'never the whole call' in result['message']
        assert 'retry the same call' not in result['message']

    @pytest.mark.asyncio
    async def test_a_raised_step_up_has_no_partial_result_and_says_retry_the_call(
        self, remote, mfa_fetch
    ):
        result = await refused_tool(token=JWT)

        assert 'partial_result' not in result
        assert 'retry the same call once with the same arguments' in result['message']

    @pytest.mark.asyncio
    async def test_a_swallowed_step_up_followed_by_an_ordinary_error_is_mfa_required(
        self, remote, mfa_fetch
    ):
        @with_error_handling
        async def tool(workspace='acme', region='ap1', **kwargs):
            await asyncio.gather(_refusing_child(), return_exceptions=True)
            raise RuntimeError('boom')

        result = await tool(token=JWT)

        assert result['status'] == 'mfa_required'
        assert result['partial_result']['status'] == 'error'
        assert 'boom' in result['partial_result']['message']

    @pytest.mark.asyncio
    async def test_a_resend_after_a_step_up_recorded_during_backoff_is_never_sent(
        self, remote, mfa_fetch
    ):
        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ConnectError('refused'))

        async def sibling_refused_while_backing_off(delay: float) -> None:
            mfa_step_up.record('command')

        @with_error_handling
        async def tool(workspace='acme', region='ap1', **kwargs):
            return await http_client.request(
                'POST', 'https://acme.ap1.alpacon.io/api/events/commands/', token=JWT
            )

        with (
            patch.object(
                AlpaconHTTPClient, '_get_client', AsyncMock(return_value=client)
            ),
            patch('utils.http_client.asyncio.sleep', sibling_refused_while_backing_off),
        ):
            result = await tool(token=JWT)

        assert client.request.await_count == 1
        assert result['status'] == 'mfa_required'

    @pytest.mark.asyncio
    async def test_a_request_after_a_recorded_step_up_is_never_sent(self, remote):
        sent = MagicMock(request=AsyncMock())

        @with_error_handling
        async def tool(workspace='acme', region='ap1', **kwargs):
            await asyncio.gather(_refusing_child(), return_exceptions=True)
            return await http_client.request(
                'POST', 'https://acme.ap1.alpacon.io/api/events/commands/', token=JWT
            )

        with (
            patch.object(
                AlpaconHTTPClient, '_get_client', AsyncMock(return_value=sent)
            ),
            patch('utils.decorators.http_client.get', AsyncMock(return_value={})),
        ):
            result = await tool(token=JWT)

        assert result['status'] == 'mfa_required'
        sent.request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_step_up_recorded_during_the_pool_wait_stops_the_request(self):
        received: list[str] = []
        release = asyncio.Event()

        async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            with contextlib.suppress(asyncio.IncompleteReadError):  # client hung up
                while head := await reader.readuntil(b'\r\n\r\n'):
                    path = head.split(b' ', 2)[1].decode()
                    received.append(path)
                    if path == '/slow':
                        await release.wait()
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}')
                    await writer.drain()
            writer.close()  # Server.wait_closed waits for every connection (3.12+)

        server = await asyncio.start_server(serve, '127.0.0.1', 0)
        base = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        one_connection = httpx.AsyncHTTPTransport(
            limits=httpx.Limits(max_connections=1)
        )
        async with server, AlpaconHTTPClient(transport=one_connection) as client:
            with mfa_step_up.tool_call():
                holding = asyncio.create_task(client.request('GET', f'{base}/slow'))
                while not received:
                    await asyncio.sleep(0.01)
                queued = asyncio.create_task(
                    client.request('POST', f'{base}/api/events/commands/')
                )
                await asyncio.sleep(0.05)  # queued now waits for the only connection
                mfa_step_up.record('command')  # a sibling request was refused meanwhile
                release.set()
                await holding
                with pytest.raises(mfa_step_up.MfaStepUpRequired):
                    await queued

        assert received == ['/slow']


async def _refusing_child():
    _refuse()


SERVER_A = '550e8400-e29b-41d4-a716-446655440000'
SERVER_B = '550e8400-e29b-41d4-a716-446655440001'
SERVER_C = '550e8400-e29b-41d4-a716-446655440002'
STEP_UP_BODY = {'code': 'auth_mfa_required', 'source': 'command'}


@contextmanager
def _real_stack(handler: Callable[[httpx.Request], httpx.Response]) -> Iterator[None]:
    """The real client and decorator stack over a MockTransport, in remote JWT mode."""
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    claims = [{'schema_name': 'acme', 'region': 'ap1'}]
    with (
        patch.object(
            AlpaconHTTPClient, '_get_client', AsyncMock(return_value=mock_client)
        ),
        patch.object(
            http_client, 'get_base_url', lambda r, w: f'https://{w}.{r}.alpacon.io'
        ),
        patch('utils.decorators._get_jwt_token', return_value=JWT),
        patch('utils.decorators.get_token_workspaces', return_value=claims),
    ):
        yield


def _answer(request: httpx.Request, refused: set[str]) -> httpx.Response:
    if request.url.path == '/api/auth0/mfa/':
        return httpx.Response(200, json={'mfa_url': LINK})
    server = json.loads(request.content or b'{}').get('server')
    if server in refused:
        return httpx.Response(401, json=STEP_UP_BODY)
    return httpx.Response(201, json={'id': f'cmd-{server}', 'server': server})


class TestRealStack:
    @pytest.mark.asyncio
    async def test_link_fetch_goes_out_after_the_holder_is_released(
        self, remote, caplog
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return _answer(request, refused={SERVER_A})

        with _real_stack(handler), caplog.at_level(logging.DEBUG):
            result = await command_tools.execute_command_multi_server(
                [SERVER_A], 'uptime', 'acme', region='ap1'
            )

        assert result['status'] == 'mfa_required'
        assert result['mfa_url'] == LINK
        assert 'ticket=secret' not in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize('parallel', [False, True], ids=['sequential', 'parallel'])
    async def test_multi_server_keeps_the_success_and_marks_the_refused_server(
        self, remote, parallel
    ):
        posted: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == '/api/events/commands/':
                posted.append(json.loads(request.content)['server'])
            return _answer(request, refused={SERVER_B})

        servers = [SERVER_A, SERVER_B] if parallel else [SERVER_A, SERVER_B, SERVER_C]
        with _real_stack(handler):
            result = await command_tools.execute_command_multi_server(
                servers, 'uptime', 'acme', region='ap1', parallel=parallel
            )

        entries = result['partial_result']['deploy_shell_results']
        assert result['status'] == 'mfa_required'
        assert result['mfa_url'] == LINK
        assert entries[SERVER_A]['status'] == 'success'
        assert entries[SERVER_B]['status'] == 'mfa_required'
        assert 'never the whole call' in result['message']
        if not parallel:
            assert SERVER_C not in posted
            assert entries[SERVER_C]['status'] == 'mfa_required'

    @pytest.mark.asyncio
    async def test_execute_file_refused_at_the_upload_asks_for_the_same_call(
        self, remote
    ):
        sent: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == '/api/auth0/mfa/':
                return httpx.Response(200, json={'mfa_url': LINK})
            sent.append(f'{request.method} {request.url.path}')
            return httpx.Response(401, json=STEP_UP_BODY)

        with _real_stack(handler):
            result = await command_tools.execute_file(
                SERVER_A, '/tmp/run.sh', 'acme', content='echo hi', write_file=True
            )

        assert result['status'] == 'mfa_required'
        assert 'retry the same call once with the same arguments' in result['message']
        assert 'already_sent' not in result
        assert sent == ['POST /api/webftp/uploads/']

    @pytest.mark.asyncio
    async def test_command_refused_while_polling_is_not_resubmitted(self, remote):
        posted: list[str] = []
        link_auth: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == '/api/auth0/mfa/':
                link_auth.append(request.headers.get('authorization'))
                return httpx.Response(200, json={'mfa_url': LINK})
            if request.method == 'POST':
                posted.append(request.url.path)
                return httpx.Response(201, json=[{'id': 'cmd-1', 'server': SERVER_A}])
            return httpx.Response(401, json=STEP_UP_BODY)

        with _real_stack(handler):
            result = await command_tools.execute_command(
                SERVER_A, 'uptime', 'acme', region='ap1'
            )

        assert result['status'] == 'mfa_required'
        assert result['already_sent'] == ['POST /api/events/commands/']
        assert 'never the whole call' in result['message']
        assert 'same arguments' not in result['message']
        assert 'partial_result' not in result
        assert posted == ['/api/events/commands/']
        assert link_auth == [f'Bearer {JWT}']
