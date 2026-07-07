"""Unit tests for webhook and event subscription tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE
from tools.webhook_tools import (
    create_event_subscription,
    create_webhook,
    delete_event_subscription,
    delete_webhook,
    get_webhook,
    list_event_subscriptions,
    list_webhooks,
    update_webhook,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.webhook_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.patch = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('tool', 'tool_kwargs', 'method_name', 'expected_context'),
    [
        pytest.param(
            list_event_subscriptions,
            {'workspace': 'testworkspace', 'region': 'ap1'},
            'get',
            {},
            id='list_event_subscriptions',
        ),
        pytest.param(
            create_event_subscription,
            {
                'workspace': 'testworkspace',
                'channel': 'ch-1',
                'event_type': 'command_fin',
                'target_id': 'server-1',
                'region': 'ap1',
            },
            'post',
            {},
            id='create_event_subscription',
        ),
        pytest.param(
            delete_event_subscription,
            {
                'subscription_id': 'sub-1',
                'workspace': 'testworkspace',
                'region': 'ap1',
            },
            'delete',
            {'subscription_id': 'sub-1'},
            id='delete_event_subscription',
        ),
        pytest.param(
            list_webhooks,
            {'workspace': 'testworkspace', 'region': 'ap1'},
            'get',
            {},
            id='list_webhooks',
        ),
        pytest.param(
            get_webhook,
            {'webhook_id': 'wh-1', 'workspace': 'testworkspace', 'region': 'ap1'},
            'get',
            {'webhook_id': 'wh-1'},
            id='get_webhook',
        ),
        pytest.param(
            create_webhook,
            {
                'workspace': 'testworkspace',
                'name': 'alerts',
                'url': 'https://example.com/webhook',
                'region': 'ap1',
            },
            'post',
            {},
            id='create_webhook',
        ),
        pytest.param(
            update_webhook,
            {
                'webhook_id': 'wh-1',
                'workspace': 'testworkspace',
                'name': 'updated-alerts',
                'region': 'ap1',
            },
            'patch',
            {'webhook_id': 'wh-1'},
            id='update_webhook',
        ),
        pytest.param(
            delete_webhook,
            {
                'webhook_id': 'wh-1',
                'workspace': 'testworkspace',
                'region': 'ap1',
            },
            'delete',
            {'webhook_id': 'wh-1'},
            id='delete_webhook',
        ),
    ],
)
async def test_webhook_http_error_envelope_returns_error(
    tool,
    tool_kwargs,
    method_name,
    expected_context,
    mock_http_client,
    mock_token_manager,
):
    getattr(mock_http_client, method_name).return_value = HTTP_ERROR_ENVELOPE

    result = await tool(**tool_kwargs)

    assert result['status'] == 'error'
    assert result['message'] == HTTP_ERROR_ENVELOPE['message']
    assert result['status_code'] == HTTP_ERROR_ENVELOPE['status_code']
    assert result['region'] == 'ap1'
    assert result['workspace'] == 'testworkspace'
    for key, value in expected_context.items():
        assert result[key] == value


class TestEventSubscriptions:
    """Test event subscription tools."""

    @pytest.mark.asyncio
    async def test_list_event_subscriptions_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful event subscriptions list."""
        mock_http_client.get.return_value = {'count': 1, 'results': [{'id': 'sub-1'}]}

        result = await list_event_subscriptions(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/subscriptions/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_create_event_subscription_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful event subscription creation."""
        mock_http_client.post.return_value = {
            'id': 'sub-1',
            'event_type': 'command_fin',
        }

        result = await create_event_subscription(
            workspace='testworkspace',
            channel='ch-1',
            event_type='command_fin',
            target_id='server-1',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/subscriptions/',
            token='test-token',
            data={
                'channel': 'ch-1',
                'event_type': 'command_fin',
                'target_id': 'server-1',
            },
        )

    @pytest.mark.asyncio
    async def test_create_event_subscription_minimal(
        self, mock_http_client, mock_token_manager
    ):
        """Test event subscription creation with minimal params."""
        mock_http_client.post.return_value = {'id': 'sub-2'}

        result = await create_event_subscription(
            workspace='testworkspace',
            channel='ch-2',
            event_type='sudo',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/subscriptions/',
            token='test-token',
            data={'channel': 'ch-2', 'event_type': 'sudo'},
        )

    @pytest.mark.asyncio
    async def test_delete_event_subscription_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful event subscription deletion."""
        mock_http_client.delete.return_value = {}

        result = await delete_event_subscription(
            subscription_id='sub-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['subscription_id'] == 'sub-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/subscriptions/sub-1/',
            token='test-token',
        )


class TestWebhooks:
    """Test webhook tools."""

    @pytest.mark.asyncio
    async def test_list_webhooks_success(self, mock_http_client, mock_token_manager):
        """Test successful webhooks list."""
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [{'id': 'wh-1', 'name': 'alerts'}],
        }

        result = await list_webhooks(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/notifications/webhooks/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_create_webhook_success(self, mock_http_client, mock_token_manager):
        """Test successful webhook creation."""
        mock_http_client.post.return_value = {
            'id': 'wh-1',
            'name': 'alerts',
            'url': 'https://example.com/webhook',
        }

        result = await create_webhook(
            workspace='testworkspace',
            name='alerts',
            url='https://example.com/webhook',
            ssl_verify=False,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/notifications/webhooks/',
            token='test-token',
            data={
                'name': 'alerts',
                'url': 'https://example.com/webhook',
                'ssl_verify': False,
                'enabled': True,
            },
        )

    @pytest.mark.asyncio
    async def test_update_webhook_success(self, mock_http_client, mock_token_manager):
        """Test successful webhook update."""
        mock_http_client.patch.return_value = {
            'id': 'wh-1',
            'name': 'updated-alerts',
        }

        result = await update_webhook(
            webhook_id='wh-1',
            workspace='testworkspace',
            name='updated-alerts',
            enabled=False,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['webhook_id'] == 'wh-1'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/notifications/webhooks/wh-1/',
            token='test-token',
            data={'name': 'updated-alerts', 'enabled': False},
        )

    @pytest.mark.asyncio
    async def test_update_webhook_no_data(self, mock_http_client, mock_token_manager):
        """Test webhook update with no data returns error."""
        result = await update_webhook(
            webhook_id='wh-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert 'No update data provided' in result['message']
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_webhook_success(self, mock_http_client, mock_token_manager):
        """Test successful webhook deletion."""
        mock_http_client.delete.return_value = {}

        result = await delete_webhook(
            webhook_id='wh-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['webhook_id'] == 'wh-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/notifications/webhooks/wh-1/',
            token='test-token',
        )


class TestGetWebhook:
    """Test get_webhook function."""

    @pytest.mark.asyncio
    async def test_get_webhook_success(self, mock_http_client, mock_token_manager):
        """Returns single webhook detail by ID."""
        mock_http_client.get.return_value = {
            'id': 'wh-1',
            'name': 'deploy-hook',
            'url': 'https://example.com/hook',
            'enabled': True,
        }

        result = await get_webhook(
            webhook_id='wh-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == 'wh-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/notifications/webhooks/wh-1/',
            token='test-token',
        )
