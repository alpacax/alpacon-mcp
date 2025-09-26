"""
Unit tests for workspace_tools module.

Tests workspace management functionality including workspace listing,
user settings management, and user profile operations.
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.workspace_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        mock_client.patch = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('tools.workspace_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        mock_manager.get_all_tokens.return_value = {
            "ap1": {
                "production": {"token": "token1"},
                "staging": {"token": "token2"},
                "development": {"token": "token3"}
            },
            "us1": {
                "backup": {"token": "token4"},
                "disaster-recovery": {"token": "token5"}
            },
            "eu1": {
                "compliance": {"token": "token6"}
            }
        }
        yield mock_manager


class TestWorkspaceList:
    """Test workspace_list function."""

    @pytest.mark.asyncio
    async def test_workspace_list_success(self, mock_http_client, mock_token_manager):
        """Test successful workspace listing."""
        from tools.workspace_tools import workspace_list

        result = await workspace_list(region="ap1")

        # Verify response structure
        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert "data" in result
        assert "workspaces" in result["data"]

        # Verify workspace data
        workspaces = result["data"]["workspaces"]
        assert len(workspaces) == 3  # production, staging, development

        # Check specific workspace details
        workspace_names = [ws["workspace"] for ws in workspaces]
        assert "production" in workspace_names
        assert "staging" in workspace_names
        assert "development" in workspace_names

        # Verify workspace structure
        production_ws = next(ws for ws in workspaces if ws["workspace"] == "production")
        assert production_ws["region"] == "ap1"
        assert production_ws["has_token"] == True
        assert production_ws["domain"] == "production.ap1.alpacon.io"

        # Verify token manager was called
        mock_token_manager.get_all_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_workspace_list_different_region(self, mock_http_client, mock_token_manager):
        """Test workspace listing for different region."""
        from tools.workspace_tools import workspace_list

        result = await workspace_list(region="us1")

        assert result["status"] == "success"
        assert result["region"] == "us1"

        workspaces = result["data"]["workspaces"]
        assert len(workspaces) == 2  # backup, disaster-recovery

        workspace_names = [ws["workspace"] for ws in workspaces]
        assert "backup" in workspace_names
        assert "disaster-recovery" in workspace_names

        # Verify domain format
        backup_ws = next(ws for ws in workspaces if ws["workspace"] == "backup")
        assert backup_ws["domain"] == "backup.us1.alpacon.io"

    @pytest.mark.asyncio
    async def test_workspace_list_empty_region(self, mock_http_client, mock_token_manager):
        """Test workspace listing for region with no workspaces."""
        from tools.workspace_tools import workspace_list

        # Mock empty tokens for unknown region
        mock_token_manager.get_all_tokens.return_value = {
            "ap1": {"production": {"token": "token1"}}
        }

        result = await workspace_list(region="nonexistent")

        assert result["status"] == "success"
        assert result["region"] == "nonexistent"
        assert result["data"]["workspaces"] == []

    @pytest.mark.asyncio
    async def test_workspace_list_token_manager_error(self, mock_http_client, mock_token_manager):
        """Test workspace listing when token manager fails."""
        from tools.workspace_tools import workspace_list

        mock_token_manager.get_all_tokens.side_effect = Exception("Token manager error")

        result = await workspace_list(region="ap1")

        assert result["status"] == "error"
        assert "Failed to get workspaces list" in result["message"]
        assert "Token manager error" in result["message"]

    @pytest.mark.asyncio
    async def test_workspace_list_workspace_without_token(self, mock_http_client, mock_token_manager):
        """Test workspace listing with workspace that has no token."""
        from tools.workspace_tools import workspace_list

        # Mock tokens with empty token value
        mock_token_manager.get_all_tokens.return_value = {
            "ap1": {
                "production": {"token": "token1"},
                "staging": {"token": ""},  # Empty token
                "development": {}  # No token key
            }
        }

        result = await workspace_list(region="ap1")

        assert result["status"] == "success"
        workspaces = result["data"]["workspaces"]

        # Find workspaces and check token status
        production_ws = next(ws for ws in workspaces if ws["workspace"] == "production")
        staging_ws = next(ws for ws in workspaces if ws["workspace"] == "staging")
        development_ws = next(ws for ws in workspaces if ws["workspace"] == "development")

        assert production_ws["has_token"] == True
        assert staging_ws["has_token"] == False
        assert development_ws["has_token"] == False


class TestUserSettingsGet:
    """Test user_settings_get function."""

    @pytest.mark.asyncio
    async def test_user_settings_get_success(self, mock_http_client, mock_token_manager):
        """Test successful user settings retrieval."""
        from tools.workspace_tools import user_settings_get

        # Mock successful response
        mock_http_client.get.return_value = {
            "theme": "dark",
            "language": "en",
            "timezone": "UTC",
            "notifications": {
                "email": True,
                "sms": False,
                "push": True
            },
            "preferences": {
                "default_region": "ap1",
                "dashboard_layout": "grid",
                "items_per_page": 25
            }
        }

        result = await user_settings_get(
            workspace="testworkspace",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result
        assert result["data"]["theme"] == "dark"
        assert result["data"]["notifications"]["email"] == True

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/user/settings/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_user_settings_get_no_token(self, mock_http_client, mock_token_manager):
        """Test user settings get when no token is available."""
        from tools.workspace_tools import user_settings_get

        mock_token_manager.get_token.return_value = None

        result = await user_settings_get(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_settings_get_http_error(self, mock_http_client, mock_token_manager):
        """Test user settings get with HTTP error."""
        from tools.workspace_tools import user_settings_get

        mock_http_client.get.side_effect = Exception("HTTP 403 Forbidden")

        result = await user_settings_get(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "error"
        assert "Failed to get user settings" in result["message"]
        assert "403" in result["message"]

    @pytest.mark.asyncio
    async def test_user_settings_get_different_region(self, mock_http_client, mock_token_manager):
        """Test user settings get with different region."""
        from tools.workspace_tools import user_settings_get

        mock_http_client.get.return_value = {"theme": "light"}

        result = await user_settings_get(
            workspace="eu-workspace",
            region="eu1"
        )

        assert result["status"] == "success"
        assert result["region"] == "eu1"
        assert result["workspace"] == "eu-workspace"

        # Verify correct region was used
        call_args = mock_http_client.get.call_args
        assert call_args[1]["region"] == "eu1"
        assert call_args[1]["workspace"] == "eu-workspace"


class TestUserSettingsUpdate:
    """Test user_settings_update function."""

    @pytest.mark.asyncio
    async def test_user_settings_update_success(self, mock_http_client, mock_token_manager):
        """Test successful user settings update."""
        from tools.workspace_tools import user_settings_update

        # Mock successful response
        mock_http_client.patch.return_value = {
            "theme": "light",
            "language": "es",
            "timezone": "Europe/Madrid",
            "updated_at": "2024-01-01T12:00:00Z"
        }

        settings_to_update = {
            "theme": "light",
            "language": "es",
            "timezone": "Europe/Madrid"
        }

        result = await user_settings_update(
            settings=settings_to_update,
            workspace="testworkspace",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["settings"] == settings_to_update
        assert "data" in result
        assert result["data"]["theme"] == "light"
        assert result["data"]["language"] == "es"

        # Verify HTTP client was called correctly
        mock_http_client.patch.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/user/settings/",
            token="test-token",
            data=settings_to_update
        )

    @pytest.mark.asyncio
    async def test_user_settings_update_partial(self, mock_http_client, mock_token_manager):
        """Test partial user settings update."""
        from tools.workspace_tools import user_settings_update

        mock_http_client.patch.return_value = {
            "theme": "dark",
            "updated_at": "2024-01-01T12:00:00Z"
        }

        # Update only theme
        settings_to_update = {"theme": "dark"}

        result = await user_settings_update(
            settings=settings_to_update,
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["settings"] == {"theme": "dark"}
        assert result["data"]["theme"] == "dark"

        # Verify only theme was sent
        call_args = mock_http_client.patch.call_args
        assert call_args[1]["data"] == {"theme": "dark"}

    @pytest.mark.asyncio
    async def test_user_settings_update_complex_data(self, mock_http_client, mock_token_manager):
        """Test user settings update with complex nested data."""
        from tools.workspace_tools import user_settings_update

        mock_http_client.patch.return_value = {"status": "updated"}

        complex_settings = {
            "notifications": {
                "email": False,
                "sms": True,
                "push": True,
                "channels": ["alerts", "reports"]
            },
            "preferences": {
                "dashboard": {
                    "layout": "list",
                    "refresh_interval": 30
                },
                "filters": ["status:active", "region:ap1"]
            }
        }

        result = await user_settings_update(
            settings=complex_settings,
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["settings"] == complex_settings

        # Verify complex data was sent correctly
        call_args = mock_http_client.patch.call_args
        assert call_args[1]["data"] == complex_settings

    @pytest.mark.asyncio
    async def test_user_settings_update_no_token(self, mock_http_client, mock_token_manager):
        """Test user settings update when no token is available."""
        from tools.workspace_tools import user_settings_update

        mock_token_manager.get_token.return_value = None

        result = await user_settings_update(
            settings={"theme": "dark"},
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_settings_update_http_error(self, mock_http_client, mock_token_manager):
        """Test user settings update with HTTP error."""
        from tools.workspace_tools import user_settings_update

        mock_http_client.patch.side_effect = Exception("HTTP 400 Bad Request")

        result = await user_settings_update(
            settings={"invalid_key": "invalid_value"},
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "error"
        assert "Failed to update user settings" in result["message"]
        assert "400" in result["message"]

    @pytest.mark.asyncio
    async def test_user_settings_update_empty_settings(self, mock_http_client, mock_token_manager):
        """Test user settings update with empty settings."""
        from tools.workspace_tools import user_settings_update

        mock_http_client.patch.return_value = {"status": "no changes"}

        result = await user_settings_update(
            settings={},
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["settings"] == {}

        # Verify empty data was sent
        call_args = mock_http_client.patch.call_args
        assert call_args[1]["data"] == {}


class TestUserProfileGet:
    """Test user_profile_get function."""

    @pytest.mark.asyncio
    async def test_user_profile_get_success(self, mock_http_client, mock_token_manager):
        """Test successful user profile retrieval."""
        from tools.workspace_tools import user_profile_get

        # Mock successful response
        mock_http_client.get.return_value = {
            "id": 12345,
            "username": "testuser",
            "email": "testuser@example.com",
            "first_name": "Test",
            "last_name": "User",
            "is_active": True,
            "is_staff": False,
            "date_joined": "2024-01-01T00:00:00Z",
            "last_login": "2024-01-01T12:00:00Z",
            "permissions": [
                "can_view_servers",
                "can_execute_commands",
                "can_manage_files"
            ],
            "workspace_role": "admin",
            "quota": {
                "storage": 10737418240,  # 10GB
                "used_storage": 1073741824,  # 1GB
                "max_servers": 50,
                "current_servers": 12
            }
        }

        result = await user_profile_get(
            workspace="testworkspace",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify profile data
        profile = result["data"]
        assert profile["id"] == 12345
        assert profile["username"] == "testuser"
        assert profile["email"] == "testuser@example.com"
        assert profile["is_active"] == True
        assert profile["workspace_role"] == "admin"
        assert len(profile["permissions"]) == 3
        assert "quota" in profile
        assert profile["quota"]["max_servers"] == 50

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/user/profile/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_user_profile_get_minimal_data(self, mock_http_client, mock_token_manager):
        """Test user profile get with minimal profile data."""
        from tools.workspace_tools import user_profile_get

        # Mock minimal response
        mock_http_client.get.return_value = {
            "id": 99999,
            "username": "limiteduser",
            "email": "limited@example.com",
            "is_active": True,
            "workspace_role": "viewer"
        }

        result = await user_profile_get(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        profile = result["data"]
        assert profile["id"] == 99999
        assert profile["username"] == "limiteduser"
        assert profile["workspace_role"] == "viewer"

    @pytest.mark.asyncio
    async def test_user_profile_get_no_token(self, mock_http_client, mock_token_manager):
        """Test user profile get when no token is available."""
        from tools.workspace_tools import user_profile_get

        mock_token_manager.get_token.return_value = None

        result = await user_profile_get(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_profile_get_http_error(self, mock_http_client, mock_token_manager):
        """Test user profile get with HTTP error."""
        from tools.workspace_tools import user_profile_get

        mock_http_client.get.side_effect = Exception("HTTP 401 Unauthorized")

        result = await user_profile_get(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "error"
        assert "Failed to get user profile" in result["message"]
        assert "401" in result["message"]

    @pytest.mark.asyncio
    async def test_user_profile_get_different_region(self, mock_http_client, mock_token_manager):
        """Test user profile get with different region."""
        from tools.workspace_tools import user_profile_get

        mock_http_client.get.return_value = {
            "id": 54321,
            "username": "eurouser",
            "workspace_role": "operator"
        }

        result = await user_profile_get(
            workspace="eu-workspace",
            region="eu1"
        )

        assert result["status"] == "success"
        assert result["region"] == "eu1"
        assert result["workspace"] == "eu-workspace"
        assert result["data"]["username"] == "eurouser"

        # Verify correct region was used
        call_args = mock_http_client.get.call_args
        assert call_args[1]["region"] == "eu1"


class TestWorkspaceToolsEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_all_functions_with_different_regions(self, mock_http_client, mock_token_manager):
        """Test all functions with various regions and workspaces."""
        from tools.workspace_tools import user_settings_get, user_settings_update, user_profile_get

        # Mock successful responses
        mock_http_client.get.return_value = {"test": "data"}
        mock_http_client.patch.return_value = {"test": "updated"}

        functions_to_test = [
            (user_settings_get, {}),
            (user_settings_update, {"settings": {"theme": "dark"}}),
            (user_profile_get, {})
        ]

        for func, extra_args in functions_to_test:
            result = await func(
                workspace="us-workspace",
                region="us1",
                **extra_args
            )

            assert result["status"] == "success"
            assert result["workspace"] == "us-workspace"
            assert result["region"] == "us1"

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, mock_http_client, mock_token_manager):
        """Test concurrent workspace operations."""
        import asyncio
        from tools.workspace_tools import user_settings_get, user_profile_get

        # Mock different responses for each call
        def get_side_effect(*args, **kwargs):
            endpoint = kwargs.get('endpoint', '')
            if 'settings' in endpoint:
                return {"theme": "dark"}
            elif 'profile' in endpoint:
                return {"username": "testuser"}
            return {}

        mock_http_client.get.side_effect = get_side_effect

        # Run operations concurrently
        results = await asyncio.gather(
            user_settings_get(workspace="testworkspace", region="ap1"),
            user_profile_get(workspace="testworkspace", region="ap1"),
            return_exceptions=True
        )

        # Verify both operations succeeded
        assert len(results) == 2
        assert all(result["status"] == "success" for result in results)
        assert results[0]["data"]["theme"] == "dark"
        assert results[1]["data"]["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_token_manager_exceptions_in_all_functions(self, mock_http_client, mock_token_manager):
        """Test all functions when token manager raises exceptions."""
        from tools.workspace_tools import user_settings_get, user_settings_update, user_profile_get

        mock_token_manager.get_token.side_effect = Exception("Token service down")

        functions_to_test = [
            (user_settings_get, {}),
            (user_settings_update, {"settings": {"theme": "dark"}}),
            (user_profile_get, {})
        ]

        for func, extra_args in functions_to_test:
            result = await func(
                workspace="testworkspace",
                region="ap1",
                **extra_args
            )

            assert result["status"] == "error"
            assert "Token service down" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])