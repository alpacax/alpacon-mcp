"""Tests for recovery hints module."""

from http import HTTPStatus

from utils.recovery_hints import (
    _detect_error_domain,
    _parse_status_code,
    enrich_error_response,
    get_recovery_hints,
)


class TestDetectErrorDomain:
    """Tests for error domain detection."""

    def test_command_from_message(self):
        assert (
            _detect_error_domain(HTTPStatus.FORBIDDEN, 'command ACL denied')
            == 'command'
        )

    def test_command_from_tool_name(self):
        assert (
            _detect_error_domain(
                HTTPStatus.FORBIDDEN, 'denied', tool_name='execute_command_sync'
            )
            == 'command'
        )

    def test_command_from_endpoint(self):
        assert (
            _detect_error_domain(
                HTTPStatus.FORBIDDEN, 'denied', endpoint='/api/events/commands/'
            )
            == 'command'
        )

    def test_server_from_message(self):
        assert (
            _detect_error_domain(HTTPStatus.NOT_FOUND, 'server not found') == 'server'
        )

    def test_server_from_tool_name(self):
        assert (
            _detect_error_domain(
                HTTPStatus.NOT_FOUND, 'not found', tool_name='get_server'
            )
            == 'server'
        )

    def test_server_from_endpoint(self):
        assert (
            _detect_error_domain(
                HTTPStatus.NOT_FOUND, 'not found', endpoint='/api/servers/servers/abc'
            )
            == 'server'
        )

    def test_file_from_message(self):
        assert (
            _detect_error_domain(HTTPStatus.FORBIDDEN, 'file access denied') == 'file'
        )

    def test_file_from_tool_name(self):
        assert (
            _detect_error_domain(
                HTTPStatus.FORBIDDEN, 'denied', tool_name='webftp_upload_file'
            )
            == 'file'
        )

    def test_user_from_message(self):
        assert _detect_error_domain(HTTPStatus.NOT_FOUND, 'user not found') == 'user'

    def test_user_from_tool_name(self):
        assert (
            _detect_error_domain(
                HTTPStatus.NOT_FOUND, 'not found', tool_name='get_iam_user'
            )
            == 'user'
        )

    def test_alert_from_tool_name(self):
        assert (
            _detect_error_domain(
                HTTPStatus.NOT_FOUND, 'not found', tool_name='get_alert'
            )
            == 'alert'
        )

    def test_acl_alone_does_not_match_command(self):
        assert _detect_error_domain(HTTPStatus.FORBIDDEN, 'ACL denied') != 'command'

    def test_server_acl_matches_server_not_command(self):
        assert (
            _detect_error_domain(
                HTTPStatus.FORBIDDEN, 'server ACL denied', tool_name='list_server_acls'
            )
            == 'server'
        )

    def test_general_fallback(self):
        assert (
            _detect_error_domain(HTTPStatus.INTERNAL_SERVER_ERROR, 'something broke')
            == 'general'
        )


class TestParseStatusCode:
    """Tests for status code parsing."""

    def test_int(self):
        assert _parse_status_code(HTTPStatus.FORBIDDEN) == HTTPStatus.FORBIDDEN

    def test_string(self):
        assert _parse_status_code('404') == HTTPStatus.NOT_FOUND

    def test_none(self):
        assert _parse_status_code(None) is None

    def test_invalid_string(self):
        assert _parse_status_code('timeout') is None

    def test_none_returns_no_hints(self):
        hints = get_recovery_hints(None, 'some error')
        assert hints['recovery_hints'] == []
        assert hints['related_tools'] == []


class TestGetRecoveryHints:
    """Tests for recovery hint lookup."""

    def test_403_command_acl(self):
        hints = get_recovery_hints(
            HTTPStatus.FORBIDDEN, 'command ACL denied', tool_name='execute_command_sync'
        )
        assert len(hints['recovery_hints']) > 0
        assert 'list_command_acls' in hints['related_tools']

    def test_403_server_access(self):
        hints = get_recovery_hints(
            HTTPStatus.FORBIDDEN, 'access denied', tool_name='get_server'
        )
        assert len(hints['recovery_hints']) > 0
        assert 'list_server_acls' in hints['related_tools']

    def test_403_file_access(self):
        hints = get_recovery_hints(
            HTTPStatus.FORBIDDEN, 'upload denied', tool_name='webftp_upload_file'
        )
        assert len(hints['recovery_hints']) > 0
        assert 'list_file_acls' in hints['related_tools']

    def test_404_server(self):
        hints = get_recovery_hints(
            HTTPStatus.NOT_FOUND, 'server not found', tool_name='get_server'
        )
        assert len(hints['recovery_hints']) > 0
        assert 'list_servers' in hints['related_tools']

    def test_404_user(self):
        hints = get_recovery_hints(
            HTTPStatus.NOT_FOUND, 'not found', tool_name='get_iam_user'
        )
        assert 'list_iam_users' in hints['related_tools']

    def test_404_alert(self):
        hints = get_recovery_hints(
            HTTPStatus.NOT_FOUND, 'not found', tool_name='get_alert'
        )
        assert 'list_alerts' in hints['related_tools']

    def test_401_general(self):
        hints = get_recovery_hints(HTTPStatus.UNAUTHORIZED, 'authentication failed')
        assert len(hints['recovery_hints']) > 0

    def test_429_rate_limit(self):
        hints = get_recovery_hints(HTTPStatus.TOO_MANY_REQUESTS, 'too many requests')
        assert len(hints['recovery_hints']) > 0

    def test_500_server_error(self):
        hints = get_recovery_hints(
            HTTPStatus.INTERNAL_SERVER_ERROR, 'internal server error'
        )
        assert len(hints['recovery_hints']) > 0

    def test_unknown_code_returns_empty(self):
        hints = get_recovery_hints(HTTPStatus.IM_A_TEAPOT, "I'm a teapot")
        assert hints['recovery_hints'] == []
        assert hints['related_tools'] == []

    def test_string_status_code(self):
        hints = get_recovery_hints(
            '403', 'command denied', tool_name='execute_command_sync'
        )
        assert len(hints['recovery_hints']) > 0

    def test_general_fallback_for_unknown_domain(self):
        hints = get_recovery_hints(HTTPStatus.NOT_FOUND, 'something not found')
        assert len(hints['recovery_hints']) > 0

    def test_returned_hints_are_independent_copies(self):
        hints1 = get_recovery_hints(HTTPStatus.UNAUTHORIZED, 'auth failed')
        hints2 = get_recovery_hints(HTTPStatus.UNAUTHORIZED, 'auth failed')
        hints1['recovery_hints'].append('mutated')
        assert 'mutated' not in hints2['recovery_hints']


class TestEnrichErrorResponse:
    """Tests for error response enrichment."""

    def test_enriches_error_response(self):
        resp = {
            'status': 'error',
            'message': 'server not found',
            'status_code': HTTPStatus.NOT_FOUND,
        }
        enriched = enrich_error_response(resp, tool_name='get_server')
        assert 'recovery_hints' in enriched
        assert 'related_tools' in enriched
        assert 'list_servers' in enriched['related_tools']

    def test_enriches_http_client_error(self):
        resp = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'message': 'command ACL denied',
        }
        enriched = enrich_error_response(resp, tool_name='execute_command_sync')
        assert 'recovery_hints' in enriched
        assert 'list_command_acls' in enriched['related_tools']

    def test_skips_success_response(self):
        resp = {'status': 'success', 'data': []}
        enriched = enrich_error_response(resp, tool_name='list_servers')
        assert 'recovery_hints' not in enriched

    def test_skips_non_dict(self):
        assert enrich_error_response('not a dict') == 'not a dict'

    def test_does_not_overwrite_existing_hints(self):
        resp = {
            'status': 'error',
            'message': 'server not found',
            'status_code': HTTPStatus.NOT_FOUND,
            'recovery_hints': ['custom hint'],
        }
        enriched = enrich_error_response(resp, tool_name='get_server')
        assert enriched['recovery_hints'] == ['custom hint']

    def test_no_hints_for_unknown_code(self):
        resp = {
            'status': 'error',
            'message': 'weird error',
            'status_code': HTTPStatus.IM_A_TEAPOT,
        }
        enriched = enrich_error_response(resp)
        assert 'recovery_hints' not in enriched

    def test_error_code_field(self):
        resp = {
            'status': 'error',
            'message': 'authentication failed',
            'error_code': HTTPStatus.UNAUTHORIZED,
        }
        enriched = enrich_error_response(resp)
        assert 'recovery_hints' in enriched

    def test_no_hints_when_status_code_missing(self):
        resp = {
            'status': 'error',
            'message': 'something failed',
        }
        enriched = enrich_error_response(resp)
        assert 'recovery_hints' not in enriched


def test_a_402_explains_the_paid_plan_gate():
    hints = get_recovery_hints(status_code=402, tool_name='create_alert_rule')

    assert hints['recovery_hints']
    assert any('paid plan' in h.lower() for h in hints['recovery_hints'])
    assert 'attach_alert_rule' in hints['related_tools']


def test_a_402_on_a_webhook_names_the_webhook_gate():
    hints = get_recovery_hints(status_code=402, tool_name='create_webhook')

    assert any('webhook' in h.lower() for h in hints['recovery_hints'])
    assert 'list_webhooks' in hints['related_tools']


def test_a_402_outside_a_known_domain_stays_plan_neutral():
    hints = get_recovery_hints(
        status_code=402, tool_name='update_workspace_preferences'
    )

    assert any('paid plan' in h.lower() for h in hints['recovery_hints'])
    assert not any(
        word in h.lower()
        for h in hints['recovery_hints']
        for word in ('alert rule', 'webhook')
    )


def test_an_alert_message_naming_the_server_stays_in_the_alert_domain():
    assert (
        _detect_error_domain(
            HTTPStatus.NOT_FOUND,
            'No Server matches the given query.',
            tool_name='attach_alert_rule',
        )
        == 'alert'
    )


def test_a_404_from_attach_alert_rule_points_at_list_servers():
    hints = get_recovery_hints(
        status_code=404,
        message='No Server matches the given query.',
        tool_name='attach_alert_rule',
        endpoint='/api/servers/servers/abc/attach-rule/',
    )

    assert 'list_servers' in hints['related_tools']
    assert any('attach_alert_rule' in h for h in hints['recovery_hints'])
