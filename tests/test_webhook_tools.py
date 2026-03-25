"""Unit tests for webhook and event subscription tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.webhook_tools import (
    create_event_subscription,
    create_webhook,
    delete_event_subscription,
    delete_webhook,
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


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


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
