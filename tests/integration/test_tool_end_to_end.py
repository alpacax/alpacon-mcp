"""End-to-end integration tests for MCP tool functions.

Tests tool functions from call through the full decorator chain, HTTP client,
MockTransport, and back to response parsing. Verifies that realistic API
payloads produce correct success/error responses.
"""

import json

import httpx
import pytest

from tools.events_tools import list_events
from tools.iam_tools import (
    create_iam_user,
    delete_iam_user,
    list_iam_users,
    update_iam_user,
)
from tools.metrics_tools import get_cpu_usage
from tools.server_tools import (
    create_server_note,
    get_server,
    list_servers,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SERVER_UUID = '550e8400-e29b-41d4-a716-446655440001'


class TestServerToolsEndToEnd:
    """End-to-end tests for server management tools."""

    async def test_list_servers(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """list_servers returns paginated server list through full path."""
        api_data = sample_api_responses()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=api_data['servers_list'])

        patched_http_client.set_handler(handler)

        result = await list_servers(workspace='production', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        assert len(result['data']['results']) == 2
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'production'

    async def test_get_server_found(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """get_server returns server details when found."""
        api_data = sample_api_responses()

        def handler(request: httpx.Request) -> httpx.Response:
            # Verify the request has the server ID filter
            assert 'id' in str(request.url)
            return httpx.Response(200, json=api_data['server_detail'])

        patched_http_client.set_handler(handler)

        result = await get_server(
            server_id=SERVER_UUID, workspace='production', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['name'] == 'web-server-01'
        assert result['server_id'] == SERVER_UUID

    async def test_get_server_not_found(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """get_server returns error when server not found."""
        api_data = sample_api_responses()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=api_data['server_not_found'])

        patched_http_client.set_handler(handler)

        result = await get_server(
            server_id='99999999-9999-9999-9999-999999999999',
            workspace='production',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'Server not found' in result['message']

    async def test_create_server_note_post_body(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """create_server_note sends correct POST body and returns success."""
        api_data = sample_api_responses()
        captured_body = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured_body.update(body)
            return httpx.Response(201, json=api_data['server_note_created'])

        patched_http_client.set_handler(handler)

        result = await create_server_note(
            server_id=SERVER_UUID,
            title='Test Note',
            content='Test content',
            workspace='production',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == 'note-001'

        # Verify the POST body
        assert captured_body['server'] == SERVER_UUID
        assert captured_body['title'] == 'Test Note'
        assert captured_body['content'] == 'Test content'


class TestIAMToolsEndToEnd:
    """End-to-end tests for IAM CRUD operations."""

    async def test_list_iam_users(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """list_iam_users returns user list through full path."""
        api_data = sample_api_responses()

        def handler(request: httpx.Request) -> httpx.Response:
            assert '/api/iam/users/' in str(request.url)
            return httpx.Response(200, json=api_data['iam_users_list'])

        patched_http_client.set_handler(handler)

        result = await list_iam_users(workspace='production', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 1
        assert result['data']['results'][0]['username'] == 'testuser'

    async def test_create_iam_user(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """create_iam_user sends correct POST and returns created user."""
        api_data = sample_api_responses()
        captured_body = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured_body.update(body)
            return httpx.Response(201, json=api_data['iam_user_created'])

        patched_http_client.set_handler(handler)

        result = await create_iam_user(
            username='newuser',
            email='new@example.com',
            workspace='production',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['username'] == 'newuser'
        assert captured_body['username'] == 'newuser'
        assert captured_body['email'] == 'new@example.com'

    async def test_update_iam_user(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """update_iam_user sends PATCH with only changed fields."""
        api_data = sample_api_responses()
        captured_body = {}
        captured_method = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_method.append(request.method)
            body = json.loads(request.content)
            captured_body.update(body)
            return httpx.Response(200, json=api_data['iam_user_updated'])

        patched_http_client.set_handler(handler)

        result = await update_iam_user(
            user_id='user-001',
            workspace='production',
            email='updated@example.com',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['email'] == 'updated@example.com'
        assert captured_method[0] == 'PATCH'
        assert captured_body == {'email': 'updated@example.com'}

    async def test_delete_iam_user(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """delete_iam_user sends DELETE and returns success."""
        captured_method = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_method.append(request.method)
            assert '/api/iam/users/user-001/' in str(request.url)
            return httpx.Response(204, text='')

        patched_http_client.set_handler(handler)

        result = await delete_iam_user(
            user_id='user-001', workspace='production', region='ap1'
        )

        assert result['status'] == 'success'
        assert captured_method[0] == 'DELETE'


class TestEventsEndToEnd:
    """End-to-end tests for events tools."""

    async def test_list_events(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """list_events returns event list with correct parameters."""
        api_data = sample_api_responses()
        captured_params = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.update(dict(request.url.params))
            return httpx.Response(200, json=api_data['events_list'])

        patched_http_client.set_handler(handler)

        result = await list_events(workspace='production', region='ap1', limit=50)

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        assert captured_params.get('page_size') == '50'
        assert captured_params.get('ordering') == '-added_at'


class TestMetricsEndToEnd:
    """End-to-end tests for metrics tools with metric parsing."""

    async def test_get_cpu_usage_with_parsing(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """get_cpu_usage returns parsed CPU metrics through full path."""
        api_data = sample_api_responses()

        def handler(request: httpx.Request) -> httpx.Response:
            assert '/api/metrics/realtime/cpu/' in str(request.url)
            return httpx.Response(200, json=api_data['cpu_metrics'])

        patched_http_client.set_handler(handler)

        result = await get_cpu_usage(
            server_id=SERVER_UUID,
            workspace='production',
            start_date='2024-06-01T00:00:00Z',
            end_date='2024-06-02T00:00:00Z',
            region='ap1',
        )

        assert result['status'] == 'success'
        stats = result['data']['statistics']
        assert stats['available'] is True
        assert stats['data_points'] == 3
        # Verify parsed values from the sample data: [25.5, 30.2, 45.8]
        assert stats['raw_values']['current'] == 45.8
        assert stats['raw_values']['min'] == 25.5
        assert stats['raw_values']['max'] == 45.8
        assert stats['status'] == 'low'  # 45.8 < 50 falls in 'low' range
