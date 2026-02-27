"""
Unit tests for IAM tools module.

Tests all IAM management functions including user and group management.
"""
import pytest
from unittest.mock import AsyncMock, patch
from tools.iam_tools import (
    list_iam_users,
    get_iam_user,
    create_iam_user,
    update_iam_user,
    delete_iam_user,
    list_iam_groups,
    create_iam_group,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.iam_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.patch = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
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
    async def test_list_iam_users_success(self, mock_http_client, mock_token_manager, sample_users_list):
        """Test successful users list retrieval."""
        mock_http_client.get.return_value = sample_users_list

        result = await list_iam_users(
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
    async def test_list_iam_users_no_token(self, mock_http_client, mock_token_manager):
        """Test users list with no token."""
        mock_token_manager.get_token.return_value = None

        result = await list_iam_users(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_iam_users_pagination(self, mock_http_client, mock_token_manager, sample_users_list):
        """Test users list with pagination."""
        mock_http_client.get.return_value = sample_users_list

        result = await list_iam_users(
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
    async def test_get_iam_user_success(self, mock_http_client, mock_token_manager, sample_user):
        """Test successful user retrieval."""
        mock_http_client.get.return_value = sample_user

        result = await get_iam_user(
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
    async def test_create_iam_user_success(self, mock_http_client, mock_token_manager, sample_user):
        """Test successful user creation."""
        mock_http_client.post.return_value = sample_user

        result = await create_iam_user(
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
    async def test_update_iam_user_success(self, mock_http_client, mock_token_manager, sample_user):
        """Test successful user update."""
        updated_user = sample_user.copy()
        updated_user["first_name"] = "Updated"
        mock_http_client.patch.return_value = updated_user

        result = await update_iam_user(
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
    async def test_delete_iam_user_success(self, mock_http_client, mock_token_manager):
        """Test successful user deletion."""
        mock_http_client.delete.return_value = {"message": "User deleted successfully"}

        result = await delete_iam_user(
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


class TestIAMGroupsManagement:
    """Test group management functions."""

    @pytest.mark.asyncio
    async def test_list_iam_groups_success(self, mock_http_client, mock_token_manager):
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

        result = await list_iam_groups(workspace="testworkspace")

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
    async def test_create_iam_group_success(self, mock_http_client, mock_token_manager):
        """Test successful group creation."""
        group_data = {
            "id": "group-123",
            "name": "developers",
            "permissions": ["servers.view", "code.deploy"]
        }
        mock_http_client.post.return_value = group_data

        result = await create_iam_group(
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


class TestErrorHandling:
    """Test error handling across IAM functions."""

    @pytest.mark.asyncio
    async def test_http_error_handling(self, mock_http_client, mock_token_manager):
        """Test HTTP error handling."""
        mock_http_client.get.side_effect = Exception("HTTP 404: Not Found")

        result = await get_iam_user(
            user_id="nonexistent",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "HTTP 404" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_token_error(self, mock_http_client, mock_token_manager):
        """Test missing token error handling."""
        mock_token_manager.get_token.return_value = None

        result = await create_iam_user(
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

        await list_iam_users(
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

        await create_iam_user(
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

        await list_iam_users(
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
