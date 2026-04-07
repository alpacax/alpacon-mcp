"""Tests for recovery hints module."""

from utils.recovery_hints import (
    _detect_error_domain,
    _parse_status_code,
    enrich_error_response,
    get_recovery_hints,
)


class TestDetectErrorDomain:
    """Tests for error domain detection."""

    def test_command_from_message(self):
        assert _detect_error_domain(403, 'command ACL denied') == 'command'

    def test_command_from_tool_name(self):
        assert (
            _detect_error_domain(403, 'denied', tool_name='execute_command_sync')
            == 'command'
        )

    def test_command_from_endpoint(self):
        assert (
            _detect_error_domain(403, 'denied', endpoint='/api/events/commands/')
            == 'command'
        )

    def test_server_from_message(self):
        assert _detect_error_domain(404, 'server not found') == 'server'

    def test_server_from_tool_name(self):
        assert (
            _detect_error_domain(404, 'not found', tool_name='get_server') == 'server'
        )

    def test_server_from_endpoint(self):
        assert (
            _detect_error_domain(404, 'not found', endpoint='/api/servers/servers/abc')
            == 'server'
        )

    def test_file_from_message(self):
        assert _detect_error_domain(403, 'file access denied') == 'file'

    def test_file_from_tool_name(self):
        assert (
            _detect_error_domain(403, 'denied', tool_name='webftp_upload_file')
            == 'file'
        )

    def test_user_from_message(self):
        assert _detect_error_domain(404, 'user not found') == 'user'

    def test_user_from_tool_name(self):
        assert (
            _detect_error_domain(404, 'not found', tool_name='get_iam_user') == 'user'
        )

    def test_alert_from_tool_name(self):
        assert _detect_error_domain(404, 'not found', tool_name='get_alert') == 'alert'

    def test_general_fallback(self):
        assert _detect_error_domain(500, 'something broke') == 'general'


class TestParseStatusCode:
    """Tests for status code parsing."""

    def test_int(self):
        assert _parse_status_code(403) == 403

    def test_string(self):
        assert _parse_status_code('404') == 404

    def test_none(self):
        assert _parse_status_code(None) == 0

    def test_invalid_string(self):
        assert _parse_status_code('timeout') == 0


class TestGetRecoveryHints:
    """Tests for recovery hint lookup."""

    def test_403_command_acl(self):
        hints = get_recovery_hints(
            403, 'command ACL denied', tool_name='execute_command_sync'
        )
        assert len(hints['recovery_hints']) > 0
        assert 'list_command_acls' in hints['related_tools']

    def test_403_server_access(self):
        hints = get_recovery_hints(403, 'access denied', tool_name='get_server')
        assert len(hints['recovery_hints']) > 0
        assert 'list_server_acls' in hints['related_tools']

    def test_403_file_access(self):
        hints = get_recovery_hints(403, 'upload denied', tool_name='webftp_upload_file')
        assert len(hints['recovery_hints']) > 0
        assert 'list_file_acls' in hints['related_tools']

    def test_404_server(self):
        hints = get_recovery_hints(404, 'server not found', tool_name='get_server')
        assert len(hints['recovery_hints']) > 0
        assert 'list_servers' in hints['related_tools']

    def test_404_user(self):
        hints = get_recovery_hints(404, 'not found', tool_name='get_iam_user')
        assert 'list_iam_users' in hints['related_tools']

    def test_404_alert(self):
        hints = get_recovery_hints(404, 'not found', tool_name='get_alert')
        assert 'list_alerts' in hints['related_tools']

    def test_401_general(self):
        hints = get_recovery_hints(401, 'authentication failed')
        assert len(hints['recovery_hints']) > 0

    def test_429_rate_limit(self):
        hints = get_recovery_hints(429, 'too many requests')
        assert len(hints['recovery_hints']) > 0

    def test_500_server_error(self):
        hints = get_recovery_hints(500, 'internal server error')
        assert len(hints['recovery_hints']) > 0

    def test_unknown_code_returns_empty(self):
        hints = get_recovery_hints(418, "I'm a teapot")
        assert hints['recovery_hints'] == []
        assert hints['related_tools'] == []

    def test_string_status_code(self):
        hints = get_recovery_hints(
            '403', 'command denied', tool_name='execute_command_sync'
        )
        assert len(hints['recovery_hints']) > 0

    def test_general_fallback_for_unknown_domain(self):
        hints = get_recovery_hints(404, 'something not found')
        assert len(hints['recovery_hints']) > 0


class TestEnrichErrorResponse:
    """Tests for error response enrichment."""

    def test_enriches_error_response(self):
        resp = {
            'status': 'error',
            'message': 'server not found',
            'status_code': 404,
        }
        enriched = enrich_error_response(resp, tool_name='get_server')
        assert 'recovery_hints' in enriched
        assert 'related_tools' in enriched
        assert 'list_servers' in enriched['related_tools']

    def test_enriches_http_client_error(self):
        resp = {
            'error': 'HTTP Error',
            'status_code': 403,
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
            'status_code': 404,
            'recovery_hints': ['custom hint'],
        }
        enriched = enrich_error_response(resp, tool_name='get_server')
        assert enriched['recovery_hints'] == ['custom hint']

    def test_no_hints_for_unknown_code(self):
        resp = {
            'status': 'error',
            'message': 'weird error',
            'status_code': 418,
        }
        enriched = enrich_error_response(resp)
        assert 'recovery_hints' not in enriched

    def test_error_code_field(self):
        resp = {
            'status': 'error',
            'message': 'authentication failed',
            'error_code': 401,
        }
        enriched = enrich_error_response(resp)
        assert 'recovery_hints' in enriched
