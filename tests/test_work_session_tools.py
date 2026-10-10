"""Unit tests for work_session_tools module."""

import inspect
from http import HTTPStatus

import pytest

from server import mcp
from tests.conftest import http_client_fixture
from tools.work_session_tools import (
    work_session_analyze,
    work_session_close,
    work_session_create,
    work_session_extend,
    work_session_get,
    work_session_list,
    work_session_timeline,
    work_session_update,
)
from utils import cursor_pagination

mock_http_client = http_client_fixture('tools.work_session_tools')

SERVER_ID = '550e8400-e29b-41d4-a716-446655440001'
SESSION_ID = '550e8400-e29b-41d4-a716-446655440020'
UNKNOWN_SESSION_ID = '550e8400-e29b-41d4-a716-446655440099'


class TestWorkSessionCreate:
    @pytest.mark.asyncio
    async def test_create_success(self, mock_http_client, mock_token_manager):

        # Verifies the request payload sent to the server. Use an active session
        # so the success path is exercised; the pending path is covered by
        # test_create_pending_surfaces_approval_signal.
        mock_http_client.post.return_value = {
            'id': SESSION_ID,
            'status': 'active',
            'auth_method': 'mcp_oauth',
        }

        result = await work_session_create(
            workspace='testworkspace',
            scopes=['command'],
            servers=[SERVER_ID],
            expires_at='2026-05-19T13:00:00+00:00',
            description='Fix nginx config',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == SESSION_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            data={
                'requester_type': 'agent',
                'scopes': ['command'],
                'servers': [SERVER_ID],
                'expires_at': '2026-05-19T13:00:00+00:00',
                'description': 'Fix nginx config',
            },
        )

    @pytest.mark.asyncio
    async def test_create_pending_surfaces_approval_signal(
        self, mock_http_client, mock_token_manager
    ):
        """A pending Work Session is surfaced as a structured approval signal."""

        mock_http_client.post.return_value = {
            'id': 'ws-uuid-pending',
            'status': 'pending',
            'auth_method': 'mcp_oauth',
        }

        result = await work_session_create(
            workspace='testworkspace',
            scopes=['command'],
            servers=[SERVER_ID],
            expires_at='2026-05-19T13:00:00+00:00',
            description='Fix nginx config',
            region='ap1',
        )

        assert result['status'] == 'pending_approval'
        assert result['category'] == 'WORK_SESSION_PENDING'
        assert result['requires_human_approval'] is True
        assert result['approvable_by_agent'] is False
        assert result['session_id'] == 'ws-uuid-pending'
        assert result['data']['status'] == 'pending'
        assert 'out-of-band' in result['next_action']

    @pytest.mark.asyncio
    async def test_create_pending_guidance_reads_data_status_and_names_stop_states(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'ws-uuid-pending',
            'status': 'pending',
            'auth_method': 'mcp_oauth',
        }

        result = await work_session_create(
            workspace='testworkspace',
            scopes=['command'],
            servers=[SERVER_ID],
            expires_at='2026-05-19T13:00:00+00:00',
            description='Fix nginx config',
            region='ap1',
        )

        assert result['status'] == 'pending_approval'
        assert 'data.status' in result['next_action']
        assert 'data.status' in result['message']
        for state in ('rejected', 'cancelled', 'expired', 'revoked', 'completed'):
            assert state in result['next_action']
            assert state in result['message']

    @pytest.mark.asyncio
    async def test_create_active_returns_success(
        self, mock_http_client, mock_token_manager
    ):
        """A non-pending session (e.g. auto-approved) returns a normal success."""

        mock_http_client.post.return_value = {
            'id': 'ws-uuid-active',
            'status': 'active',
        }

        result = await work_session_create(
            workspace='testworkspace',
            scopes=['command'],
            servers=[SERVER_ID],
            expires_at='2026-05-19T13:00:00+00:00',
            description='Fix nginx config',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == 'ws-uuid-active'

    @pytest.mark.asyncio
    async def test_create_with_title_and_description(
        self, mock_http_client, mock_token_manager
    ):

        mock_http_client.post.return_value = {'id': 'ws-uuid-5678', 'status': 'pending'}

        await work_session_create(
            workspace='testworkspace',
            scopes=['command', 'webftp'],
            servers=[SERVER_ID],
            expires_at='2026-05-19T13:00:00+00:00',
            title='Deploy session',
            description='Deploying config files',
            region='ap1',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            data={
                'requester_type': 'agent',
                'scopes': ['command', 'webftp'],
                'servers': [SERVER_ID],
                'expires_at': '2026-05-19T13:00:00+00:00',
                'description': 'Deploying config files',
                'title': 'Deploy session',
            },
        )

    @pytest.mark.asyncio
    async def test_create_omits_empty_title(self, mock_http_client, mock_token_manager):

        mock_http_client.post.return_value = {'id': 'ws-uuid-0000', 'status': 'pending'}

        await work_session_create(
            workspace='testworkspace',
            scopes=['command'],
            servers=[SERVER_ID],
            expires_at='2026-05-19T13:00:00+00:00',
            description='Routine maintenance',
            region='ap1',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            data={
                'requester_type': 'agent',
                'scopes': ['command'],
                'servers': [SERVER_ID],
                'expires_at': '2026-05-19T13:00:00+00:00',
                'description': 'Routine maintenance',
            },
        )


class TestWorkSessionClose:
    @pytest.mark.asyncio
    async def test_close_success(self, mock_http_client, mock_token_manager):

        mock_http_client.post.return_value = {
            'id': SESSION_ID,
            'status': 'completed',
        }

        result = await work_session_close(
            session_id=SESSION_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/work-sessions/sessions/{SESSION_ID}/complete/',
            token='test-token',
            data={},
        )


class TestWorkSessionGet:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_http_client, mock_token_manager):

        mock_http_client.get.return_value = {
            'id': SESSION_ID,
            'status': 'active',
            'requester_type': 'agent',
        }

        result = await work_session_get(
            session_id=SESSION_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == SESSION_ID
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/work-sessions/sessions/{SESSION_ID}/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_propagates_api_error(self, mock_http_client, mock_token_manager):

        mock_http_client.get.return_value = {
            'error': 'Not found',
            'message': 'Work Session not found',
            'status_code': HTTPStatus.NOT_FOUND,
        }

        result = await work_session_get(
            session_id=UNKNOWN_SESSION_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'Work Session not found' in result['message']


class TestWorkSessionList:
    @pytest.mark.asyncio
    async def test_list_success(self, mock_http_client, mock_token_manager):

        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'ws-1', 'status': 'active'},
                {'id': 'ws-2', 'status': 'completed'},
            ],
        }

        result = await work_session_list(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            params={'page_size': 20},
        )

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, mock_http_client, mock_token_manager):

        mock_http_client.get.return_value = {'count': 1, 'results': []}

        await work_session_list(
            workspace='testworkspace', status='active', region='ap1'
        )

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            params={'page_size': 20, 'status': 'active'},
        )

    @pytest.mark.asyncio
    async def test_list_with_requester_type_filter(
        self, mock_http_client, mock_token_manager
    ):

        mock_http_client.get.return_value = {'count': 1, 'results': []}

        await work_session_list(
            workspace='testworkspace', requester_type='agent', region='ap1'
        )

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            params={'page_size': 20, 'requester_type': 'agent'},
        )

    @pytest.mark.asyncio
    async def test_list_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):

        mock_http_client.get.return_value = {
            'error': 'Forbidden',
            'message': 'Permission denied',
            'status_code': HTTPStatus.FORBIDDEN,
        }

        result = await work_session_list(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert 'Permission denied' in result['message']


class TestWorkSessionUpdate:
    @pytest.mark.asyncio
    async def test_update_success(self, mock_http_client, mock_token_manager):

        # Applied immediately: no modification request was queued.
        mock_http_client.patch.return_value = {
            'id': SESSION_ID,
            'status': 'pending',
            'description': 'Updated intent',
            'pending_modification_request': None,
        }

        result = await work_session_update(
            session_id=SESSION_ID,
            workspace='testworkspace',
            title='New title',
            description='Updated intent',
            scopes=['command', 'webftp'],
            servers=[SERVER_ID],
            expires_at='2026-06-06T13:00:00+00:00',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/work-sessions/sessions/{SESSION_ID}/',
            token='test-token',
            data={
                'title': 'New title',
                'description': 'Updated intent',
                'scopes': ['command', 'webftp'],
                'servers': [SERVER_ID],
                'expires_at': '2026-06-06T13:00:00+00:00',
            },
        )

    @pytest.mark.asyncio
    async def test_update_sends_only_provided_fields(
        self, mock_http_client, mock_token_manager
    ):

        mock_http_client.patch.return_value = {'id': SESSION_ID}

        await work_session_update(
            session_id=SESSION_ID,
            workspace='testworkspace',
            description='Only description changed',
            region='ap1',
        )

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/work-sessions/sessions/{SESSION_ID}/',
            token='test-token',
            data={'description': 'Only description changed'},
        )

    @pytest.mark.asyncio
    async def test_update_rejects_empty_update(
        self, mock_http_client, mock_token_manager
    ):

        result = await work_session_update(
            session_id=SESSION_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'No fields to update' in result['message']
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_sends_empty_title_to_clear(
        self, mock_http_client, mock_token_manager
    ):
        """An explicit empty string is sent so the server clears the title."""

        mock_http_client.patch.return_value = {
            'id': SESSION_ID,
            'pending_modification_request': None,
        }

        await work_session_update(
            session_id=SESSION_ID,
            workspace='testworkspace',
            title='',
            region='ap1',
        )

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/work-sessions/sessions/{SESSION_ID}/',
            token='test-token',
            data={'title': ''},
        )

    @pytest.mark.asyncio
    async def test_update_queued_modification_surfaces_approval_signal(
        self, mock_http_client, mock_token_manager
    ):
        """A queued modification (server HTTP 202) is surfaced as pending approval.

        Scope/server changes on an approved/active session are not applied
        immediately—the server queues a ``work_session_mod`` approval request
        and reports it via a non-null ``pending_modification_request``.
        """

        mock_http_client.patch.return_value = {
            'id': SESSION_ID,
            'status': 'active',
            'scopes': ['command'],
            'pending_modification_request': {
                'id': 'mod-req-uuid-1',
                'changes': {'scopes': ['command', 'sudo']},
                'added_at': '2026-06-12T10:00:00+00:00',
            },
        }

        result = await work_session_update(
            session_id=SESSION_ID,
            workspace='testworkspace',
            scopes=['command', 'sudo'],
            region='ap1',
        )

        assert result['status'] == 'pending_approval'
        assert result['category'] == 'WORK_SESSION_MOD_PENDING'
        assert result['requires_human_approval'] is True
        assert result['approvable_by_agent'] is False
        assert result['session_id'] == SESSION_ID
        assert result['data']['pending_modification_request']['id'] == 'mod-req-uuid-1'

    @pytest.mark.asyncio
    async def test_update_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):

        mock_http_client.patch.return_value = {
            'error': 'Validation error',
            'message': 'Work session is not modifiable',
            'status_code': HTTPStatus.BAD_REQUEST,
        }

        result = await work_session_update(
            session_id=SESSION_ID,
            workspace='testworkspace',
            description='Too late',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'not modifiable' in result['message']


class TestWorkSessionExtend:
    @pytest.mark.asyncio
    async def test_extend_success(self, mock_http_client, mock_token_manager):

        # Applied immediately: no extension request was queued.
        mock_http_client.post.return_value = {
            'id': SESSION_ID,
            'status': 'active',
            'expires_at': '2026-06-06T18:00:00+00:00',
            'pending_extension_request': None,
        }

        result = await work_session_extend(
            session_id=SESSION_ID,
            workspace='testworkspace',
            expires_at='2026-06-06T18:00:00+00:00',
            reason='Customer escalation, still triaging',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/work-sessions/sessions/{SESSION_ID}/extend/',
            token='test-token',
            data={
                'expires_at': '2026-06-06T18:00:00+00:00',
                'reason': 'Customer escalation, still triaging',
            },
        )

    @pytest.mark.asyncio
    async def test_extend_without_reason_is_a_type_error(
        self, mock_http_client, mock_token_manager
    ):
        """reason is a required parameter; omitting it never reaches the server."""
        with pytest.raises(TypeError):
            await work_session_extend(
                session_id=SESSION_ID,
                workspace='testworkspace',
                expires_at='2026-06-06T18:00:00+00:00',
            )

    @pytest.mark.asyncio
    async def test_extend_queued_surfaces_approval_signal(
        self, mock_http_client, mock_token_manager
    ):
        """A queued extension (server HTTP 202) is surfaced as pending approval.

        An extension on a lane other than auto-approve is not applied
        immediately—the server queues a ``work_session_mod`` approval request
        and reports it via a non-null ``pending_extension_request``.
        """

        mock_http_client.post.return_value = {
            'id': SESSION_ID,
            'status': 'active',
            'expires_at': '2026-06-05T00:00:00+00:00',
            'pending_extension_request': {
                'id': 'ext-req-uuid-1',
                'requested_expires_at': '2026-06-06T18:00:00+00:00',
                'expires_at': '2026-06-05T12:00:00+00:00',
                'reason': 'Customer escalation, still triaging',
                'added_at': '2026-06-05T00:05:00+00:00',
            },
        }

        result = await work_session_extend(
            session_id=SESSION_ID,
            workspace='testworkspace',
            expires_at='2026-06-06T18:00:00+00:00',
            reason='Customer escalation, still triaging',
            region='ap1',
        )

        assert result['status'] == 'pending_approval'
        assert result['category'] == 'WORK_SESSION_EXTENSION_PENDING'
        assert result['requires_human_approval'] is True
        assert result['approvable_by_agent'] is False
        assert result['session_id'] == SESSION_ID
        assert result['data']['pending_extension_request']['id'] == 'ext-req-uuid-1'
        assert 'work_session_get' in result['next_action']
        assert 'expires_at' in result['next_action']

    @pytest.mark.asyncio
    async def test_extend_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):

        mock_http_client.post.return_value = {
            'error': 'Validation error',
            'message': 'New expiry must be later than current expiry',
            'status_code': HTTPStatus.BAD_REQUEST,
        }

        result = await work_session_extend(
            session_id=SESSION_ID,
            workspace='testworkspace',
            expires_at='2026-06-05T00:00:00+00:00',
            reason='Customer escalation, still triaging',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'later than current' in result['message']

    @pytest.mark.asyncio
    async def test_extend_missing_reason_error_code_mapped(
        self, mock_http_client, mock_token_manager
    ):
        """The server's reason-required refusal comes back with an actionable hint.

        Only reachable when reason is supplied but blank/whitespace—the tool's
        own required parameter stops an omitted reason before any request.
        """

        mock_http_client.post.return_value = {
            'error': 'Bad Request',
            'response': '{"code": "work_session_extension_reason_required"}',
            'status_code': HTTPStatus.BAD_REQUEST,
        }

        result = await work_session_extend(
            session_id=SESSION_ID,
            workspace='testworkspace',
            expires_at='2026-06-06T18:00:00+00:00',
            reason='   ',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'work_session_extension_reason_required'
        assert 'reason must not be blank' in result['message']


TIMELINE_ENDPOINT = f'/api/work-sessions/sessions/{SESSION_ID}/timeline/'


def _timeline_page(items, next_cursor=None):
    """The envelope the timeline paginator returns: `results` and `next`, no count."""
    return {'next': next_cursor, 'results': items}


class TestWorkSessionTimeline:
    """The timeline is paginated only on request, and then only forward (#325).

    Naming neither `cursor` nor `page_size` makes alpacon-server render the
    whole session in one response, so the tool names `page_size` on every
    request and walks the cursor from there, bounded and with the bound stated.
    """

    @pytest.fixture
    def max_pages(self, monkeypatch):
        """Lower the request bound for one test: `max_pages(n)`."""
        return lambda n: monkeypatch.setattr(cursor_pagination, 'MAX_CURSOR_PAGES', n)

    @pytest.mark.asyncio
    async def test_every_request_names_page_size_so_the_server_paginates(
        self, mock_http_client, mock_token_manager
    ):
        """Without it the server answers with the whole session, unbounded.

        That response also carries no `next`, so nothing downstream could tell
        a complete timeline from a truncated one.
        """
        mock_http_client.get.return_value = _timeline_page(
            [{'type': 'command', 'added_at': '2026-06-05T10:00:00+00:00'}]
        )

        result = await work_session_timeline(
            session_id=SESSION_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=TIMELINE_ENDPOINT,
            token='test-token',
            params={'page_size': 100},
        )

    @pytest.mark.asyncio
    async def test_follows_the_cursor_and_merges_the_pages(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.side_effect = [
            _timeline_page([{'type': 'command'}], next_cursor='c1'),
            _timeline_page([{'type': 'sudo_grant'}]),
        ]

        result = await work_session_timeline(
            session_id=SESSION_ID, workspace='testworkspace', region='ap1'
        )

        assert result['data']['results'] == [
            {'type': 'command'},
            {'type': 'sudo_grant'},
        ]
        assert result['pagination']['complete'] is True
        sent = [call.kwargs['params'] for call in mock_http_client.get.await_args_list]
        assert sent == [{'page_size': 100}, {'page_size': 100, 'cursor': 'c1'}]

    @pytest.mark.asyncio
    async def test_a_truncated_timeline_says_so_in_the_result(
        self, mock_http_client, mock_token_manager, max_pages
    ):
        """The whole point of the walk: a cut timeline is never served silently.

        A model reading this result has to be able to tell it from a short
        session, so the bound is stated, not left to be inferred from absence.
        """
        max_pages(2)
        mock_http_client.get.side_effect = [
            _timeline_page([{'type': 'command'}], next_cursor='c1'),
            _timeline_page([{'type': 'command'}], next_cursor='c2'),
        ]

        result = await work_session_timeline(
            session_id=SESSION_ID, workspace='testworkspace', region='ap1'
        )

        report = result['pagination']
        assert report['complete'] is False
        assert report['stopped_because'] == 'page_bound'
        assert report['next_cursor'] == 'c2'
        assert report['pages_read'] == 2
        assert 'incomplete' in report['note']

    @pytest.mark.asyncio
    async def test_the_bound_note_names_the_timelines_own_page_size_ceiling(
        self, mock_http_client, mock_token_manager, max_pages
    ):
        """500, not the 100 the Elasticsearch-backed lists stop at.

        The note tells a caller to raise `page_size` to reach further, and this
        endpoint reaches five times as far as that advice would suggest.
        """
        max_pages(1)
        mock_http_client.get.return_value = _timeline_page(
            [{'type': 'command'}], next_cursor='c1'
        )

        result = await work_session_timeline(
            session_id=SESSION_ID, workspace='testworkspace', region='ap1'
        )

        assert 'max 500' in result['pagination']['note']

    @pytest.mark.asyncio
    async def test_a_supplied_cursor_resumes_the_walk(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = _timeline_page([])

        result = await work_session_timeline(
            session_id=SESSION_ID,
            workspace='testworkspace',
            region='ap1',
            cursor='resume-me',
            page_size=500,
        )

        assert result['pagination']['started_from_cursor'] is True
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=TIMELINE_ENDPOINT,
            token='test-token',
            params={'page_size': 500, 'cursor': 'resume-me'},
        )

    def test_the_tool_offers_cursor_and_page_size(self):
        params = inspect.signature(work_session_timeline).parameters

        assert 'cursor' in params
        assert 'page_size' in params

    @pytest.mark.parametrize('value', [True, False])
    @pytest.mark.asyncio
    async def test_include_records_is_refused_not_dropped(
        self, value, mock_http_client, mock_token_manager
    ):
        """Retired, and refused loudly, because dropping it reads as success.

        The paged shape carries no recording bytes, so the argument cannot be
        honoured. Answering a request for recordings with a timeline that has
        none, and saying nothing, is the defect this tool was changed to stop
        making—only moved up a layer. `False` is refused too: it is a caller
        written against a contract that no longer exists, and one rule is
        easier to rely on than an argument that behaves two ways.
        """
        result = await work_session_timeline(
            session_id=SESSION_ID,
            workspace='testworkspace',
            region='ap1',
            include_records=value,
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'include_records'
        assert 'record route' in result['suggestion']
        mock_http_client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_include_records_is_declared_so_the_sdk_cannot_drop_it(self):
        """The refusal only works because the published schema names it.

        The SDK validates a call against that schema and silently discards
        whatever it does not name (pinned by
        `test_call_tool_takes_the_documented_arguments_alone`), so an
        undeclared `include_records` would never reach the body to be refused.
        This asserts on the schema a client actually reads, not the Python
        signature, since the schema is what decides whether the value survives
        the trip.
        """
        schemas = {t.name: t.input_schema for t in await mcp.list_tools()}

        assert 'include_records' in schemas['work_session_timeline']['properties']

    @pytest.mark.asyncio
    async def test_include_records_is_refused_through_the_sdk_too(
        self, mock_http_client, mock_token_manager
    ):
        """The path a client takes, where the silent drop was invisible.

        A direct Python call raised a TypeError on an unknown argument while
        INFO was on, which made the hole look narrower than it was; through
        the SDK it was dropped at every log level, so the composition is what
        needs pinning, not the function.
        """
        result = await mcp.call_tool(
            'work_session_timeline',
            {
                'session_id': SESSION_ID,
                'workspace': 'testworkspace',
                'region': 'ap1',
                'include_records': True,
            },
        )

        payload = result.structured_content
        assert payload['status'] == 'error'
        assert payload['field'] == 'include_records'
        mock_http_client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_description_tells_the_model_to_check_completeness(self):
        descriptions = {t.name: t.description for t in await mcp.list_tools()}

        text = descriptions['work_session_timeline']

        assert 'pagination.complete' in text
        assert 'unified chronological' not in text

    @pytest.mark.asyncio
    async def test_a_server_that_does_not_paginate_answers_the_whole_session(
        self, mock_http_client, mock_token_manager
    ):
        """Every alpacon-server released so far ignores `page_size` here.

        It answers `{"results": [...]}` with no `next`, and that body really is
        the whole session, so it is reported complete rather than refused. The
        completeness claim only becomes false once the server paginates, and
        erroring would leave this tool dead on today's servers until each user
        upgrades both sides.
        """
        mock_http_client.get.return_value = {'results': [{'type': 'command'}]}

        result = await work_session_timeline(
            session_id=SESSION_ID, workspace='testworkspace', region='ap1'
        )

        report = result['pagination']
        assert result['status'] == 'success'
        assert result['data']['results'] == [{'type': 'command'}]
        assert report['complete'] is True
        assert report['stopped_because'] == 'unpaginated_server'
        assert report['next_cursor'] is None
        assert 'incomplete' not in report['note']

    @pytest.mark.asyncio
    async def test_an_unpaginated_answer_is_told_apart_from_an_exhausted_walk(
        self, mock_http_client, mock_token_manager
    ):
        """Both are complete, but only one of them was ever paginated.

        A reader that cannot tell them apart cannot tell whether the bound was
        in play at all, which is the question `page_size` was sent to settle.
        """
        mock_http_client.get.return_value = {'next': None, 'results': []}

        paginated = await work_session_timeline(
            session_id=SESSION_ID, workspace='testworkspace', region='ap1'
        )

        assert paginated['pagination']['complete'] is True
        assert paginated['pagination']['stopped_because'] == 'end_of_list'
        assert 'note' not in paginated['pagination']

    @pytest.mark.asyncio
    async def test_a_body_with_no_results_is_still_an_error(
        self, mock_http_client, mock_token_manager
    ):
        """The relaxation is `next` alone: an unreadable body stays unreadable."""
        mock_http_client.get.return_value = {'next': None}

        result = await work_session_timeline(
            session_id=SESSION_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert 'results' in result['message']
        assert 'data' not in result

    @pytest.mark.asyncio
    async def test_timeline_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):

        mock_http_client.get.return_value = {
            'error': 'Not found',
            'message': 'Work Session not found',
            'status_code': HTTPStatus.NOT_FOUND,
        }

        result = await work_session_timeline(
            session_id=UNKNOWN_SESSION_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'not found' in result['message'].lower()
        assert result['pagination']['pages_read'] == 0


class TestWorkSessionAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_success(self, mock_http_client, mock_token_manager):

        mock_http_client.post.return_value = {
            'status': 'accepted',
            'work_session': SESSION_ID,
        }

        result = await work_session_analyze(
            session_id=SESSION_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/work-sessions/sessions/{SESSION_ID}/analyze/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_analyze_with_force(self, mock_http_client, mock_token_manager):

        mock_http_client.post.return_value = {
            'status': 'accepted',
            'work_session': SESSION_ID,
        }

        await work_session_analyze(
            session_id=SESSION_ID,
            workspace='testworkspace',
            force=True,
            region='ap1',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/work-sessions/sessions/{SESSION_ID}/analyze/',
            token='test-token',
            data={},
            params={'force': 'true'},
        )

    @pytest.mark.asyncio
    async def test_analyze_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):

        mock_http_client.post.return_value = {
            'error': 'Validation error',
            'message': 'Work session is not in a terminal state',
            'status_code': HTTPStatus.BAD_REQUEST,
        }

        result = await work_session_analyze(
            session_id=SESSION_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'terminal state' in result['message']


class TestDescriptionIsNotAnExecutionChannel:
    """Agents have pasted the commands they meant to run into `description`;
    the schema has to say outright that nothing there is executed.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'tool_name', ['work_session_create', 'work_session_update']
    )
    async def test_description_field_is_declared_non_executable(self, tool_name):
        descriptions = {t.name: t.description for t in await mcp.list_tools()}
        text = descriptions[tool_name]
        assert 'NOT a command list' in text
        assert 'nothing in it is executed' in text

    @pytest.mark.asyncio
    async def test_create_description_names_work_session_id_pending_approval_and_stop_states(
        self,
    ):
        descriptions = {t.name: t.description for t in await mcp.list_tools()}

        text = descriptions['work_session_create']

        assert 'work_session_id' in text
        assert 'pending_approval' in text
        assert 'data.status' in text
        for state in ('rejected', 'cancelled', 'expired', 'revoked', 'completed'):
            assert state in text
        assert 'pass session_id' not in text


class TestWorkSessionListParams:
    WORK_SESSION_LIST_CASES = [
        pytest.param(
            {'status': 'active', 'requester_type': 'agent', 'limit': 5},
            {'page_size': 5, 'status': 'active', 'requester_type': 'agent'},
            id='all_filters',
        ),
        pytest.param(
            {'status': ''}, {'page_size': 20, 'status': ''}, id='blank_status_forwarded'
        ),
        pytest.param(
            {'requester_type': ''},
            {'page_size': 20, 'requester_type': ''},
            id='blank_requester_type_forwarded',
        ),
    ]

    @pytest.mark.parametrize(
        ('tool_kwargs', 'expected_params'), WORK_SESSION_LIST_CASES
    )
    @pytest.mark.asyncio
    async def test_params(
        self, tool_kwargs, expected_params, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await work_session_list(
            workspace='testworkspace', region='ap1', **tool_kwargs
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            params=expected_params,
        )
