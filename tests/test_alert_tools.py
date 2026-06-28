"""Unit tests for alert management tools."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE
from tools.alert_tools import (
    create_alert_rule,
    delete_alert_rule,
    get_alert,
    list_alerts,
    mute_alert,
    update_alert_rule,
)

ALERT_ID = 'alert-1'
RULE_ID = 'rule-1'


@pytest.fixture
def mock_http_client():
    with patch('tools.alert_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.patch = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


class TestListAlerts:
    @pytest.mark.asyncio
    async def test_list_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_alerts(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/alerts/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_active_filter(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_alerts(
            workspace='testworkspace', region='ap1', acknowledged=False
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/alerts/',
            token='test-token',
            params={'acknowledged': False},
        )


class TestGetAlert:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'id': ALERT_ID, 'status': 'triggered'}

        result = await get_alert(
            alert_id=ALERT_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['alert_id'] == ALERT_ID
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/alerts/{ALERT_ID}/',
            token='test-token',
        )


class TestMuteAlert:
    @pytest.mark.asyncio
    async def test_mute_success(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = {'id': ALERT_ID, 'muted': True}

        result = await mute_alert(
            alert_id=ALERT_ID,
            workspace='testworkspace',
            duration=30,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['alert_id'] == ALERT_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/alerts/{ALERT_ID}/mute/',
            token='test-token',
            data={'duration': 30},
        )


class TestCreateAlertRule:
    @pytest.mark.asyncio
    async def test_create_success(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = {'id': RULE_ID, 'name': 'cpu-high'}

        result = await create_alert_rule(
            workspace='testworkspace',
            name='cpu-high',
            metric_type='cpu',
            condition='gt',
            threshold=90.0,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/alert-rules/',
            token='test-token',
            data={
                'name': 'cpu-high',
                'metric_type': 'cpu',
                'condition': 'gt',
                'threshold': 90.0,
                'enabled': True,
            },
        )


class TestUpdateAlertRule:
    @pytest.mark.asyncio
    async def test_update_success(self, mock_http_client, mock_token_manager):
        mock_http_client.patch.return_value = {'id': RULE_ID, 'threshold': 80.0}

        result = await update_alert_rule(
            rule_id=RULE_ID,
            workspace='testworkspace',
            threshold=80.0,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['rule_id'] == RULE_ID
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/alert-rules/{RULE_ID}/',
            token='test-token',
            data={'threshold': 80.0},
        )

    @pytest.mark.asyncio
    async def test_update_no_data_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_alert_rule(
            rule_id=RULE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()


class TestDeleteAlertRule:
    @pytest.mark.asyncio
    async def test_delete_success(self, mock_http_client, mock_token_manager):
        mock_http_client.delete.return_value = {}

        result = await delete_alert_rule(
            rule_id=RULE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['rule_id'] == RULE_ID
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/alert-rules/{RULE_ID}/',
            token='test-token',
        )


# Each endpoint's error-envelope path is identical; one parametrized case per
# tool (with its HTTP verb) replaces six near-duplicate per-class tests.
@pytest.mark.parametrize(
    'verb, func, kwargs',
    [
        ('get', list_alerts, {}),
        ('get', get_alert, {'alert_id': ALERT_ID}),
        ('post', mute_alert, {'alert_id': ALERT_ID}),
        (
            'post',
            create_alert_rule,
            {
                'name': 'cpu-high',
                'metric_type': 'cpu',
                'condition': 'gt',
                'threshold': 90.0,
            },
        ),
        ('patch', update_alert_rule, {'rule_id': RULE_ID, 'threshold': 80.0}),
        ('delete', delete_alert_rule, {'rule_id': RULE_ID}),
    ],
    ids=[
        'list_alerts',
        'get_alert',
        'mute_alert',
        'create_alert_rule',
        'update_alert_rule',
        'delete_alert_rule',
    ],
)
@pytest.mark.asyncio
async def test_http_error_returns_error(
    verb, func, kwargs, mock_http_client, mock_token_manager
):
    getattr(mock_http_client, verb).return_value = HTTP_ERROR_ENVELOPE

    result = await func(workspace='testworkspace', region='ap1', **kwargs)

    assert result['status'] == 'error'
