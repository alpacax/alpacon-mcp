"""Unit tests for alert management tools."""

import inspect
import sys
from pathlib import Path

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE, http_client_fixture
from tools.alert_tools import (
    _TARGETS_SENTENCE,
    acknowledge_alert,
    attach_alert_rule,
    create_alert_rule,
    create_rule_override,
    delete_alert_rule,
    delete_rule_override,
    detach_alert_rule,
    get_alert,
    get_alert_rule_recipients,
    get_rule_override,
    list_alerts,
    list_rule_overrides,
    update_alert_rule,
    update_rule_override,
)

ALERT_ID = 'alert-1'
RULE_ID = 'rule-1'
SERVER_ID = '550e8400-e29b-41d4-a716-446655440123'
OVERRIDE_ID = 'override-1'

# The six fields the metrics-extension rework added to AlertRule (#243): each
# is sent only when the caller gives it.
NEW_RULE_FIELDS = [
    ('operator', 'lte'),
    ('duration_s', 60),
    ('recovery_threshold', 70.0),
    ('no_data_after_s', 300),
    ('device', 'sda1'),
    ('severity', 'critical'),
]

# The two notification-destination fields the alert-rule-destinations feature
# added to AlertRule (alpacax/alpacon-server#3594): each is sent only when given.
NEW_DESTINATION_FIELDS = [
    ('notify_email', 'admins'),
    ('notify_slack_channel', False),
]

# All four notify_email choices AlertRule.EmailDestination accepts
# (alpacax/alpacon-server#3594), for forwarding coverage broader than the one
# value NEW_DESTINATION_FIELDS exercises.
ALL_NOTIFY_EMAIL_VALUES = ['all', 'admins', 'group_members', 'none']


mock_http_client = http_client_fixture('tools.alert_tools')


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
            resolved=True,
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
                'resolved': True,
            },
        )

    @pytest.mark.asyncio
    async def test_list_resolved_false_filter(
        self, mock_http_client, mock_token_manager
    ):
        """resolved=False must forward as a param, not be dropped by a truthy check."""
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_alerts(
            workspace='testworkspace', region='ap1', resolved=False
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/alerts/',
            token='test-token',
            params={'resolved': False},
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
        module = sys.modules[acknowledge_alert.__module__]
        assert not hasattr(module, 'mute_alert')


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
    async def test_create_forwards_an_unrecognized_target_to_the_server(
        self, mock_http_client, mock_token_manager
    ):
        # The server holds the authoritative target list (AlertRule.TARGET_METRICS)
        # and returns a 400 for one it does not recognize; this tool no longer
        # pre-validates, so an unfamiliar target still reaches http_client.
        mock_http_client.post.return_value = {'id': RULE_ID, 'target': 'disk'}

        result = await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk',
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
                'target': 'disk',
                'threshold': 85.0,
                'is_default': False,
            },
        )

    def test_targets_sentence_reaches_both_descriptions(self):
        # mcp.tool() hands back the bare function, so the description is not
        # reachable from the tool object; assert on the sentence both
        # descriptions interpolate, and that they both still interpolate it.
        assert 'cpu-usage' in _TARGETS_SENTENCE

        source = Path('tools/alert_tools.py').read_text()
        assert source.count('{_TARGETS_SENTENCE}') == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize('field, value', NEW_RULE_FIELDS)
    async def test_create_sends_new_fields_only_when_given(
        self, field, value, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': RULE_ID}

        await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk-usage',
            threshold=85.0,
            region='ap1',
            **{field: value},
        )

        sent_data = mock_http_client.post.call_args.kwargs['data']
        assert sent_data[field] == value
        for other_field, _other_value in NEW_RULE_FIELDS:
            if other_field != field:
                assert other_field not in sent_data

    @pytest.mark.asyncio
    async def test_create_omits_all_six_new_fields_when_none_given(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': RULE_ID}

        await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk-usage',
            threshold=85.0,
            region='ap1',
        )

        sent_data = mock_http_client.post.call_args.kwargs['data']
        for field, _value in NEW_RULE_FIELDS:
            assert field not in sent_data

    @pytest.mark.asyncio
    @pytest.mark.parametrize('field, value', NEW_DESTINATION_FIELDS)
    async def test_create_sends_destination_fields_only_when_given(
        self, field, value, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': RULE_ID}

        await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk-usage',
            threshold=85.0,
            region='ap1',
            **{field: value},
        )

        sent_data = mock_http_client.post.call_args.kwargs['data']
        assert sent_data[field] == value
        for other_field, _other_value in NEW_DESTINATION_FIELDS:
            if other_field != field:
                assert other_field not in sent_data

    @pytest.mark.asyncio
    @pytest.mark.parametrize('notify_email', ALL_NOTIFY_EMAIL_VALUES)
    async def test_create_forwards_every_valid_notify_email_choice(
        self, notify_email, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': RULE_ID}

        result = await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk-usage',
            threshold=85.0,
            region='ap1',
            notify_email=notify_email,
        )

        assert result['status'] == 'success'
        sent_data = mock_http_client.post.call_args.kwargs['data']
        assert sent_data['notify_email'] == notify_email

    @pytest.mark.asyncio
    async def test_create_omits_destination_fields_when_none_given(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': RULE_ID}

        await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk-usage',
            threshold=85.0,
            region='ap1',
        )

        sent_data = mock_http_client.post.call_args.kwargs['data']
        for field, _value in NEW_DESTINATION_FIELDS:
            assert field not in sent_data

    @pytest.mark.asyncio
    async def test_create_rejects_an_unrecognized_notify_email_before_calling(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_alert_rule(
            workspace='testworkspace',
            name='disk above 85',
            target='disk-usage',
            threshold=85.0,
            region='ap1',
            notify_email='everyone',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'notify_email'
        mock_http_client.post.assert_not_called()


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
    async def test_update_forwards_an_unrecognized_target_to_the_server(
        self, mock_http_client, mock_token_manager
    ):
        # Same rationale as create: the server validates, this tool does not.
        mock_http_client.patch.return_value = {'id': RULE_ID, 'target': 'disk'}

        result = await update_alert_rule(
            rule_id=RULE_ID,
            workspace='testworkspace',
            target='disk',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/alert-rules/{RULE_ID}/',
            token='test-token',
            data={'target': 'disk'},
        )

    def test_update_no_longer_accepts_the_invented_fields(self):
        params = inspect.signature(update_alert_rule).parameters
        assert set(params) == {
            'rule_id',
            'workspace',
            'name',
            'target',
            'threshold',
            'is_default',
            'operator',
            'duration_s',
            'recovery_threshold',
            'no_data_after_s',
            'device',
            'severity',
            'notify_email',
            'notify_slack_channel',
            'region',
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize('field, value', NEW_RULE_FIELDS)
    async def test_update_sends_new_fields_only_when_given(
        self, field, value, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': RULE_ID}

        await update_alert_rule(
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
            **{field: value},
        )

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/alert-rules/{RULE_ID}/',
            token='test-token',
            data={field: value},
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize('field, value', NEW_DESTINATION_FIELDS)
    async def test_update_sends_destination_fields_only_when_given(
        self, field, value, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': RULE_ID}

        await update_alert_rule(
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
            **{field: value},
        )

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/alert-rules/{RULE_ID}/',
            token='test-token',
            data={field: value},
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize('notify_email', ALL_NOTIFY_EMAIL_VALUES)
    async def test_update_forwards_every_valid_notify_email_choice(
        self, notify_email, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': RULE_ID}

        result = await update_alert_rule(
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
            notify_email=notify_email,
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/alert-rules/{RULE_ID}/',
            token='test-token',
            data={'notify_email': notify_email},
        )

    @pytest.mark.asyncio
    async def test_update_rejects_an_unrecognized_notify_email_before_calling(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_alert_rule(
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
            notify_email='everyone',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'notify_email'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_with_no_fields_is_a_validation_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_alert_rule(
            rule_id=RULE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'payload'
        assert (
            'At least one of name, target, threshold, is_default, operator, '
            'duration_s, recovery_threshold, no_data_after_s, device, '
            'severity, notify_email or notify_slack_channel must be '
            'provided.' in result['suggestion']
        )
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


class TestGetAlertRuleRecipients:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {
            'email': {
                'mode': 'group_members',
                'count': 7,
                'reasons': {'admins': 0, 'group_members': 6, 'owner': 1},
            },
            'slack_channel': {'enabled': True, 'connected': True},
            'event_subscriptions': 2,
        }

        result = await get_alert_rule_recipients(
            rule_id=RULE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['rule_id'] == RULE_ID
        assert result['data']['email'] == {
            'mode': 'group_members',
            'count': 7,
            'reasons': {'admins': 0, 'group_members': 6, 'owner': 1},
        }
        assert result['data']['slack_channel'] == {'enabled': True, 'connected': True}
        assert result['data']['event_subscriptions'] == 2
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/alert-rules/{RULE_ID}/recipients/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_reasons_can_exceed_count(self, mock_http_client, mock_token_manager):
        """The three reasons overlap, so their sum can exceed email.count—
        the tool must pass the payload through untouched, not reconcile it."""
        mock_http_client.get.return_value = {
            'email': {
                'mode': 'all',
                'count': 5,
                'reasons': {'admins': 3, 'group_members': 4, 'owner': 1},
            },
            'slack_channel': {'enabled': True, 'connected': False},
            'event_subscriptions': 0,
        }

        result = await get_alert_rule_recipients(
            rule_id=RULE_ID, workspace='testworkspace', region='ap1'
        )

        reasons = result['data']['email']['reasons']
        assert sum(reasons.values()) > result['data']['email']['count']

    @pytest.mark.asyncio
    async def test_not_found_when_servers_are_out_of_reach(
        self, mock_http_client, mock_token_manager
    ):
        """A rule attached only to servers outside the caller's reach 404s,
        the same shape as any other error envelope this tool passes through."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_alert_rule_recipients(
            rule_id=RULE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'


class TestAttachDetachAlertRule:
    @pytest.mark.asyncio
    async def test_attach_posts_the_rule_to_the_server_route(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'status': 'success', 'status_code': 204}

        result = await attach_alert_rule(
            server_id=SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/attach-rule/',
            token='test-token',
            data={'rule': RULE_ID},
        )

    @pytest.mark.asyncio
    async def test_detach_uses_the_detach_route(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'status': 'success', 'status_code': 204}

        result = await detach_alert_rule(
            server_id=SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/detach-rule/',
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
            server_id=SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )
        second = await attach_alert_rule(
            server_id=SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert first['status'] == 'success'
        assert second['status'] == 'success'
        assert mock_http_client.post.call_count == 2


class TestListRuleOverrides:
    @pytest.mark.asyncio
    async def test_list_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_rule_overrides(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/rule-overrides/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_forwards_server_and_rule_filters(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        await list_rule_overrides(
            workspace='testworkspace',
            region='ap1',
            server_id=SERVER_ID,
            rule_id=RULE_ID,
        )

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/rule-overrides/',
            token='test-token',
            params={'server': SERVER_ID, 'rule': RULE_ID},
        )

    @pytest.mark.asyncio
    async def test_list_enabled_false_filter_is_not_dropped(
        self, mock_http_client, mock_token_manager
    ):
        """enabled=False must forward as a param, not be dropped by a truthy check."""
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        await list_rule_overrides(
            workspace='testworkspace', region='ap1', enabled=False
        )

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/rule-overrides/',
            token='test-token',
            params={'enabled': False},
        )


class TestGetRuleOverride:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'id': OVERRIDE_ID, 'server': SERVER_ID}

        result = await get_rule_override(
            override_id=OVERRIDE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['override_id'] == OVERRIDE_ID
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/rule-overrides/{OVERRIDE_ID}/',
            token='test-token',
        )


class TestCreateRuleOverride:
    @pytest.mark.asyncio
    async def test_create_sends_only_server_and_rule_by_default(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': OVERRIDE_ID}

        result = await create_rule_override(
            server_id=SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/rule-overrides/',
            token='test-token',
            data={'server': SERVER_ID, 'rule': RULE_ID},
        )

    @pytest.mark.asyncio
    async def test_create_sends_the_optional_fields_when_given(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': OVERRIDE_ID}

        await create_rule_override(
            server_id=SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            threshold=90.0,
            recovery_threshold=70.0,
            duration_s=60,
            enabled=False,
            region='ap1',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/rule-overrides/',
            token='test-token',
            data={
                'server': SERVER_ID,
                'rule': RULE_ID,
                'threshold': 90.0,
                'recovery_threshold': 70.0,
                'duration_s': 60,
                'enabled': False,
            },
        )

    @pytest.mark.asyncio
    async def test_create_enabled_false_is_not_dropped(
        self, mock_http_client, mock_token_manager
    ):
        """enabled=False must forward, not be dropped by a truthy check."""
        mock_http_client.post.return_value = {'id': OVERRIDE_ID}

        await create_rule_override(
            server_id=SERVER_ID,
            rule_id=RULE_ID,
            workspace='testworkspace',
            enabled=False,
            region='ap1',
        )

        sent_data = mock_http_client.post.call_args.kwargs['data']
        assert sent_data['enabled'] is False


class TestUpdateRuleOverride:
    @pytest.mark.asyncio
    async def test_update_sends_only_what_it_was_given(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': OVERRIDE_ID}

        result = await update_rule_override(
            override_id=OVERRIDE_ID,
            workspace='testworkspace',
            threshold=95.0,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/rule-overrides/{OVERRIDE_ID}/',
            token='test-token',
            data={'threshold': 95.0},
        )

    @pytest.mark.asyncio
    async def test_update_enabled_false_is_not_dropped(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': OVERRIDE_ID}

        await update_rule_override(
            override_id=OVERRIDE_ID,
            workspace='testworkspace',
            enabled=False,
            region='ap1',
        )

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/rule-overrides/{OVERRIDE_ID}/',
            token='test-token',
            data={'enabled': False},
        )

    @pytest.mark.asyncio
    async def test_update_with_no_fields_is_a_validation_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_rule_override(
            override_id=OVERRIDE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'payload'
        assert (
            'At least one of server_id, rule_id, threshold, recovery_threshold, '
            'duration_s or enabled must be provided.' in result['suggestion']
        )
        mock_http_client.patch.assert_not_called()


class TestDeleteRuleOverride:
    @pytest.mark.asyncio
    async def test_delete_success(self, mock_http_client, mock_token_manager):
        mock_http_client.delete.return_value = {}

        result = await delete_rule_override(
            override_id=OVERRIDE_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['override_id'] == OVERRIDE_ID
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/metrics/rule-overrides/{OVERRIDE_ID}/',
            token='test-token',
        )


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
        ('get', get_alert_rule_recipients, {'rule_id': RULE_ID}),
        ('post', attach_alert_rule, {'server_id': SERVER_ID, 'rule_id': RULE_ID}),
        ('post', detach_alert_rule, {'server_id': SERVER_ID, 'rule_id': RULE_ID}),
        ('get', list_rule_overrides, {}),
        ('get', get_rule_override, {'override_id': OVERRIDE_ID}),
        (
            'post',
            create_rule_override,
            {'server_id': SERVER_ID, 'rule_id': RULE_ID},
        ),
        (
            'patch',
            update_rule_override,
            {'override_id': OVERRIDE_ID, 'threshold': 80.0},
        ),
        ('delete', delete_rule_override, {'override_id': OVERRIDE_ID}),
    ],
    ids=[
        'list_alerts',
        'get_alert',
        'acknowledge_alert',
        'create_alert_rule',
        'update_alert_rule',
        'delete_alert_rule',
        'get_alert_rule_recipients',
        'attach_alert_rule',
        'detach_alert_rule',
        'list_rule_overrides',
        'get_rule_override',
        'create_rule_override',
        'update_rule_override',
        'delete_rule_override',
    ],
)
@pytest.mark.asyncio
async def test_http_error_returns_error(
    verb, func, kwargs, mock_http_client, mock_token_manager
):
    getattr(mock_http_client, verb).return_value = HTTP_ERROR_ENVELOPE

    result = await func(workspace='testworkspace', region='ap1', **kwargs)

    assert result['status'] == 'error'
