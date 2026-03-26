"""Tests for MFA pre-check in the tool handler decorator."""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from utils.security_settings import (
    WorkspaceSecuritySettings,
    check_mfa_completed,
    get_action_for_tool,
)


class TestGetActionForTool:
    """Tests for tool name -> MFA action mapping."""

    def test_websh_tools(self):
        assert get_action_for_tool('execute_command') == 'websh'
        assert get_action_for_tool('execute_command_batch') == 'websh'
        assert get_action_for_tool('websh_session_create') == 'websh'
        assert get_action_for_tool('websh_channel_execute') == 'websh'

    def test_webftp_tools(self):
        assert get_action_for_tool('webftp_upload_file') == 'webftp'
        assert get_action_for_tool('webftp_download_file') == 'webftp'
        assert get_action_for_tool('webftp_session_create') == 'webftp'

    def test_command_tools(self):
        assert get_action_for_tool('execute_command_with_acl') == 'command'
        assert get_action_for_tool('execute_command_sync') == 'command'
        assert get_action_for_tool('execute_command_multi_server') == 'command'

    def test_non_mfa_tools(self):
        assert get_action_for_tool('list_servers') is None
        assert get_action_for_tool('get_server') is None
        assert get_action_for_tool('get_cpu_usage') is None
        assert get_action_for_tool('list_workspaces') is None


class TestCheckMfaCompleted:
    """Tests for JWT MFA claim validation."""

    def _make_settings(
        self, mfa_required=True, timeout=900, actions=None, methods=None
    ):
        return WorkspaceSecuritySettings(
            {
                'mfa_required': mfa_required,
                'mfa_timeout': timeout,
                'mfa_required_actions': actions or ['websh', 'command'],
                'allowed_mfa_methods': methods or [],
            }
        )

    def test_valid_mfa_within_timeout(self):
        recent = (
            (datetime.now(tz=UTC) - timedelta(seconds=60))
            .isoformat()
            .replace('+00:00', 'Z')
        )
        claims = {'https://alpacon.io/completed_mfa_methods': {'otp': recent}}
        settings = self._make_settings()
        assert check_mfa_completed(claims, settings) is True

    def test_expired_mfa(self):
        old = (
            (datetime.now(tz=UTC) - timedelta(seconds=1800))
            .isoformat()
            .replace('+00:00', 'Z')
        )
        claims = {'https://alpacon.io/completed_mfa_methods': {'otp': old}}
        settings = self._make_settings()
        assert check_mfa_completed(claims, settings) is False

    def test_empty_claims(self):
        claims = {}
        settings = self._make_settings()
        assert check_mfa_completed(claims, settings) is False

    def test_empty_mfa_methods(self):
        claims = {'https://alpacon.io/completed_mfa_methods': {}}
        settings = self._make_settings()
        assert check_mfa_completed(claims, settings) is False

    def test_method_not_in_allowed_list(self):
        recent = (
            (datetime.now(tz=UTC) - timedelta(seconds=60))
            .isoformat()
            .replace('+00:00', 'Z')
        )
        claims = {'https://alpacon.io/completed_mfa_methods': {'otp': recent}}
        settings = self._make_settings(methods=['email'])
        assert check_mfa_completed(claims, settings) is False

    def test_method_in_allowed_list(self):
        recent = (
            (datetime.now(tz=UTC) - timedelta(seconds=60))
            .isoformat()
            .replace('+00:00', 'Z')
        )
        claims = {'https://alpacon.io/completed_mfa_methods': {'otp': recent}}
        settings = self._make_settings(methods=['otp', 'email'])
        assert check_mfa_completed(claims, settings) is True

    def test_future_timestamp_rejected(self):
        future = (
            (datetime.now(tz=UTC) + timedelta(hours=1))
            .isoformat()
            .replace('+00:00', 'Z')
        )
        claims = {'https://alpacon.io/completed_mfa_methods': {'otp': future}}
        settings = self._make_settings()
        assert check_mfa_completed(claims, settings) is False

    def test_non_string_timestamp_skipped(self):
        """Non-string MFA claim values should not cause AttributeError."""
        claims = {
            'https://alpacon.io/completed_mfa_methods': {'otp': None, 'email': 12345}
        }
        settings = self._make_settings()
        assert check_mfa_completed(claims, settings) is False

    def test_custom_namespace(self):
        """AUTH0_NAMESPACE env var changes the claim key lookup."""
        recent = (
            (datetime.now(tz=UTC) - timedelta(seconds=60))
            .isoformat()
            .replace('+00:00', 'Z')
        )
        claims = {'http://localhost/completed_mfa_methods': {'otp': recent}}
        settings = self._make_settings()

        with patch.dict(os.environ, {'AUTH0_NAMESPACE': 'http://localhost/'}):
            assert check_mfa_completed(claims, settings) is True

        # Default namespace should not find it
        assert check_mfa_completed(claims, settings) is False


class TestMfaPrecheck:
    """Tests for _check_mfa_requirement in decorators."""

    @pytest.fixture(autouse=True)
    def _set_auth_env(self):
        with patch.dict(os.environ, {'ALPACON_MCP_AUTH_ENABLED': 'true'}):
            yield

    @pytest.mark.asyncio
    async def test_mfa_required_signals_and_returns_true(self):
        """When MFA is required but not completed, should signal and return True."""
        from utils.decorators import _check_mfa_requirement

        settings = WorkspaceSecuritySettings(
            {
                'mfa_required': True,
                'mfa_timeout': 900,
                'mfa_required_actions': ['websh'],
                'allowed_mfa_methods': [],
            }
        )

        with (
            patch(
                'utils.decorators._decode_jwt_claims',
                return_value={
                    'sub': 'auth0|test',
                    'https://alpacon.io/completed_mfa_methods': {},
                },
            ),
            patch(
                'utils.security_settings.security_cache.get_settings',
                new_callable=AsyncMock,
                return_value=settings,
            ),
            patch('utils.error_handler.signal_upstream_auth_error') as mock_signal,
            patch('utils.error_handler.make_auth_error_key', return_value='test-key'),
        ):
            result = await _check_mfa_requirement(
                'execute_command', 'fake-jwt', 'test-ws'
            )

        assert result is True
        mock_signal.assert_called_once_with(
            'test-key', {'mfa_required': True, 'source': 'websh'}
        )

    @pytest.mark.asyncio
    async def test_mfa_not_required_returns_false(self):
        """When MFA is not required, should return False without signaling."""
        from utils.decorators import _check_mfa_requirement

        settings = WorkspaceSecuritySettings(
            {
                'mfa_required': False,
                'mfa_timeout': 900,
                'mfa_required_actions': [],
                'allowed_mfa_methods': [],
            }
        )

        with (
            patch(
                'utils.security_settings.security_cache.get_settings',
                new_callable=AsyncMock,
                return_value=settings,
            ),
            patch('utils.error_handler.signal_upstream_auth_error') as mock_signal,
        ):
            result = await _check_mfa_requirement(
                'execute_command', 'fake-jwt', 'test-ws'
            )

        assert result is False
        mock_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_mfa_tool_returns_false(self):
        """Non-MFA tools should return False immediately."""
        from utils.decorators import _check_mfa_requirement

        with patch(
            'utils.security_settings.security_cache.get_settings',
            new_callable=AsyncMock,
        ) as mock_get:
            result = await _check_mfa_requirement('list_servers', 'fake-jwt', 'test-ws')

        assert result is False
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_mfa_completed_returns_false(self):
        """When MFA is required and completed, should return False."""
        from utils.decorators import _check_mfa_requirement

        recent = (
            (datetime.now(tz=UTC) - timedelta(seconds=60))
            .isoformat()
            .replace('+00:00', 'Z')
        )
        settings = WorkspaceSecuritySettings(
            {
                'mfa_required': True,
                'mfa_timeout': 900,
                'mfa_required_actions': ['websh'],
                'allowed_mfa_methods': [],
            }
        )

        with (
            patch(
                'utils.decorators._decode_jwt_claims',
                return_value={
                    'sub': 'auth0|test',
                    'https://alpacon.io/completed_mfa_methods': {'otp': recent},
                },
            ),
            patch(
                'utils.security_settings.security_cache.get_settings',
                new_callable=AsyncMock,
                return_value=settings,
            ),
            patch('utils.error_handler.signal_upstream_auth_error') as mock_signal,
        ):
            result = await _check_mfa_requirement(
                'execute_command', 'fake-jwt', 'test-ws'
            )

        assert result is False
        mock_signal.assert_not_called()


class TestSecuritySettingsCache:
    """Tests for SecuritySettingsCache TTL, pruning, and deduplication."""

    def test_cache_hit(self):
        from utils.security_settings import SecuritySettingsCache

        cache = SecuritySettingsCache(ttl=60)
        settings = WorkspaceSecuritySettings({'mfa_required': True, 'mfa_timeout': 900})
        cache._put_bulk('token-a', {'ws1': settings})
        result = cache.get_cached('token-a', 'ws1')
        assert result is not None
        assert result.mfa_required is True

    def test_cache_miss(self):
        from utils.security_settings import SecuritySettingsCache

        cache = SecuritySettingsCache(ttl=60)
        assert cache.get_cached('token-a', 'ws1') is None

    def test_expired_entry(self):
        import time

        from utils.security_settings import SecuritySettingsCache

        cache = SecuritySettingsCache(ttl=0)
        settings = WorkspaceSecuritySettings({'mfa_required': True})
        cache._put_bulk('token-a', {'ws1': settings})
        time.sleep(0.01)
        assert cache.get_cached('token-a', 'ws1') is None

    def test_prune_removes_all_expired(self):
        import time

        from utils.security_settings import SecuritySettingsCache

        cache = SecuritySettingsCache(ttl=0)
        settings = WorkspaceSecuritySettings({'mfa_required': True})
        cache._put_bulk('token-a', {'ws1': settings, 'ws2': settings})
        cache._last_prune = 0
        time.sleep(0.01)
        cache._prune_expired()
        assert len(cache._cache) == 0

    @pytest.mark.asyncio
    async def test_fetch_on_cache_miss(self):
        from unittest.mock import MagicMock

        from utils.security_settings import SecuritySettingsCache

        cache = SecuritySettingsCache(ttl=60)

        # httpx.Response methods (json, raise_for_status) are sync
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'workspace': 'ws1',
                'mfa_required': True,
                'mfa_timeout': 900,
                'mfa_required_actions': ['websh'],
                'allowed_mfa_methods': [],
            },
        ]

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(os.environ, {'ALPACON_ACCOUNT_URL': 'https://account.test.com'}),
            patch('httpx.AsyncClient', return_value=mock_client),
        ):
            result = await cache.get_settings('fake-jwt', 'ws1')

        assert result is not None
        assert result.mfa_required is True
        assert cache.get_cached('fake-jwt', 'ws1') is not None

    @pytest.mark.asyncio
    async def test_concurrent_misses_deduplicate(self):
        """Multiple concurrent get_settings for same token should only fetch once."""
        import asyncio

        from utils.security_settings import SecuritySettingsCache

        cache = SecuritySettingsCache(ttl=60)
        fetch_count = 0

        async def counting_fetch(token):
            nonlocal fetch_count
            fetch_count += 1
            await asyncio.sleep(0.05)
            return {'ws1': WorkspaceSecuritySettings({'mfa_required': True})}

        cache.fetch_and_cache = counting_fetch

        results = await asyncio.gather(
            cache.get_settings('same-token', 'ws1'),
            cache.get_settings('same-token', 'ws1'),
            cache.get_settings('same-token', 'ws1'),
        )

        assert fetch_count == 1
        assert all(r is not None for r in results)
