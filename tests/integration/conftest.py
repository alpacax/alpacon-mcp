"""Shared fixtures for integration tests.

Provides MockTransport-based fixtures that inject mock HTTP responses at the
httpx transport layer, letting the full request path execute end-to-end.
"""

from unittest.mock import patch

import httpx
import pytest

from utils.http_client import http_client


@pytest.fixture
def make_mock_transport():
    """Factory to create httpx.MockTransport with a custom handler.

    The handler receives an httpx.Request and must return an httpx.Response.

    Usage:
        transport = make_mock_transport(my_handler)
    """

    def _factory(handler):
        return httpx.MockTransport(handler)

    return _factory


@pytest.fixture
def patched_http_client(make_mock_transport):
    """Patch AlpaconHTTPClient._get_client to return a client with MockTransport.

    Yields a helper that accepts a handler function. The handler receives
    an httpx.Request and returns an httpx.Response.

    Clears the HTTP client cache on teardown for test isolation.
    """

    class _Patcher:
        def __init__(self):
            self._patches = []
            self._clients = []

        def set_handler(self, handler):
            """Set the mock transport handler for HTTP requests."""
            # Stop any existing patches before starting a new one
            for p in self._patches:
                p.stop()
            self._patches.clear()

            transport = make_mock_transport(handler)
            mock_client = httpx.AsyncClient(transport=transport)
            self._clients.append(mock_client)

            async def _get_client():
                return mock_client

            patcher = patch.object(http_client, '_get_client', side_effect=_get_client)
            patcher.start()
            self._patches.append(patcher)
            return mock_client

        def cleanup(self):
            for p in self._patches:
                p.stop()
            for c in self._clients:
                try:
                    import asyncio

                    asyncio.get_event_loop().run_until_complete(c.aclose())
                except Exception:
                    pass
            self._clients.clear()

    patcher = _Patcher()
    yield patcher

    # Teardown: stop patches and clear cache
    patcher.cleanup()
    http_client._cache.clear()
    http_client._cache_ttl.clear()


@pytest.fixture
def mock_token_for_integration():
    """Patch utils.common.token_manager to return a test token.

    All decorated tool functions use validate_token() from utils.common,
    which delegates to token_manager.get_token(). This fixture makes
    that call return 'integration-test-token'.
    """
    with patch('utils.common.token_manager') as mock_tm:
        mock_tm.get_token.return_value = 'integration-test-token'
        yield mock_tm


@pytest.fixture
def sample_api_responses():
    """Factory returning realistic API response payloads.

    Usage:
        data = sample_api_responses()
        servers = data['servers_list']
    """

    def _factory():
        return {
            'servers_list': {
                'count': 2,
                'next': None,
                'previous': None,
                'results': [
                    {
                        'id': '550e8400-e29b-41d4-a716-446655440001',
                        'name': 'web-server-01',
                        'ip': '10.0.1.10',
                        'status': 'running',
                        'os': 'Ubuntu 22.04',
                    },
                    {
                        'id': '550e8400-e29b-41d4-a716-446655440002',
                        'name': 'db-server-01',
                        'ip': '10.0.1.11',
                        'status': 'running',
                        'os': 'CentOS 9',
                    },
                ],
            },
            'server_detail': {
                'count': 1,
                'results': [
                    {
                        'id': '550e8400-e29b-41d4-a716-446655440001',
                        'name': 'web-server-01',
                        'ip': '10.0.1.10',
                        'status': 'running',
                        'os': 'Ubuntu 22.04',
                        'cpu': 4,
                        'memory': 8192,
                    },
                ],
            },
            'server_not_found': {
                'count': 0,
                'results': [],
            },
            'server_note_created': {
                'id': 'note-001',
                'server': '550e8400-e29b-41d4-a716-446655440001',
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
                'status_code': 204,
            },
            'events_list': {
                'count': 2,
                'results': [
                    {
                        'id': 'evt-001',
                        'server': '550e8400-e29b-41d4-a716-446655440001',
                        'reporter': 'system',
                        'record': 'Server started',
                        'added_at': '2024-06-01T12:00:00Z',
                    },
                    {
                        'id': 'evt-002',
                        'server': '550e8400-e29b-41d4-a716-446655440001',
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
    """Patch asyncio.sleep in http_client module to make retry tests fast.

    This is autouse so all integration tests run without actual sleep delays.
    Records delay values in mock_sleep.recorded_delays for backoff verification.
    """
    recorded_delays = []

    async def fast_sleep(delay):
        recorded_delays.append(delay)

    with patch('utils.http_client.asyncio.sleep', side_effect=fast_sleep) as mock_sleep:
        mock_sleep.recorded_delays = recorded_delays
        yield mock_sleep
