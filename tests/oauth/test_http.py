"""Tests for the request/response plumbing shared by the OAuth routes."""

from utils.oauth._http import _LOG_VALUE_MAX_CHARS, _escape_for_log


class TestEscapeForLog:
    """Tests for the client-value escaping helper."""

    def test_truncates_an_oversized_value(self):
        escaped = _escape_for_log('a' * (_LOG_VALUE_MAX_CHARS + 100))

        assert escaped == 'a' * _LOG_VALUE_MAX_CHARS + '...(truncated)'

    def test_truncates_when_escaping_expands_the_value(self):
        """Escaping grows a control character, so the input cap alone is not enough."""
        escaped = _escape_for_log('\n' * _LOG_VALUE_MAX_CHARS)

        assert escaped == '\\n' * (_LOG_VALUE_MAX_CHARS // 2) + '...(truncated)'
