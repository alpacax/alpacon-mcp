"""
Unit tests for workspace_tools module.

Tests workspace management functionality including workspace listing.
Note: User settings and profile endpoints have been removed from the server.
"""

from unittest.mock import MagicMock, patch

import pytest


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

    with patch('utils.token_manager.get_token_manager', return_value=mock_manager):
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
        assert 'data' in result
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
    async def test_list_workspaces_default_region(self, mock_token_manager):
        """Test workspace listing with default region (ap1)."""
        from tools.workspace_tools import list_workspaces

        result = await list_workspaces()

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'

        workspaces = result['data']['workspaces']
        assert len(workspaces) == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
