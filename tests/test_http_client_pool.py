"""The pooled client path of AlpaconHTTPClient, driven through httpx.MockTransport.

A real httpx.AsyncClient runs here; only the network is replaced.
"""

import asyncio
from http import HTTPStatus

import httpx
import pytest

from utils.http_client import AlpaconHTTPClient

URL = 'https://ws.ap1.alpacon.io/api/servers/servers/'


class RecordingTransport(httpx.MockTransport):
    """Answer each request with the next queued status, recording what was sent."""

    def __init__(self, *statuses: int):
        self.requests: list[httpx.Request] = []
        self._statuses = list(statuses) or [HTTPStatus.OK]
        super().__init__(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        return httpx.Response(status, json={'results': []})


@pytest.fixture
async def make_client():
    clients: list[AlpaconHTTPClient] = []

    def build(transport: httpx.AsyncBaseTransport) -> AlpaconHTTPClient:
        client = AlpaconHTTPClient(transport=transport)
        client.retry_delay = 0
        clients.append(client)
        return client

    yield build
    for client in clients:
        await client.close()


class TestPooledClient:
    async def test_consecutive_requests_reuse_one_pooled_client(self, make_client):
        transport = RecordingTransport()
        client = make_client(transport)

        await client.request('GET', URL, token='abc')
        first = client._client
        await client.request('GET', URL, token='abc')

        assert isinstance(first, httpx.AsyncClient)
        assert client._client is first
        assert len(transport.requests) == 2

    async def test_request_reaches_the_transport_with_the_token_header(
        self, make_client
    ):
        transport = RecordingTransport()
        client = make_client(transport)

        result = await client.request('GET', URL, token='abc')

        assert result == {'results': []}
        sent = transport.requests[0]
        assert str(sent.url) == URL
        assert sent.headers['Authorization'] == 'token=abc'

    async def test_concurrent_first_calls_create_a_single_client(self, make_client):
        client = make_client(RecordingTransport())

        clients = await asyncio.gather(*(client._get_client() for _ in range(5)))

        assert all(c is clients[0] for c in clients)

    async def test_a_closed_client_is_replaced_on_the_next_request(self, make_client):
        transport = RecordingTransport()
        client = make_client(transport)
        await client.request('GET', URL)
        closed = client._client
        await client.close()

        result = await client.request('GET', URL)

        assert closed.is_closed
        assert client._client is not closed
        assert client.pool_active
        assert result == {'results': []}

    async def test_a_server_error_is_retried_on_the_same_pooled_client(
        self, make_client, monkeypatch
    ):
        transport = RecordingTransport(HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.OK)
        client = make_client(transport)
        attempts: list[httpx.AsyncClient] = []
        get_client = client._get_client

        async def recording_get_client() -> httpx.AsyncClient:
            attempts.append(await get_client())
            return attempts[-1]

        monkeypatch.setattr(client, '_get_client', recording_get_client)

        result = await client.request('GET', URL)

        assert result == {'results': []}
        assert len(transport.requests) == 2
        assert len(attempts) == 2
        assert attempts[0] is attempts[1]
