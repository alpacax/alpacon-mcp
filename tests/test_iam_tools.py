"""
Unit tests for IAM tools module.

Tests all IAM management functions including user, group, role, and permission management.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tools.iam_tools import (
    iam_users_list,
    iam_user_get,
    iam_user_create,
    iam_user_update,
    iam_user_delete,
    iam_user_permissions_get,
    iam_user_assign_role,
    iam_groups_list,
    iam_group_create,
    iam_roles_list,
    iam_permissions_list
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.iam_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.patch = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('tools.iam_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        yield mock_manager


@pytest.fixture
def sample_user():
    """Sample user data for testing."""
    return {
        "id": "user-123",
        "username": "testuser",
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "User",
        "is_active": True,
        "groups": ["group-1"],
        "date_joined": "2024-01-01T00:00:00Z"
    }


@pytest.fixture
def sample_users_list():
    """Sample users list response for testing."""
    return {
        "count": 25,
        "next": "https://workspace.ap1.alpacon.io/api/iam/users/?page=2",
        "previous": None,
        "results": [
            {
                "id": "user-123",
                "username": "testuser1",
                "email": "test1@example.com",
                "first_name": "Test",
                "last_name": "User1",
                "is_active": True,
                "groups": ["group-1"]
            },
            {
                "id": "user-456",
                "username": "testuser2",
                "email": "test2@example.com",
                "first_name": "Test",
                "last_name": "User2",
                "is_active": True,
                "groups": ["group-2"]
            }
        ]
    }


class TestIAMUsersManagement:
    """Test user management functions."""

    @pytest.mark.asyncio
    async def test_iam_users_list_success(self, mock_http_client, mock_token_manager, sample_users_list):
        """Test successful users list retrieval."""
        mock_http_client.get.return_value = sample_users_list

        result = await iam_users_list(
            workspace="testworkspace",
            region="ap1",
            page=1,
            page_size=20
        )

        assert result["status"] == "success"
        assert result["data"] == sample_users_list
        assert len(result["data"]["results"]) == 2

        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/users/",
            token="test-token",
            params={"page": 1, "page_size": 20}
        )

    @pytest.mark.asyncio
    async def test_iam_users_list_no_token(self, mock_http_client, mock_token_manager):
        """Test users list with no token."""
        mock_token_manager.get_token.return_value = None

        result = await iam_users_list(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_iam_users_list_pagination(self, mock_http_client, mock_token_manager, sample_users_list):
        """Test users list with pagination."""
        mock_http_client.get.return_value = sample_users_list

        result = await iam_users_list(
            workspace="testworkspace",
            page=2,
            page_size=50
        )

        assert result["status"] == "success"
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/users/",
            token="test-token",
            params={"page": 2, "page_size": 50}
        )

    @pytest.mark.asyncio
    async def test_iam_user_get_success(self, mock_http_client, mock_token_manager, sample_user):
        """Test successful user retrieval."""
        mock_http_client.get.return_value = sample_user

        result = await iam_user_get(
            user_id="user-123",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["data"] == sample_user

        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/users/user-123/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_iam_user_create_success(self, mock_http_client, mock_token_manager, sample_user):
        """Test successful user creation."""
        mock_http_client.post.return_value = sample_user

        result = await iam_user_create(
            username="testuser",
            email="test@example.com",
            first_name="Test",
            last_name="User",
            workspace="testworkspace",
            groups=["group-1"]
        )

        assert result["status"] == "success"
        assert result["data"] == sample_user

        expected_data = {
            "username": "testuser",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "is_active": True,
            "groups": ["group-1"]
        }

        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/users/",
            token="test-token",
            data=expected_data
        )

    @pytest.mark.asyncio
    async def test_iam_user_update_success(self, mock_http_client, mock_token_manager, sample_user):
        """Test successful user update."""
        updated_user = sample_user.copy()
        updated_user["first_name"] = "Updated"
        mock_http_client.patch.return_value = updated_user

        result = await iam_user_update(
            user_id="user-123",
            workspace="testworkspace",
            first_name="Updated",
            is_active=True
        )

        assert result["status"] == "success"
        assert result["data"]["first_name"] == "Updated"

        expected_data = {
            "first_name": "Updated",
            "is_active": True
        }

        mock_http_client.patch.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/users/user-123/",
            token="test-token",
            data=expected_data
        )

    @pytest.mark.asyncio
    async def test_iam_user_delete_success(self, mock_http_client, mock_token_manager):
        """Test successful user deletion."""
        mock_http_client.delete.return_value = {"message": "User deleted successfully"}

        result = await iam_user_delete(
            user_id="user-123",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["data"]["message"] == "User deleted successfully"
        assert result["user_id"] == "user-123"

        mock_http_client.delete.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/users/user-123/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_iam_user_permissions_get_success(self, mock_http_client, mock_token_manager):
        """Test successful user permissions retrieval."""
        permissions_data = {
            "effective_permissions": [
                {"name": "servers.view", "codename": "view_server"},
                {"name": "users.create", "codename": "add_user"}
            ],
            "group_permissions": [
                {"group": "admins", "permissions": ["servers.view", "users.create"]}
            ]
        }
        mock_http_client.get.return_value = permissions_data

        result = await iam_user_permissions_get(
            user_id="user-123",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["data"] == permissions_data
        assert len(result["data"]["effective_permissions"]) == 2

        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/users/user-123/permissions/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_iam_user_assign_role_success(self, mock_http_client, mock_token_manager):
        """Test successful user role assignment."""
        role_data = {"message": "Role assigned successfully"}
        mock_http_client.post.return_value = role_data

        result = await iam_user_assign_role(
            user_id="user-123",
            role_id="role-456",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["data"]["message"] == "Role assigned successfully"
        assert result["user_id"] == "user-123"
        assert result["role_id"] == "role-456"

        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/users/user-123/roles/",
            token="test-token",
            data={"role_id": "role-456"}
        )


class TestIAMGroupsManagement:
    """Test group management functions."""

    @pytest.mark.asyncio
    async def test_iam_groups_list_success(self, mock_http_client, mock_token_manager):
        """Test successful groups list retrieval."""
        groups_data = {
            "count": 3,
            "results": [
                {"id": "group-1", "name": "admins", "permissions": ["servers.view"]},
                {"id": "group-2", "name": "users", "permissions": ["servers.view"]},
                {"id": "group-3", "name": "guests", "permissions": []}
            ]
        }
        mock_http_client.get.return_value = groups_data

        result = await iam_groups_list(workspace="testworkspace")

        assert result["status"] == "success"
        assert result["data"] == groups_data
        assert len(result["data"]["results"]) == 3

        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/groups/",
            token="test-token",
            params={}
        )

    @pytest.mark.asyncio
    async def test_iam_group_create_success(self, mock_http_client, mock_token_manager):
        """Test successful group creation."""
        group_data = {
            "id": "group-123",
            "name": "developers",
            "permissions": ["servers.view", "code.deploy"]
        }
        mock_http_client.post.return_value = group_data

        result = await iam_group_create(
            name="developers",
            workspace="testworkspace",
            permissions=["servers.view", "code.deploy"]
        )

        assert result["status"] == "success"
        assert result["data"] == group_data

        expected_data = {
            "name": "developers",
            "permissions": ["servers.view", "code.deploy"]
        }

        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/groups/",
            token="test-token",
            data=expected_data
        )


class TestIAMRolesAndPermissions:
    """Test roles and permissions functions."""

    @pytest.mark.asyncio
    async def test_iam_roles_list_success(self, mock_http_client, mock_token_manager):
        """Test successful roles list retrieval."""
        roles_data = {
            "count": 2,
            "results": [
                {"id": "role-1", "name": "admin", "permissions": ["*"]},
                {"id": "role-2", "name": "viewer", "permissions": ["*.view"]}
            ]
        }
        mock_http_client.get.return_value = roles_data

        result = await iam_roles_list(workspace="testworkspace")

        assert result["status"] == "success"
        assert result["data"] == roles_data
        assert len(result["data"]["results"]) == 2

        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/roles/",
            token="test-token",
            params={}
        )

    @pytest.mark.asyncio
    async def test_iam_permissions_list_success(self, mock_http_client, mock_token_manager):
        """Test successful permissions list retrieval."""
        permissions_data = {
            "count": 10,
            "results": [
                {"name": "servers.view", "codename": "view_server"},
                {"name": "servers.create", "codename": "add_server"},
                {"name": "users.view", "codename": "view_user"},
                {"name": "users.create", "codename": "add_user"}
            ]
        }
        mock_http_client.get.return_value = permissions_data

        result = await iam_permissions_list(workspace="testworkspace")

        assert result["status"] == "success"
        assert result["data"] == permissions_data
        assert len(result["data"]["results"]) == 4

        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/iam/permissions/",
            token="test-token",
            params={}
        )


class TestErrorHandling:
    """Test error handling across IAM functions."""

    @pytest.mark.asyncio
    async def test_http_error_handling(self, mock_http_client, mock_token_manager):
        """Test HTTP error handling."""
        mock_http_client.get.side_effect = Exception("HTTP 404: Not Found")

        result = await iam_user_get(
            user_id="nonexistent",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "HTTP 404" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_token_error(self, mock_http_client, mock_token_manager):
        """Test missing token error handling."""
        mock_token_manager.get_token.return_value = None

        result = await iam_user_create(
            username="test",
            email="test@example.com",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.post.assert_not_called()


class TestParameterValidation:
    """Test parameter validation and edge cases."""

    @pytest.mark.asyncio
    async def test_pagination_parameters(self, mock_http_client, mock_token_manager):
        """Test pagination parameter handling."""
        mock_http_client.get.return_value = {"count": 0, "results": []}

        # Test with page and page_size
        await iam_users_list(
            workspace="test",
            page=2,
            page_size=50
        )

        mock_http_client.get.assert_called_with(
            region="ap1",
            workspace="test",
            endpoint="/api/iam/users/",
            token="test-token",
            params={"page": 2, "page_size": 50}
        )

    @pytest.mark.asyncio
    async def test_optional_parameters(self, mock_http_client, mock_token_manager, sample_user):
        """Test functions with optional parameters."""
        mock_http_client.post.return_value = sample_user

        # Test user creation with minimal required parameters
        await iam_user_create(
            username="test",
            email="test@example.com",
            workspace="test"
        )

        expected_data = {
            "username": "test",
            "email": "test@example.com",
            "is_active": True
        }

        mock_http_client.post.assert_called_with(
            region="ap1",
            workspace="test",
            endpoint="/api/iam/users/",
            token="test-token",
            data=expected_data
        )

    @pytest.mark.asyncio
    async def test_different_regions(self, mock_http_client, mock_token_manager):
        """Test with different regions."""
        mock_http_client.get.return_value = {"count": 0, "results": []}

        # Test users list with different region
        await iam_users_list(
            workspace="test",
            region="us1"
        )

        mock_http_client.get.assert_called_with(
            region="us1",
            workspace="test",
            endpoint="/api/iam/users/",
            token="test-token",
            params={}
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])