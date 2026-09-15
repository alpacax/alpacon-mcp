"""
Unit tests for events_tools module.

Tests event management functionality including event listing,
event retrieval, and event search.
"""

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE, http_client_fixture
from tools.events_tools import get_event, list_events, search_events

mock_http_client = http_client_fixture('tools.events_tools')

SERVER_ID = '550e8400-e29b-41d4-a716-446655440001'


class TestListEvents:
    """Test list_events function."""

    @pytest.mark.asyncio
    async def test_list_events_success(self, mock_http_client, mock_token_manager):
        """Test successful events listing."""

        # Mock successful response
        mock_http_client.get.return_value = {
            'count': 3,
            'results': [
                {
                    'id': 'event-123',
                    'server': '550e8400-e29b-41d4-a716-446655440001',
                    'reporter': 'system',
                    'record': 'service_started',
                    'description': 'Apache service started',
                    'added_at': '2024-01-01T00:00:00Z',
                },
                {
                    'id': 'event-124',
                    'server': '550e8400-e29b-41d4-a716-446655440001',
                    'reporter': 'user',
                    'record': 'command_executed',
                    'description': 'ls -la executed',
                    'added_at': '2024-01-01T00:01:00Z',
                },
                {
                    'id': 'event-125',
                    'server': '550e8400-e29b-41d4-a716-446655440002',
                    'reporter': 'system',
                    'record': 'disk_warning',
                    'description': 'Disk usage above 80%',
                    'added_at': '2024-01-01T00:02:00Z',
                },
            ],
        }

        result = await list_events(
            workspace='testworkspace',
            server_id='550e8400-e29b-41d4-a716-446655440001',
            reporter='system',
            limit=25,
            region='ap1',
        )

        # Verify response structure
        assert result['status'] == 'success'
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'
        assert result['reporter'] == 'system'
        assert result['limit'] == 25
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result
        assert result['data']['count'] == 3

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/events/',
            token='test-token',
            params={
                'page_size': 25,
                'ordering': '-added_at',
                'server': '550e8400-e29b-41d4-a716-446655440001',
                'reporter': 'system',
            },
        )

    @pytest.mark.asyncio
    async def test_list_events_minimal_params(
        self, mock_http_client, mock_token_manager
    ):
        """Test events listing with minimal parameters."""

        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_events(workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['server_id'] is None
        assert result['reporter'] is None
        assert result['limit'] == 50  # Default value

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/events/',
            token='test-token',
            params={'page_size': 50, 'ordering': '-added_at'},
        )

    @pytest.mark.asyncio
    async def test_list_events_no_token(self, mock_http_client, mock_token_manager):
        """Test events listing when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await list_events(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_events_error_envelope(
        self, mock_http_client, mock_token_manager
    ):
        """Test events listing surfaces http_client error envelope as error."""

        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await list_events(workspace='testworkspace')

        assert result['status'] == 'error'


class TestGetEvent:
    """Test get_event function."""

    @pytest.mark.asyncio
    async def test_get_event_success(self, mock_http_client, mock_token_manager):
        """Test successful event details retrieval."""

        # Mock successful response
        mock_http_client.get.return_value = {
            'id': 'event-123',
            'server': '550e8400-e29b-41d4-a716-446655440001',
            'server_name': 'web-server-1',
            'reporter': 'system',
            'record': 'service_started',
            'description': 'Apache service started successfully',
            'added_at': '2024-01-01T00:00:00Z',
            'details': {'service': 'apache2', 'pid': 1234, 'status': 'active'},
        }

        result = await get_event(
            event_id='event-123', workspace='testworkspace', region='ap1'
        )

        # Verify response structure
        assert result['status'] == 'success'
        assert result['event_id'] == 'event-123'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result
        assert result['data']['id'] == 'event-123'

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/events/event-123/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_event_no_token(self, mock_http_client, mock_token_manager):
        """Test event retrieval when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await get_event(event_id='event-123', workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_event_error_envelope(self, mock_http_client, mock_token_manager):
        """Test event retrieval surfaces http_client error envelope as error."""

        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_event(event_id='event-123', workspace='testworkspace')

        assert result['status'] == 'error'


class TestSearchEvents:
    """Test search_events function."""

    @pytest.mark.asyncio
    async def test_search_events_success(self, mock_http_client, mock_token_manager):
        """Test successful event search."""

        # Mock successful response
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {
                    'id': 'event-123',
                    'server': '550e8400-e29b-41d4-a716-446655440001',
                    'reporter': 'system',
                    'record': 'service_error',
                    'description': 'Apache service error: connection refused',
                    'added_at': '2024-01-01T00:00:00Z',
                },
                {
                    'id': 'event-124',
                    'server': '550e8400-e29b-41d4-a716-446655440002',
                    'reporter': 'user',
                    'record': 'command_error',
                    'description': 'Command failed: apache2 restart',
                    'added_at': '2024-01-01T00:01:00Z',
                },
            ],
        }

        result = await search_events(
            search_query='apache',
            workspace='testworkspace',
            server_id='550e8400-e29b-41d4-a716-446655440001',
            limit=10,
            region='ap1',
        )

        # Verify response structure
        assert result['status'] == 'success'
        assert result['search_query'] == 'apache'
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'
        assert result['limit'] == 10
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result
        assert result['data']['count'] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/events/',
            token='test-token',
            params={
                'search': 'apache',
                'page_size': 10,
                'ordering': '-added_at',
                'server': '550e8400-e29b-41d4-a716-446655440001',
            },
        )

    @pytest.mark.asyncio
    async def test_search_events_minimal_params(
        self, mock_http_client, mock_token_manager
    ):
        """Test event search with minimal parameters."""

        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await search_events(search_query='error', workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['search_query'] == 'error'
        assert result['server_id'] is None
        assert result['limit'] == 20  # Default value

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/events/',
            token='test-token',
            params={'search': 'error', 'page_size': 20, 'ordering': '-added_at'},
        )

    @pytest.mark.asyncio
    async def test_search_events_no_results(self, mock_http_client, mock_token_manager):
        """Test event search with no results."""

        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await search_events(
            search_query='nonexistent', workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert result['data']['count'] == 0
        assert result['data']['results'] == []

    @pytest.mark.asyncio
    async def test_search_events_no_token(self, mock_http_client, mock_token_manager):
        """Test event search when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await search_events(search_query='test', workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']

    @pytest.mark.asyncio
    async def test_search_events_error_envelope(
        self, mock_http_client, mock_token_manager
    ):
        """Test event search surfaces http_client error envelope as error."""

        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await search_events(search_query='test', workspace='testworkspace')

        assert result['status'] == 'error'


class TestListEventsParams:
    LIST_EVENTS_CASES = [
        pytest.param({}, {'page_size': 50, 'ordering': '-added_at'}, id='no_filters'),
        pytest.param(
            {'server_id': SERVER_ID},
            {'page_size': 50, 'ordering': '-added_at', 'server': SERVER_ID},
            id='server_only',
        ),
        pytest.param(
            {'reporter': 'system'},
            {'page_size': 50, 'ordering': '-added_at', 'reporter': 'system'},
            id='reporter_only',
        ),
        pytest.param(
            {'limit': 25},
            {'page_size': 25, 'ordering': '-added_at'},
            id='limit_override',
        ),
        pytest.param(
            {'server_id': SERVER_ID, 'reporter': 'system', 'limit': 25},
            {
                'page_size': 25,
                'ordering': '-added_at',
                'server': SERVER_ID,
                'reporter': 'system',
            },
            id='all_filters',
        ),
        pytest.param(
            {'reporter': ''},
            {'page_size': 50, 'ordering': '-added_at', 'reporter': ''},
            id='blank_reporter_forwarded',
        ),
    ]

    @pytest.mark.parametrize(('tool_kwargs', 'expected_params'), LIST_EVENTS_CASES)
    @pytest.mark.asyncio
    async def test_params(
        self, tool_kwargs, expected_params, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await list_events(
            workspace='testworkspace', region='ap1', **tool_kwargs
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/events/',
            token='test-token',
            params=expected_params,
        )


class TestSearchEventsParams:
    SEARCH_EVENTS_CASES = [
        pytest.param(
            {},
            {'search': 'error', 'page_size': 20, 'ordering': '-added_at'},
            id='no_filters',
        ),
        pytest.param(
            {'server_id': SERVER_ID},
            {
                'search': 'error',
                'page_size': 20,
                'ordering': '-added_at',
                'server': SERVER_ID,
            },
            id='server_only',
        ),
        pytest.param(
            {'limit': 5},
            {'search': 'error', 'page_size': 5, 'ordering': '-added_at'},
            id='limit_override',
        ),
    ]

    @pytest.mark.parametrize(('tool_kwargs', 'expected_params'), SEARCH_EVENTS_CASES)
    @pytest.mark.asyncio
    async def test_params(
        self, tool_kwargs, expected_params, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await search_events(
            search_query='error',
            workspace='testworkspace',
            region='ap1',
            **tool_kwargs,
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/events/',
            token='test-token',
            params=expected_params,
        )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
