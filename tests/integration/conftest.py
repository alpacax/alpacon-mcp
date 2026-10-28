"""Shared fixtures that inject mock HTTP responses at the httpx transport layer.
The full request path runs end to end.
"""

from http import HTTPStatus
from unittest.mock import patch

import httpx
import pytest

from utils.http_client import http_client

SERVER_ID = '550e8400-e29b-41d4-a716-446655440001'
SECOND_SERVER_ID = '550e8400-e29b-41d4-a716-446655440002'


@pytest.fixture
def make_mock_transport():
    """Build an httpx.MockTransport from a handler(httpx.Request) -> httpx.Response."""

    def _factory(handler):
        return httpx.MockTransport(handler)

    return _factory


@pytest.fixture
def patched_http_client(make_mock_transport):
    """Patch AlpaconHTTPClient._get_client to return a MockTransport client.
    Yields a patcher whose set_handler(handler) installs the request handler.
    """

    class _Patcher:
        def __init__(self):
            self._patches = []

        def set_handler(self, handler):
            """Set the mock transport handler for HTTP requests."""
            # Stop any existing patches before starting a new one
            for p in self._patches:
                p.stop()
            self._patches.clear()

            transport = make_mock_transport(handler)
            mock_client = httpx.AsyncClient(transport=transport)

            async def _get_client():
                return mock_client

            patcher = patch.object(http_client, '_get_client', side_effect=_get_client)
            patcher.start()
            self._patches.append(patcher)
            return mock_client

        def cleanup(self):
            for p in self._patches:
                p.stop()

    patcher = _Patcher()
    yield patcher

    # Teardown: stop patches
    patcher.cleanup()


@pytest.fixture
def mock_token_for_integration():
    """Patch utils.common.token_manager so validate_token() returns
    'integration-test-token'.
    """
    with patch('utils.common.token_manager') as mock_tm:
        mock_tm.get_token.return_value = 'integration-test-token'
        yield mock_tm


@pytest.fixture
def sample_api_responses():
    """Factory returning realistic API response payloads, keyed by name.
    E.g. data = sample_api_responses(); data['servers_list'].
    """

    def _factory():
        return {
            'servers_list': {
                'count': 2,
                'next': None,
                'previous': None,
                'results': [
                    {
                        'id': SERVER_ID,
                        'name': 'web-server-01',
                        'ip': '10.0.1.10',
                        'status': 'running',
                        'os': 'Ubuntu 22.04',
                    },
                    {
                        'id': SECOND_SERVER_ID,
                        'name': 'db-server-01',
                        'ip': '10.0.1.11',
                        'status': 'running',
                        'os': 'CentOS 9',
                    },
                ],
            },
            'server_detail': {
                'id': SERVER_ID,
                'name': 'web-server-01',
                'ip': '10.0.1.10',
                'status': 'running',
                'os': 'Ubuntu 22.04',
                'cpu': 4,
                'memory': 8192,
            },
            'server_not_found': {'detail': 'Not found.'},
            'server_note_created': {
                'id': 'note-001',
                'server': SERVER_ID,
                'title': 'Test Note',
                'content': 'Test content',
                'created_at': '2024-06-01T12:00:00Z',
            },
            'iam_users_list': {
                'count': 1,
                'results': [
                    {
                        'id': 'user-001',
                        'username': 'testuser',
                        'email': 'test@example.com',
                        'is_active': True,
                    },
                ],
            },
            'iam_user_created': {
                'id': 'user-002',
                'username': 'newuser',
                'email': 'new@example.com',
                'is_active': True,
            },
            'iam_user_updated': {
                'id': 'user-001',
                'username': 'testuser',
                'email': 'updated@example.com',
                'is_active': True,
            },
            'iam_user_deleted': {
                'status': 'success',
                'status_code': HTTPStatus.NO_CONTENT,
            },
            'events_list': {
                'count': 2,
                'results': [
                    {
                        'id': 'evt-001',
                        'server': SERVER_ID,
                        'reporter': 'system',
                        'record': 'Server started',
                        'added_at': '2024-06-01T12:00:00Z',
                    },
                    {
                        'id': 'evt-002',
                        'server': SERVER_ID,
                        'reporter': 'user',
                        'record': 'Config updated',
                        'added_at': '2024-06-01T13:00:00Z',
                    },
                ],
            },
            'cpu_metrics': {
                'results': [
                    {'usage': 25.5, 'timestamp': '2024-06-01T12:00:00Z'},
                    {'usage': 30.2, 'timestamp': '2024-06-01T12:05:00Z'},
                    {'usage': 45.8, 'timestamp': '2024-06-01T12:10:00Z'},
                ],
            },
        }

    return _factory


@pytest.fixture(autouse=True)
def no_sleep():
    """Autouse: patch asyncio.sleep in http_client so retries run instantly.
    The delays land on mock_sleep.recorded_delays for backoff checks.
    """
    recorded_delays = []

    async def fast_sleep(delay):
        recorded_delays.append(delay)

    with patch('utils.http_client.asyncio.sleep', side_effect=fast_sleep) as mock_sleep:
        mock_sleep.recorded_delays = recorded_delays
        yield mock_sleep
