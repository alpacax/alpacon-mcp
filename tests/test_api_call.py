"""Contract of the shared HTTP call boundary: error envelopes and forwarded params."""

from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest

from utils.api_call import http_call_response


@pytest.mark.parametrize('message', ['Upstream unavailable', None])
@pytest.mark.asyncio
async def test_http_error_preserves_status_and_context(message):
    envelope = {'error': 'HTTP Error', 'status_code': HTTPStatus.SERVICE_UNAVAILABLE}
    if message is not None:
        envelope['message'] = message
    method = AsyncMock(return_value=envelope)

    result = await http_call_response(
        method,
        region='us1',
        workspace='testworkspace',
        endpoint='/api/example/',
        token='test-token',
        params={'page': 2},
        default_message='Failed to read example',
        server_id='server-1',
    )

    method.assert_awaited_once_with(
        region='us1',
        workspace='testworkspace',
        endpoint='/api/example/',
        token='test-token',
        params={'page': 2},
    )
    assert result == {
        'status': 'error',
        'message': message or 'Failed to read example',
        'status_code': HTTPStatus.SERVICE_UNAVAILABLE,
        'region': 'us1',
        'workspace': 'testworkspace',
        'server_id': 'server-1',
    }


@pytest.mark.parametrize(
    'body, forwarded',
    [
        ({'data': {'name': 'example'}}, {'data': {'name': 'example'}}),
        ({'params': {'page': 2}}, {'params': {'page': 2}}),
        ({}, {}),
    ],
    ids=['body', 'query', 'neither'],
)
@pytest.mark.asyncio
async def test_only_the_given_body_shape_is_forwarded(body, forwarded):
    method = AsyncMock(return_value={'results': []})

    result = await http_call_response(
        method,
        region='us1',
        workspace='testworkspace',
        endpoint='/api/example/',
        token='test-token',
        default_message='Failed to read example',
        **body,
    )

    method.assert_awaited_once_with(
        region='us1',
        workspace='testworkspace',
        endpoint='/api/example/',
        token='test-token',
        **forwarded,
    )
    assert result == {
        'status': 'success',
        'data': {'results': []},
        'region': 'us1',
        'workspace': 'testworkspace',
    }
