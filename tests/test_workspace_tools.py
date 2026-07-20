"""
Unit tests for workspace_tools module.

Tests workspace management functionality including workspace listing.
Note: User settings and profile endpoints have been removed from the server.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE
from tools.workspace_tools import (
    get_current_user,
    get_workspace_access_control,
    get_workspace_notifications,
    get_workspace_preferences,
    get_workspace_security,
    list_workspace_mfa_methods,
    update_workspace_notifications,
    update_workspace_preferences,
)


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing.

    list_workspaces does a local import: from utils.token_manager import get_token_manager
    So we need to mock at utils.token_manager.get_token_manager.
    """
    mock_manager = MagicMock()
    mock_manager.get_all_tokens.return_value = {
        'ap1': {
            'production': {'token': 'token1'},
            'staging': {'token': 'token2'},
            'development': {'token': 'token3'},
        },
        'us1': {
            'backup': {'token': 'token4'},
            'disaster-recovery': {'token': 'token5'},
        },
        'eu1': {'compliance': {'token': 'token6'}},
    }
    # No pinned host override by default; list_workspaces falls back to the
    # derived {workspace}.{region}.alpacon.io host.
    mock_manager.get_base_url_override.return_value = None

    with (
        patch('utils.token_manager.get_token_manager', return_value=mock_manager),
        patch('utils.decorators._get_jwt_token', return_value=None),
    ):
        yield mock_manager


class TestListWorkspaces:
    """Test list_workspaces function."""

    @pytest.mark.asyncio
    async def test_list_workspaces_success(self, mock_token_manager):
        """Test successful workspace listing."""
        from tools.workspace_tools import list_workspaces

        result = await list_workspaces(region='ap1')

        # Verify response structure
        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['data']['source'] == 'token_file'
        assert 'workspaces' in result['data']

        # Verify workspace data
        workspaces = result['data']['workspaces']
        assert len(workspaces) == 3  # production, staging, development

        # Check specific workspace details
        workspace_names = [ws['workspace'] for ws in workspaces]
        assert 'production' in workspace_names
        assert 'staging' in workspace_names
        assert 'development' in workspace_names

        # Verify workspace structure
        production_ws = next(ws for ws in workspaces if ws['workspace'] == 'production')
        assert production_ws['region'] == 'ap1'
        assert production_ws['has_token'] is True
        assert production_ws['domain'] == 'production.ap1.alpacon.io'

        # Verify token manager was called
        mock_token_manager.get_all_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_workspaces_different_region(self, mock_token_manager):
        """Test workspace listing for different region."""
        from tools.workspace_tools import list_workspaces

        result = await list_workspaces(region='us1')

        assert result['status'] == 'success'
        assert result['region'] == 'us1'

        workspaces = result['data']['workspaces']
        assert len(workspaces) == 2  # backup, disaster-recovery

        workspace_names = [ws['workspace'] for ws in workspaces]
        assert 'backup' in workspace_names
        assert 'disaster-recovery' in workspace_names

        # Verify domain format
        backup_ws = next(ws for ws in workspaces if ws['workspace'] == 'backup')
        assert backup_ws['domain'] == 'backup.us1.alpacon.io'

    @pytest.mark.asyncio
    async def test_list_workspaces_empty_region(self, mock_token_manager):
        """Test workspace listing for region with no workspaces."""
        from tools.workspace_tools import list_workspaces

        # Mock empty tokens for unknown region
        mock_token_manager.get_all_tokens.return_value = {
            'ap1': {'production': {'token': 'token1'}}
        }

        result = await list_workspaces(region='nonexistent')

        assert result['status'] == 'success'
        assert result['region'] == 'nonexistent'
        assert result['data']['workspaces'] == []

    @pytest.mark.asyncio
    async def test_list_workspaces_workspace_without_token(self, mock_token_manager):
        """Test workspace listing with workspace that has no token."""
        from tools.workspace_tools import list_workspaces

        # Mock tokens with empty token value
        mock_token_manager.get_all_tokens.return_value = {
            'ap1': {
                'production': {'token': 'token1'},
                'staging': {'token': ''},  # Empty token
                'development': {},  # No token key
            }
        }

        result = await list_workspaces(region='ap1')

        assert result['status'] == 'success'
        workspaces = result['data']['workspaces']

        # Find workspaces and check token status
        production_ws = next(ws for ws in workspaces if ws['workspace'] == 'production')
        staging_ws = next(ws for ws in workspaces if ws['workspace'] == 'staging')
        development_ws = next(
            ws for ws in workspaces if ws['workspace'] == 'development'
        )

        assert production_ws['has_token'] is True
        assert staging_ws['has_token'] is False
        assert development_ws['has_token'] is False

    @pytest.mark.asyncio
    async def test_list_workspaces_reports_pinned_url_domain(
        self, tmp_path, monkeypatch
    ):
        """The reported domain resolves through get_base_url_override.

        Uses a real TokenManager so the displayed host gets the same
        precedence (env var over config) and normalization (scheme added,
        trailing slash dropped) as actual request routing.
        """
        import json

        from tools.workspace_tools import list_workspaces
        from utils.token_manager import TokenManager

        config_path = tmp_path / 'token.json'
        config_path.write_text(
            json.dumps(
                {
                    'us1': {
                        # Scheme-less with trailing slash: display must be normalized.
                        'acme': {'token': 'token1', 'url': 'acme.us1.alpacon.io/'},
                        # Bare string: derived host, unless the env var pins one.
                        'plain': 'bare-token',
                    }
                }
            )
        )
        monkeypatch.setenv(
            'ALPACON_MCP_US1_PLAIN_URL', 'https://pinned-by-env.us1.alpacon.io'
        )
        real_manager = TokenManager(config_file=str(config_path))

        with (
            patch('utils.token_manager.get_token_manager', return_value=real_manager),
            patch('utils.decorators._get_jwt_token', return_value=None),
        ):
            result = await list_workspaces(region='us1')

        workspaces = result['data']['workspaces']
        acme_ws = next(ws for ws in workspaces if ws['workspace'] == 'acme')
        plain_ws = next(ws for ws in workspaces if ws['workspace'] == 'plain')

        # Config URL is normalized exactly as http_client.get_base_url uses it.
        assert acme_ws['domain'] == 'https://acme.us1.alpacon.io'
        assert acme_ws['has_token'] is True
        # Env-var override applies to display too, even for bare-string entries.
        assert plain_ws['domain'] == 'https://pinned-by-env.us1.alpacon.io'

    @pytest.mark.asyncio
    async def test_list_workspaces_default_region(self, mock_token_manager):
        """Test workspace listing without region returns all regions."""
        from tools.workspace_tools import list_workspaces

        result = await list_workspaces()

        assert result['status'] == 'success'
        assert result['region'] == 'all'
        assert result['data']['source'] == 'token_file'

        workspaces = result['data']['workspaces']
        # Should include all workspaces from all regions (3 + 2 + 1 = 6)
        assert len(workspaces) == 6


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing workspace settings tools."""
    with patch('tools.workspace_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.patch = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token():
    """Mock token manager for testing workspace settings tools."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


class TestGetCurrentUser:
    """Test get_current_user function."""

    @pytest.mark.asyncio
    async def test_get_current_user_success(self, mock_http_client, mock_token):
        """Returns current user info from /api/iam/users/-/."""
        mock_http_client.get.return_value = {
            'id': 'user-1',
            'username': 'alice',
            'email': 'alice@example.com',
            'role': 'staff',
        }

        result = await get_current_user(workspace='production', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['username'] == 'alice'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='production',
            endpoint='/api/iam/users/-/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_current_user_missing_workspace(self):
        """Missing workspace returns validation error."""
        result = await get_current_user(workspace='', region='ap1')

        assert result['status'] == 'error'
        assert 'workspace' in result['message'].lower()


class TestGetWorkspaceAccessControl:
    """Test get_workspace_access_control function."""

    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = {
            'sudo_access': 'allowed',
            'root_access': 'denied',
            'work_session_ttl': 3600,
        }

        result = await get_workspace_access_control(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['work_session_ttl'] == 3600
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/access-control/-/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_http_error(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_workspace_access_control(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'


class TestGetWorkspaceSecurity:
    """Test get_workspace_security function, including the SaaS-only 404 case."""

    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = {
            'mfa_required': True,
            'allowed_mfa_methods': ['totp', 'webauthn'],
            'mfa_timeout': 900,
        }

        result = await get_workspace_security(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['mfa_required'] is True
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/security/-/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_not_available_on_premise_returns_clear_message(
        self, mock_http_client, mock_token
    ):
        """On-premise deployments 404 this SaaS-only route; report a clear reason."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_workspace_security(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['status_code'] == 404
        assert 'not available on this deployment' in result['message']

    @pytest.mark.asyncio
    async def test_other_http_error(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': 500,
            'message': 'Internal server error',
        }

        result = await get_workspace_security(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['status_code'] == 500
        assert 'not available on this deployment' not in result['message']

    @pytest.mark.asyncio
    async def test_success_payload_with_status_code_404_is_not_misread(
        self, mock_http_client, mock_token
    ):
        """A success payload that happens to carry status_code 404 (no error key)
        must not trip the SaaS-only branch."""
        mock_http_client.get.return_value = {
            'mfa_required': True,
            'status_code': 404,
        }

        result = await get_workspace_security(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['status_code'] == 404


class TestListWorkspaceMfaMethods:
    """Test list_workspace_mfa_methods function."""

    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = {
            'allowed_mfa_methods': ['totp'],
            'passkey_as_mfa': False,
        }

        result = await list_workspace_mfa_methods(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['allowed_mfa_methods'] == ['totp']
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/security/-/mfa-methods/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_not_available_on_premise_returns_clear_message(
        self, mock_http_client, mock_token
    ):
        """This mfa-methods sub-route shares the SaaS-only 404 guard, so on-premise
        deployments get the same clear reason as get_workspace_security."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await list_workspace_mfa_methods(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['status_code'] == 404
        assert 'not available on this deployment' in result['message']

    @pytest.mark.asyncio
    async def test_other_http_error(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': 500,
            'message': 'Internal server error',
        }

        result = await list_workspace_mfa_methods(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['status_code'] == 500
        assert 'not available on this deployment' not in result['message']

    @pytest.mark.asyncio
    async def test_success_payload_with_status_code_404_is_not_misread(
        self, mock_http_client, mock_token
    ):
        """A success payload carrying status_code 404 (no error key) must not trip
        the shared SaaS-only branch."""
        mock_http_client.get.return_value = {
            'allowed_mfa_methods': ['totp'],
            'status_code': 404,
        }

        result = await list_workspace_mfa_methods(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['allowed_mfa_methods'] == ['totp']


class TestGetWorkspaceNotifications:
    """Test get_workspace_notifications function."""

    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = {
            'disconnection_notification': True,
            'notification_channels': ['email'],
        }

        result = await get_workspace_notifications(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['notification_channels'] == ['email']
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/notifications/-/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_http_error(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_workspace_notifications(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'


class TestGetWorkspacePreferences:
    """Test get_workspace_preferences function."""

    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = {
            'timezone': 'Asia/Seoul',
            'language': 'ko',
            'billing_email': 'billing@example.com',
        }

        result = await get_workspace_preferences(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['timezone'] == 'Asia/Seoul'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/preferences/-/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_http_error(self, mock_http_client, mock_token):
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_workspace_preferences(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'


class TestUpdateWorkspaceNotifications:
    """Test update_workspace_notifications function."""

    @pytest.mark.asyncio
    async def test_partial_update_only_sends_provided_fields(
        self, mock_http_client, mock_token
    ):
        mock_http_client.patch.return_value = {
            'disconnection_notification': False,
            'notification_channels': ['email'],
        }

        result = await update_workspace_notifications(
            workspace='testworkspace',
            disconnection_notification=False,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/notifications/-/',
            token='test-token',
            data={'disconnection_notification': False},
        )

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, mock_http_client, mock_token):
        mock_http_client.patch.return_value = {
            'disconnection_notification': True,
            'notification_channels': ['email', 'webhook'],
        }

        result = await update_workspace_notifications(
            workspace='testworkspace',
            disconnection_notification=True,
            notification_channels=['email', 'webhook'],
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/notifications/-/',
            token='test-token',
            data={
                'disconnection_notification': True,
                'notification_channels': ['email', 'webhook'],
            },
        )

    @pytest.mark.asyncio
    async def test_no_fields_provided_returns_error(self, mock_http_client, mock_token):
        result = await update_workspace_notifications(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_http_error(self, mock_http_client, mock_token):
        mock_http_client.patch.return_value = HTTP_ERROR_ENVELOPE

        result = await update_workspace_notifications(
            workspace='testworkspace', disconnection_notification=True, region='ap1'
        )

        assert result['status'] == 'error'


class TestUpdateWorkspacePreferences:
    """Test update_workspace_preferences function."""

    @pytest.mark.asyncio
    async def test_partial_update_only_sends_provided_fields(
        self, mock_http_client, mock_token
    ):
        mock_http_client.patch.return_value = {'timezone': 'Asia/Seoul'}

        result = await update_workspace_preferences(
            workspace='testworkspace',
            timezone='Asia/Seoul',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/preferences/-/',
            token='test-token',
            data={'timezone': 'Asia/Seoul'},
        )

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, mock_http_client, mock_token):
        mock_http_client.patch.return_value = {
            'timezone': 'Asia/Seoul',
            'auto_agent_upgrade': False,
            'enabled_extensions': ['metrics'],
        }

        result = await update_workspace_preferences(
            workspace='testworkspace',
            timezone='Asia/Seoul',
            auto_agent_upgrade=False,
            enabled_extensions=['metrics'],
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/preferences/-/',
            token='test-token',
            data={
                'timezone': 'Asia/Seoul',
                'auto_agent_upgrade': False,
                'enabled_extensions': ['metrics'],
            },
        )

    @pytest.mark.asyncio
    async def test_no_fields_provided_returns_error(self, mock_http_client, mock_token):
        result = await update_workspace_preferences(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_http_error(self, mock_http_client, mock_token):
        mock_http_client.patch.return_value = HTTP_ERROR_ENVELOPE

        result = await update_workspace_preferences(
            workspace='testworkspace', timezone='Asia/Seoul', region='ap1'
        )

        assert result['status'] == 'error'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
