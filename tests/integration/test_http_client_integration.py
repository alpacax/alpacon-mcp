"""Integration tests for HTTP client retry, caching, and request construction.

Uses MockTransport at the httpx transport layer to verify the full HTTP client
behavior including retry logic, exponential backoff, caching, URL construction,
and authorization headers.
"""

from http import HTTPStatus
from unittest.mock import patch

import httpx
import pytest

from utils.http_client import http_client

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestRetryBehavior:
    """Test HTTP client retry logic with MockTransport."""

    async def test_5xx_retries_3_times_then_fails(self, patched_http_client, no_sleep):
        """5xx errors trigger max_retries attempts then return error."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                json={'error': 'Internal Server Error'},
            )

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 3
        assert result['error'] == 'Max retries exceeded'

    async def test_5xx_retry_succeeds_on_second_attempt(
        self, patched_http_client, no_sleep
    ):
        """5xx on first call, 200 on second call returns success."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    HTTPStatus.INTERNAL_SERVER_ERROR, json={'error': 'Server Error'}
                )
            return httpx.Response(HTTPStatus.OK, json={'result': 'ok'})

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 2
        assert result == {'result': 'ok'}

    async def test_exponential_backoff_delays(self, patched_http_client, no_sleep):
        """Retry delays follow exponential backoff pattern."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                HTTPStatus.INTERNAL_SERVER_ERROR, json={'error': 'Server Error'}
            )

        patched_http_client.set_handler(handler)

        await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        # http_client.retry_delay starts at 1.0, doubles each time
        # First retry: sleep(1.0), second retry: sleep(2.0)
        recorded = no_sleep.recorded_delays
        assert len(recorded) == 2, (
            f'Expected 2 sleep calls, got {len(recorded)}: {recorded}'
        )
        assert recorded[0] == 1.0
        assert recorded[1] == 2.0

    async def test_4xx_not_retried(self, patched_http_client, no_sleep):
        """4xx client errors are not retried."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(HTTPStatus.NOT_FOUND, json={'detail': 'Not found'})

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 1
        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == HTTPStatus.NOT_FOUND

    async def test_401_not_retried(self, patched_http_client, no_sleep):
        """401 Unauthorized errors are not retried."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                HTTPStatus.UNAUTHORIZED, json={'detail': 'Unauthorized'}
            )

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 1
        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == HTTPStatus.UNAUTHORIZED

    async def test_502_retried(self, patched_http_client, no_sleep):
        """502 Bad Gateway is retried (5xx behavior)."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(
                    HTTPStatus.BAD_GATEWAY, json={'error': 'Bad Gateway'}
                )
            return httpx.Response(HTTPStatus.OK, json={'result': 'recovered'})

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 3
        assert result == {'result': 'recovered'}

    async def test_503_retried(self, patched_http_client, no_sleep):
        """503 Service Unavailable is retried (5xx behavior)."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                HTTPStatus.SERVICE_UNAVAILABLE, json={'error': 'Service Unavailable'}
            )

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 3
        assert result['error'] == 'Max retries exceeded'


class TestNoResponseCache:
    """Every read reaches the network; nothing is served from an earlier one."""

    LIST_ENDPOINT = '/api/servers/servers/'

    async def test_a_repeated_read_reaches_the_network_every_time(
        self, patched_http_client
    ):
        seen = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal seen
            seen += 1
            return httpx.Response(HTTPStatus.OK, json={'count': seen, 'results': []})

        patched_http_client.set_handler(handler)

        with patch.object(http_client, 'get_base_url', return_value='https://t.test'):
            for _ in range(2):
                await http_client.get(
                    region='ap1',
                    workspace='test',
                    endpoint=self.LIST_ENDPOINT,
                    token='test-token',
                )

        assert seen == 2

    async def test_a_second_token_gets_its_own_answer(self, patched_http_client):
        """One process serves many callers, each with its own permissions."""
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers['Authorization'])
            return httpx.Response(HTTPStatus.OK, json={'results': [len(seen)]})

        patched_http_client.set_handler(handler)

        with patch.object(http_client, 'get_base_url', return_value='https://t.test'):
            first = await http_client.get(
                region='ap1',
                workspace='test',
                endpoint=self.LIST_ENDPOINT,
                token='token-a',
            )
            second = await http_client.get(
                region='ap1',
                workspace='test',
                endpoint=self.LIST_ENDPOINT,
                token='token-b',
            )

        assert seen == ['token=token-a', 'token=token-b']
        assert first != second

    async def test_a_read_after_a_write_sees_the_write(self, patched_http_client):
        """No invalidation to get wrong: the read was never answered from a cache."""
        names = ['old', 'new']

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method != 'GET':
                names.pop(0)
                return httpx.Response(HTTPStatus.OK, json={'name': names[0]})
            return httpx.Response(HTTPStatus.OK, json={'name': names[0]})

        patched_http_client.set_handler(handler)

        url = f'https://test.ap1.alpacon.io{self.LIST_ENDPOINT}'
        before = await http_client.request(method='GET', url=url, token='tok')
        await http_client.request(
            method='PATCH', url=url, token='tok', json_data={'name': 'new'}
        )
        after = await http_client.request(method='GET', url=url, token='tok')

        assert before['name'] == 'old'
        assert after['name'] == 'new'


class TestURLConstruction:
    """Test URL construction and header formatting."""

    async def test_url_construction_for_regions(self, patched_http_client):
        """URL is constructed correctly for different regions."""
        captured_urls = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            return httpx.Response(HTTPStatus.OK, json={'ok': True})

        patched_http_client.set_handler(handler)

        await http_client.get(
            region='ap1', workspace='myworkspace', endpoint='/api/test/', token='tok'
        )
        await http_client.get(
            region='us1', workspace='myworkspace', endpoint='/api/test/', token='tok'
        )
        await http_client.get(
            region='us1', workspace='other-ws', endpoint='/api/test/', token='tok'
        )

        assert captured_urls[0] == 'https://myworkspace.ap1.alpacon.io/api/test/'
        assert captured_urls[1] == 'https://myworkspace.us1.alpacon.io/api/test/'
        assert captured_urls[2] == 'https://other-ws.us1.alpacon.io/api/test/'

    async def test_authorization_header_format(self, patched_http_client):
        """Authorization header uses 'token=<value>' format."""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(HTTPStatus.OK, json={'ok': True})

        patched_http_client.set_handler(handler)

        await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='my-secret-token',
        )

        assert captured_headers['authorization'] == 'token=my-secret-token'
        assert captured_headers['content-type'] == 'application/json'
        assert captured_headers['accept'] == 'application/json'
