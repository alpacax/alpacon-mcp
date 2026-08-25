"""Unit tests for alert management tools."""

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import tools.alert_tools as alert_tools
from tests.conftest import HTTP_ERROR_ENVELOPE
from tools.alert_tools import (
    _TARGETS_SENTENCE,
    ALERT_RULE_TARGETS,
    acknowledge_alert,
    attach_alert_rule,
    create_alert_rule,
    delete_alert_rule,
    detach_alert_rule,
    get_alert,
    list_alerts,
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

    @pytest.mark.asyncio
    async def test_list_dismissed_filter(self, mock_http_client, mock_token_manager):
        """dismissed=False must forward as a param, not be dropped by a truthy check."""
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_alerts(
            workspace='testworkspace', region='ap1', dismissed=False
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/alerts/',
            token='test-token',
            params={'dismissed': False},
        )

    @pytest.mark.asyncio
    async def test_list_forwards_the_filters_alertfilter_declares(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        await list_alerts(
            workspace='testworkspace',
            region='ap1',
            alert_type='metric_threshold',
            severity='critical',
            server_name='web-01',
        )

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/alerts/',
            token='test-token',
            params={
                'alert_type': 'metric_threshold',
                'severity': 'critical',
                'server_name': 'web-01',
            },
        )

    def test_list_no_longer_accepts_status(self):
        # list_alerts takes **kwargs, so a dead argument is swallowed rather
        # than rejected; the signature is the only thing that can be asserted.
        assert 'status' not in inspect.signature(list_alerts).parameters


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


class TestAcknowledgeAlert:
    @pytest.mark.asyncio
    async def test_acknowledge_posts_only_the_action_type(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'message': 'Alert checked successfully'}

        result = await acknowledge_alert(
            alert_id=ALERT_ID,
            workspace='testworkspace',
            action_type='checked',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/alerts/{ALERT_ID}/acknowledge/',
            token='test-token',
            data={'action_type': 'checked'},
        )

    @pytest.mark.asyncio
    async def test_acknowledge_rejects_an_unknown_action_before_calling(
        self, mock_http_client, mock_token_manager
    ):
        result = await acknowledge_alert(
            alert_id=ALERT_ID,
            workspace='testworkspace',
            action_type='muted',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'action_type'
        mock_http_client.post.assert_not_called()

    def test_mute_alert_is_gone(self):
        assert not hasattr(alert_tools, 'mute_alert')


class TestCreateAlertRule:
    @pytest.mark.asyncio
    async def test_create_sends_the_four_writable_fields(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': RULE_ID}

        result = await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk-usage',
            threshold=85.0,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/alert-rules/',
            token='test-token',
            data={
                'name': 'disk above 85',
                'target': 'disk-usage',
                'threshold': 85.0,
                'is_default': False,
            },
        )

    def test_create_no_longer_accepts_the_invented_fields(self):
        # create_alert_rule takes **kwargs, so a dead argument is swallowed
        # rather than rejected; assert on the signature instead.
        params = inspect.signature(create_alert_rule).parameters
        for dead in (
            'metric_type',
            'condition',
            'enabled',
            'servers',
            'notification_channels',
            'description',
        ):
            assert dead not in params, dead

    @pytest.mark.asyncio
    async def test_create_rejects_an_unknown_target_before_calling(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk',
            threshold=85.0,
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'target'
        mock_http_client.post.assert_not_called()

    def test_every_target_metric_reaches_both_descriptions(self):
        # mcp.tool() hands back the bare function, so the description is not
        # reachable from the tool object; assert on the sentence both
        # descriptions interpolate, and that they both still interpolate it.
        assert len(ALERT_RULE_TARGETS) == 15
        for target in ALERT_RULE_TARGETS:
            assert target in _TARGETS_SENTENCE, target

        source = Path('tools/alert_tools.py').read_text()
        assert source.count('{_TARGETS_SENTENCE}') == 2


class TestUpdateAlertRule:
    @pytest.mark.asyncio
    async def test_update_sends_only_what_it_was_given(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': RULE_ID}

        result = await update_alert_rule(
            rule_id=RULE_ID,
            workspace='testworkspace',
            threshold=90.0,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/alert-rules/{RULE_ID}/',
            token='test-token',
            data={'threshold': 90.0},
        )

    @pytest.mark.asyncio
    async def test_update_rejects_an_unknown_target_before_calling(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_alert_rule(
            rule_id=RULE_ID,
            workspace='testworkspace',
            target='disk',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'target'
        mock_http_client.patch.assert_not_called()

    def test_update_no_longer_accepts_the_invented_fields(self):
        params = inspect.signature(update_alert_rule).parameters
        assert set(params) == {
            'rule_id',
            'workspace',
            'name',
            'target',
            'threshold',
            'is_default',
            'region',
            'kwargs',
        }

    @pytest.mark.asyncio
    async def test_update_with_no_fields_is_a_validation_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_alert_rule(
            rule_id=RULE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
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


class TestAttachDetachAlertRule:
    SERVER_ID = '550e8400-e29b-41d4-a716-446655440123'

    @pytest.mark.asyncio
    async def test_attach_posts_the_rule_to_the_server_route(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'status': 'success', 'status_code': 204}

        result = await attach_alert_rule(
            server_id=self.SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{self.SERVER_ID}/attach-rule/',
            token='test-token',
            data={'rule': RULE_ID},
        )

    @pytest.mark.asyncio
    async def test_detach_uses_the_detach_route(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'status': 'success', 'status_code': 204}

        result = await detach_alert_rule(
            server_id=self.SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{self.SERVER_ID}/detach-rule/',
            token='test-token',
            data={'rule': RULE_ID},
        )

    @pytest.mark.asyncio
    async def test_attaching_an_already_attached_rule_still_succeeds(
        self, mock_http_client, mock_token_manager
    ):
        # The server backs attach with server.rules.add(), a Django M2M write
        # that is a no-op when the rule is already there, so 204 comes back
        # either way and the tool must report success rather than invent a
        # "no change" outcome.
        mock_http_client.post.return_value = {'status': 'success', 'status_code': 204}

        first = await attach_alert_rule(
            server_id=self.SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )
        second = await attach_alert_rule(
            server_id=self.SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert first['status'] == 'success'
        assert second['status'] == 'success'
        assert mock_http_client.post.call_count == 2


# Each endpoint's error-envelope path is identical; one parametrized case per
# tool (with its HTTP verb) replaces six near-duplicate per-class tests.
@pytest.mark.parametrize(
    'verb, func, kwargs',
    [
        ('get', list_alerts, {}),
        ('get', get_alert, {'alert_id': ALERT_ID}),
        (
            'post',
            acknowledge_alert,
            {'alert_id': ALERT_ID, 'action_type': 'checked'},
        ),
        (
            'post',
            create_alert_rule,
            {'name': 'cpu-high', 'target': 'cpu-usage', 'threshold': 90.0},
        ),
        ('patch', update_alert_rule, {'rule_id': RULE_ID, 'threshold': 80.0}),
        ('delete', delete_alert_rule, {'rule_id': RULE_ID}),
    ],
    ids=[
        'list_alerts',
        'get_alert',
        'acknowledge_alert',
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
