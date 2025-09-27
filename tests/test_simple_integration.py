"""
Simple integration tests for Alpacon MCP Server.

Tests basic integration and configuration loading without complex mocking.
"""
import pytest
import json
import os
import tempfile
from pathlib import Path


@pytest.fixture
def temp_config_file():
    """Create a temporary token configuration file for testing."""
    config_data = {
        "ap1": {
            "testworkspace": "test-token-ap1"
        },
        "us1": {
            "testworkspace": "test-token-us1"
        }
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
    """Test token management functionality."""

    def test_token_configuration_loading(self, temp_config_file):
        """Test token configuration file loading."""
        from utils.token_manager import TokenManager

        tm = TokenManager()

        # Test token retrieval
        token_ap1 = tm.get_token("ap1", "testworkspace")
        token_us1 = tm.get_token("us1", "testworkspace")

        assert token_ap1 == "test-token-ap1"
        assert token_us1 == "test-token-us1"

        # Test non-existent token
        token_nonexistent = tm.get_token("nonexistent", "testworkspace")
        assert token_nonexistent is None

    def test_token_manager_singleton(self):
        """Test that token manager works as expected."""
        from utils.token_manager import get_token_manager

        tm1 = get_token_manager()
        tm2 = get_token_manager()

        # Should be the same instance
        assert tm1 is tm2

    @pytest.mark.asyncio
    async def test_missing_token_error_flow(self, temp_config_file):
        """Test error handling when token is missing."""
        from tools.server_tools import servers_list

        # Try to use a workspace/region combination that doesn't exist
        result = await servers_list(
            workspace="nonexistent_workspace",
            region="ap1"
        )

        # Should return error status
        assert result["status"] == "error"
        assert "Authentication failed" in result["message"]


class TestModuleImports:
    """Test that all modules can be imported successfully."""

    def test_server_tools_import(self):
        """Test server tools module import."""
        from tools import server_tools

        # Check required functions exist
        assert hasattr(server_tools, 'servers_list')
        assert hasattr(server_tools, 'server_get')
        assert hasattr(server_tools, 'server_notes_list')
        assert hasattr(server_tools, 'server_note_create')

    def test_iam_tools_import(self):
        """Test IAM tools module import."""
        from tools import iam_tools

        # Check required functions exist
        assert hasattr(iam_tools, 'iam_users_list')
        assert hasattr(iam_tools, 'iam_user_get')
        assert hasattr(iam_tools, 'iam_user_create')
        assert hasattr(iam_tools, 'iam_groups_list')

    def test_http_client_import(self):
        """Test HTTP client import."""
        from utils import http_client

        # Check client object exists
        assert hasattr(http_client, 'http_client')
        assert hasattr(http_client.http_client, 'get')
        assert hasattr(http_client.http_client, 'post')
        assert hasattr(http_client.http_client, 'patch')
        assert hasattr(http_client.http_client, 'delete')

    def test_logger_import(self):
        """Test logger utility import."""
        from utils import logger

        # Check logger function exists
        assert hasattr(logger, 'get_logger')

        # Test logger creation
        test_logger = logger.get_logger("test")
        assert test_logger is not None


class TestMCPServerConfiguration:
    """Test MCP server configuration and setup."""

    def test_mcp_server_import(self):
        """Test MCP server can be imported."""
        from server import mcp

        # MCP server should be initialized
        assert mcp is not None

    def test_main_entry_point(self):
        """Test main entry point exists."""
        from main import main

        # Main function should exist
        assert callable(main)


class TestUtilityFunctions:
    """Test utility functions work correctly."""

    def test_logger_functionality(self):
        """Test logger creates different loggers."""
        from utils.logger import get_logger

        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        logger3 = get_logger("module1")  # Same name

        # Different names should create different loggers
        assert logger1.name != logger2.name

        # Same names should return same logger
        assert logger1 is logger3

    def test_token_manager_methods(self):
        """Test token manager has required methods."""
        from utils.token_manager import TokenManager

        tm = TokenManager()

        # Check required methods exist
        assert hasattr(tm, 'get_token')
        assert hasattr(tm, 'set_token')
        assert hasattr(tm, 'remove_token')

        # Test basic functionality without file operations
        assert tm.get_token("nonexistent", "workspace") is None


class TestProjectStructure:
    """Test project structure and files."""

    def test_required_files_exist(self):
        """Test that required project files exist."""
        project_root = Path(__file__).parent.parent

        # Core files
        assert (project_root / "main.py").exists()
        assert (project_root / "server.py").exists()
        assert (project_root / "pyproject.toml").exists()
        assert (project_root / "CLAUDE.md").exists()

        # Tool modules
        tools_dir = project_root / "tools"
        assert tools_dir.exists()
        assert (tools_dir / "server_tools.py").exists()
        assert (tools_dir / "iam_tools.py").exists()

        # Utility modules
        utils_dir = project_root / "utils"
        assert utils_dir.exists()
        assert (utils_dir / "http_client.py").exists()
        assert (utils_dir / "token_manager.py").exists()
        assert (utils_dir / "logger.py").exists()

    def test_documentation_files_exist(self):
        """Test that documentation files exist."""
        project_root = Path(__file__).parent.parent

        # Documentation
        assert (project_root / "README.md").exists()

        # Docs directory
        docs_dir = project_root / "docs"
        if docs_dir.exists():
            assert (docs_dir / "api-reference.md").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])