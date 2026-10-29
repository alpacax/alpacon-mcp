"""Basic integration and configuration-loading tests without complex mocking."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from tools.server_tools import list_servers
from utils.logger import get_logger
from utils.token_manager import TokenManager, get_token_manager


@pytest.fixture
def temp_config_file():
    """Create a temporary token configuration file for testing."""
    config_data = {
        'ap1': {'testworkspace': 'test-token-ap1'},
        'us1': {'testworkspace': 'test-token-us1'},
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config_data, f)
        temp_file = f.name

    # Set environment variable to use this config file
    original_env = os.environ.get('ALPACON_MCP_CONFIG_FILE')
    os.environ['ALPACON_MCP_CONFIG_FILE'] = temp_file

    yield temp_file

    # Cleanup
    os.unlink(temp_file)
    if original_env is not None:
        os.environ['ALPACON_MCP_CONFIG_FILE'] = original_env
    else:
        os.environ.pop('ALPACON_MCP_CONFIG_FILE', None)


class TestTokenManagement:
    def test_token_configuration_loading(self, temp_config_file):
        tm = TokenManager()

        # Test token retrieval
        token_ap1 = tm.get_token('ap1', 'testworkspace')
        token_us1 = tm.get_token('us1', 'testworkspace')

        assert token_ap1 == 'test-token-ap1'
        assert token_us1 == 'test-token-us1'

        # Test non-existent token
        token_nonexistent = tm.get_token('nonexistent', 'testworkspace')
        assert token_nonexistent is None

    def test_token_manager_singleton(self):
        tm1 = get_token_manager()
        tm2 = get_token_manager()

        # Should be the same instance
        assert tm1 is tm2

    @pytest.mark.asyncio
    async def test_missing_token_error_flow(self, temp_config_file):
        # Try to use a workspace/region combination that doesn't exist
        result = await list_servers(workspace='nonexistent_workspace', region='ap1')

        # Should return error status
        assert result['status'] == 'error'
        assert 'No token found' in result['message']


class TestModuleImports:
    """Every module imports successfully.
    Imports stay local: a failing import should fail one test, not collection.
    """

    def test_server_tools_import(self):
        from tools import server_tools

        # Check required functions exist
        assert hasattr(server_tools, 'list_servers')
        assert hasattr(server_tools, 'get_server')
        assert hasattr(server_tools, 'list_server_notes')
        assert hasattr(server_tools, 'create_server_note')

    def test_iam_tools_import(self):
        from tools import iam_tools

        # Check required functions exist
        assert hasattr(iam_tools, 'list_iam_users')
        assert hasattr(iam_tools, 'get_iam_user')
        assert hasattr(iam_tools, 'create_iam_user')
        assert hasattr(iam_tools, 'list_iam_groups')

    def test_http_client_import(self):
        from utils import http_client

        # Check client object exists
        assert hasattr(http_client, 'http_client')
        assert hasattr(http_client.http_client, 'get')
        assert hasattr(http_client.http_client, 'post')
        assert hasattr(http_client.http_client, 'patch')
        assert hasattr(http_client.http_client, 'delete')

    def test_logger_import(self):
        from utils import logger

        # Check logger function exists
        assert hasattr(logger, 'get_logger')

        # Test logger creation
        test_logger = logger.get_logger('test')
        assert test_logger is not None


class TestMCPServerConfiguration:
    """MCP server configuration and setup.
    Imports stay local: a failing import should fail one test, not collection.
    """

    def test_mcp_server_import(self):
        from server import mcp

        # MCP server should be initialized
        assert mcp is not None

    def test_main_entry_point(self):
        from main import main

        # Main function should exist
        assert callable(main)


class TestUtilityFunctions:
    def test_logger_functionality(self):
        logger1 = get_logger('module1')
        logger2 = get_logger('module2')
        logger3 = get_logger('module1')  # Same name

        # Different names should create different loggers
        assert logger1.name != logger2.name

        # Same names should return same logger
        assert logger1 is logger3

    def test_token_manager_methods(self):
        tm = TokenManager()

        # Check required methods exist
        assert hasattr(tm, 'get_token')
        assert hasattr(tm, 'set_token')
        assert hasattr(tm, 'remove_token')

        # Test basic functionality without file operations
        assert tm.get_token('nonexistent', 'workspace') is None


class TestProjectStructure:
    def test_required_files_exist(self):
        project_root = Path(__file__).parent.parent

        # Core files
        assert (project_root / 'main.py').exists()
        assert (project_root / 'server.py').exists()
        assert (project_root / 'pyproject.toml').exists()

        # Tool modules
        tools_dir = project_root / 'tools'
        assert tools_dir.exists()
        assert (tools_dir / 'server_tools.py').exists()
        assert (tools_dir / 'iam_tools.py').exists()

        # Utility modules
        utils_dir = project_root / 'utils'
        assert utils_dir.exists()
        assert (utils_dir / 'http_client.py').exists()
        assert (utils_dir / 'token_manager.py').exists()
        assert (utils_dir / 'logger.py').exists()

    def test_documentation_files_exist(self):
        project_root = Path(__file__).parent.parent

        # Documentation
        assert (project_root / 'README.md').exists()

        # Docs directory
        docs_dir = project_root / 'docs'
        if docs_dir.exists():
            assert (docs_dir / 'api-reference.md').exists()


class TestClaudePluginManifests:
    project_root = Path(__file__).parent.parent

    def test_plugin_mcp_json_points_at_hosted_server_over_http(self):
        mcp_json = self.project_root / 'plugins' / 'alpacon' / '.mcp.json'

        config = json.loads(mcp_json.read_text())

        assert config == {
            'mcpServers': {
                'alpacon': {'type': 'http', 'url': 'https://mcp.alpacon.io/mcp'}
            }
        }

    def test_marketplace_entries_resolve_to_a_plugin_of_the_same_name(self):
        marketplace = self.project_root / '.claude-plugin' / 'marketplace.json'

        entries = json.loads(marketplace.read_text())['plugins']

        assert entries
        for entry in entries:
            manifest = (
                self.project_root / entry['source'] / '.claude-plugin' / 'plugin.json'
            )
            assert json.loads(manifest.read_text())['name'] == entry['name']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
