"""
Unit tests for IAM tools module.

Tests all IAM management functions including user and group management.
"""

from unittest.mock import AsyncMock, patch

import pytest

from tools.iam_tools import (
    add_iam_member,
    assign_application_system_users,
    create_iam_application,
    create_iam_group,
    create_iam_user,
    delete_iam_application,
    delete_iam_group,
    delete_iam_user,
    get_iam_application,
    get_iam_group,
    get_iam_user,
    invite_workspace_user,
    list_iam_applications,
    list_iam_groups,
    list_iam_memberships,
    list_iam_users,
    remove_iam_member,
    unassign_application_system_users,
    update_iam_application,
    update_iam_group,
    update_iam_user,
)

# Valid UUIDs for tools that validate ID format before calling the API
GROUP_ID = '11111111-1111-1111-1111-111111111111'
USER_ID = '22222222-2222-2222-2222-222222222222'
USER_ID_2 = '33333333-3333-3333-3333-333333333333'
MEMBERSHIP_ID = '44444444-4444-4444-4444-444444444444'
APP_ID = '55555555-5555-5555-5555-555555555555'
SYSTEM_USER_ID = '66666666-6666-6666-6666-666666666666'


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
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


@pytest.fixture
def sample_user():
    """Sample user data for testing."""
    return {
        'id': 'user-123',
        'username': 'testuser',
        'email': 'test@example.com',
        'first_name': 'Test',
        'last_name': 'User',
        'is_active': True,
        'num_groups': 1,
        'date_joined': '2024-01-01T00:00:00Z',
    }


@pytest.fixture
def sample_users_list():
    """Sample users list response for testing."""
    return {
        'count': 25,
        'next': 'https://workspace.ap1.alpacon.io/api/iam/users/?page=2',
        'previous': None,
        'results': [
            {
                'id': 'user-123',
                'username': 'testuser1',
                'email': 'test1@example.com',
                'first_name': 'Test',
                'last_name': 'User1',
                'is_active': True,
                'num_groups': 1,
            },
            {
                'id': 'user-456',
                'username': 'testuser2',
                'email': 'test2@example.com',
                'first_name': 'Test',
                'last_name': 'User2',
                'is_active': True,
                'num_groups': 1,
            },
        ],
    }


class TestIAMUsersManagement:
    """Test user management functions."""

    @pytest.mark.asyncio
    async def test_list_iam_users_success(
        self, mock_http_client, mock_token_manager, sample_users_list
    ):
        """Test successful users list retrieval."""
        mock_http_client.get.return_value = sample_users_list

        result = await list_iam_users(
            workspace='testworkspace', region='ap1', page=1, page_size=20
        )

        assert result['status'] == 'success'
        assert result['data'] == sample_users_list
        assert len(result['data']['results']) == 2

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/users/',
            token='test-token',
            params={'page': 1, 'page_size': 20},
        )

    @pytest.mark.asyncio
    async def test_list_iam_users_no_token(self, mock_http_client, mock_token_manager):
        """Test users list with no token."""
        mock_token_manager.get_token.return_value = None

        result = await list_iam_users(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_iam_users_pagination(
        self, mock_http_client, mock_token_manager, sample_users_list
    ):
        """Test users list with pagination."""
        mock_http_client.get.return_value = sample_users_list

        result = await list_iam_users(workspace='testworkspace', page=2, page_size=50)

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/users/',
            token='test-token',
            params={'page': 2, 'page_size': 50},
        )

    @pytest.mark.asyncio
    async def test_get_iam_user_success(
        self, mock_http_client, mock_token_manager, sample_user
    ):
        """Test successful user retrieval."""
        mock_http_client.get.return_value = sample_user

        result = await get_iam_user(user_id=USER_ID, workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data'] == sample_user

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/users/{USER_ID}/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_iam_user_invalid_id(self, mock_http_client, mock_token_manager):
        """Test user retrieval rejects a non-UUID user ID locally."""
        result = await get_iam_user(user_id='not-a-uuid', workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_iam_user_success(
        self, mock_http_client, mock_token_manager, sample_user
    ):
        """Test successful user creation."""
        mock_http_client.post.return_value = sample_user

        result = await create_iam_user(
            username='testuser',
            email='test@example.com',
            first_name='Test',
            last_name='User',
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert result['data'] == sample_user

        expected_data = {
            'username': 'testuser',
            'email': 'test@example.com',
            'first_name': 'Test',
            'last_name': 'User',
            'is_active': True,
        }

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/users/',
            token='test-token',
            data=expected_data,
        )

    @pytest.mark.asyncio
    async def test_update_iam_user_success(
        self, mock_http_client, mock_token_manager, sample_user
    ):
        """Test successful user update."""
        updated_user = sample_user.copy()
        updated_user['first_name'] = 'Updated'
        mock_http_client.patch.return_value = updated_user

        result = await update_iam_user(
            user_id=USER_ID,
            workspace='testworkspace',
            first_name='Updated',
            is_active=True,
        )

        assert result['status'] == 'success'
        assert result['data']['first_name'] == 'Updated'

        expected_data = {'first_name': 'Updated', 'is_active': True}

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/users/{USER_ID}/',
            token='test-token',
            data=expected_data,
        )

    @pytest.mark.asyncio
    async def test_update_iam_user_invalid_id(
        self, mock_http_client, mock_token_manager
    ):
        """Test user update rejects a non-UUID user ID locally."""
        result = await update_iam_user(
            user_id='not-a-uuid', workspace='testworkspace', first_name='Updated'
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_iam_user_success(self, mock_http_client, mock_token_manager):
        """Test successful user deletion."""
        mock_http_client.delete.return_value = {'message': 'User deleted successfully'}

        result = await delete_iam_user(user_id=USER_ID, workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data']['message'] == 'User deleted successfully'
        assert result['user_id'] == USER_ID

        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/users/{USER_ID}/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_delete_iam_user_invalid_id(
        self, mock_http_client, mock_token_manager
    ):
        """Test user deletion rejects a non-UUID user ID locally."""
        result = await delete_iam_user(user_id='not-a-uuid', workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.delete.assert_not_called()


class TestIAMGroupsManagement:
    """Test group management functions."""

    @pytest.mark.asyncio
    async def test_list_iam_groups_success(self, mock_http_client, mock_token_manager):
        """Test successful groups list retrieval."""
        groups_data = {
            'count': 3,
            'results': [
                {'id': 'group-1', 'name': 'admins', 'num_members': 2},
                {'id': 'group-2', 'name': 'users', 'num_members': 5},
                {'id': 'group-3', 'name': 'guests', 'num_members': 0},
            ],
        }
        mock_http_client.get.return_value = groups_data

        result = await list_iam_groups(workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data'] == groups_data
        assert len(result['data']['results']) == 3

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/groups/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_create_iam_group_success(self, mock_http_client, mock_token_manager):
        """Test successful group creation."""
        group_data = {
            'id': GROUP_ID,
            'name': 'developers',
            'display_name': 'Developers',
            'description': 'Development team',
        }
        mock_http_client.post.return_value = group_data

        result = await create_iam_group(
            name='developers',
            workspace='testworkspace',
            display_name='Developers',
            description='Development team',
        )

        assert result['status'] == 'success'
        assert result['data'] == group_data

        expected_data = {
            'name': 'developers',
            'display_name': 'Developers',
            'description': 'Development team',
        }

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/groups/',
            token='test-token',
            data=expected_data,
        )

    @pytest.mark.asyncio
    async def test_create_iam_group_invalid_name(
        self, mock_http_client, mock_token_manager
    ):
        """Test group creation rejects an invalid name locally."""
        for invalid_name in ('Developers', 'dev team', 'dev.team', ''):
            result = await create_iam_group(
                name=invalid_name, workspace='testworkspace'
            )

            assert result['status'] == 'error'

        mock_http_client.post.assert_not_called()


class TestErrorHandling:
    """Test error handling across IAM functions."""

    @pytest.mark.asyncio
    async def test_http_error_handling(self, mock_http_client, mock_token_manager):
        """Test HTTP error handling."""
        mock_http_client.get.side_effect = Exception('HTTP 404: Not Found')

        result = await get_iam_user(user_id=USER_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'HTTP 404' in result['message']

    @pytest.mark.asyncio
    async def test_missing_token_error(self, mock_http_client, mock_token_manager):
        """Test missing token error handling."""
        mock_token_manager.get_token.return_value = None

        result = await create_iam_user(
            username='test', email='test@example.com', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()


class TestParameterValidation:
    """Test parameter validation and edge cases."""

    @pytest.mark.asyncio
    async def test_pagination_parameters(self, mock_http_client, mock_token_manager):
        """Test pagination parameter handling."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        await list_iam_users(workspace='test', page=2, page_size=50)

        mock_http_client.get.assert_called_with(
            region='ap1',
            workspace='test',
            endpoint='/api/iam/users/',
            token='test-token',
            params={'page': 2, 'page_size': 50},
        )

    @pytest.mark.asyncio
    async def test_optional_parameters(
        self, mock_http_client, mock_token_manager, sample_user
    ):
        """Test functions with optional parameters."""
        mock_http_client.post.return_value = sample_user

        await create_iam_user(
            username='test', email='test@example.com', workspace='test'
        )

        expected_data = {
            'username': 'test',
            'email': 'test@example.com',
            'is_active': True,
        }

        mock_http_client.post.assert_called_with(
            region='ap1',
            workspace='test',
            endpoint='/api/iam/users/',
            token='test-token',
            data=expected_data,
        )

    @pytest.mark.asyncio
    async def test_different_regions(self, mock_http_client, mock_token_manager):
        """Test with different regions."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        await list_iam_users(workspace='test', region='us1')

        mock_http_client.get.assert_called_with(
            region='us1',
            workspace='test',
            endpoint='/api/iam/users/',
            token='test-token',
            params={},
        )


class TestIAMGroupExtendedManagement:
    """Test extended group management functions (get, update, delete)."""

    @pytest.mark.asyncio
    async def test_get_iam_group_success(self, mock_http_client, mock_token_manager):
        """Test successful group retrieval."""
        group_data = {
            'id': GROUP_ID,
            'name': 'admins',
            'description': 'Administrators group',
        }
        mock_http_client.get.return_value = group_data

        result = await get_iam_group(group_id=GROUP_ID, workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data'] == group_data
        assert result['group_id'] == GROUP_ID

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/groups/{GROUP_ID}/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_update_iam_group_success(self, mock_http_client, mock_token_manager):
        """Test successful group update."""
        updated_group = {
            'id': GROUP_ID,
            'name': 'admins',
            'display_name': 'Senior Admins',
            'description': 'Senior administrators group',
        }
        mock_http_client.patch.return_value = updated_group

        result = await update_iam_group(
            group_id=GROUP_ID,
            workspace='testworkspace',
            display_name='Senior Admins',
            description='Senior administrators group',
        )

        assert result['status'] == 'success'
        assert result['data'] == updated_group
        assert result['group_id'] == GROUP_ID

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/groups/{GROUP_ID}/',
            token='test-token',
            data={
                'display_name': 'Senior Admins',
                'description': 'Senior administrators group',
            },
        )

    @pytest.mark.asyncio
    async def test_get_iam_group_invalid_id(self, mock_http_client, mock_token_manager):
        """Test group retrieval rejects a non-UUID group ID locally."""
        result = await get_iam_group(group_id='not-a-uuid', workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_iam_group_no_data(self, mock_http_client, mock_token_manager):
        """Test update group with no fields returns error."""
        result = await update_iam_group(group_id=GROUP_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_iam_group_success(self, mock_http_client, mock_token_manager):
        """Test successful group deletion."""
        mock_http_client.delete.return_value = {'message': 'Group deleted successfully'}

        result = await delete_iam_group(group_id=GROUP_ID, workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['group_id'] == GROUP_ID

        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/groups/{GROUP_ID}/',
            token='test-token',
        )


class TestIAMMembershipManagement:
    """Test IAM membership management functions."""

    @pytest.mark.asyncio
    async def test_list_iam_memberships_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful memberships list retrieval."""
        memberships_data = {
            'count': 2,
            'results': [
                {'id': 'mem-1', 'group': GROUP_ID, 'user': 'user-1'},
                {'id': 'mem-2', 'group': GROUP_ID, 'user': 'user-2'},
            ],
        }
        mock_http_client.get.return_value = memberships_data

        result = await list_iam_memberships(workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data'] == memberships_data
        assert len(result['data']['results']) == 2

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/memberships/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_iam_memberships_with_group_filter(
        self, mock_http_client, mock_token_manager
    ):
        """Test memberships list filtered by group ID."""
        mock_http_client.get.return_value = {'count': 1, 'results': []}

        await list_iam_memberships(
            workspace='testworkspace', group_id=GROUP_ID, page=1, page_size=10
        )

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/memberships/',
            token='test-token',
            params={'group': GROUP_ID, 'page': 1, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_list_iam_memberships_invalid_group_filter(
        self, mock_http_client, mock_token_manager
    ):
        """Test membership listing rejects a non-UUID group filter locally."""
        result = await list_iam_memberships(
            workspace='testworkspace', group_id='not-a-uuid'
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_iam_member_success(self, mock_http_client, mock_token_manager):
        """Test successful member addition to group."""
        membership_data = {'id': 'mem-1', 'group': GROUP_ID, 'user': USER_ID}
        mock_http_client.post.return_value = membership_data

        result = await add_iam_member(
            group_id=GROUP_ID, user_id=USER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert result['data'] == membership_data
        assert result['group_id'] == GROUP_ID
        assert result['user_id'] == USER_ID

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/memberships/',
            token='test-token',
            data={'group': GROUP_ID, 'user': USER_ID, 'role': 'member'},
        )

    @pytest.mark.asyncio
    async def test_add_iam_member_with_role(self, mock_http_client, mock_token_manager):
        """Test member addition with an explicit role."""
        mock_http_client.post.return_value = {'id': 'mem-2', 'role': 'manager'}

        result = await add_iam_member(
            group_id=GROUP_ID,
            user_id=USER_ID_2,
            workspace='testworkspace',
            role='manager',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/memberships/',
            token='test-token',
            data={'group': GROUP_ID, 'user': USER_ID_2, 'role': 'manager'},
        )

    @pytest.mark.asyncio
    async def test_add_iam_member_invalid_role(
        self, mock_http_client, mock_token_manager
    ):
        """Test member addition rejects an unknown role locally."""
        result = await add_iam_member(
            group_id=GROUP_ID,
            user_id=USER_ID,
            workspace='testworkspace',
            role='admin',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_iam_member_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful member removal from group."""
        mock_http_client.delete.return_value = {'message': 'Membership removed'}

        result = await remove_iam_member(
            membership_id=MEMBERSHIP_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert result['membership_id'] == MEMBERSHIP_ID

        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/memberships/{MEMBERSHIP_ID}/',
            token='test-token',
        )


class TestWorkspaceUserInvitation:
    """Test workspace user invitation function."""

    @pytest.mark.asyncio
    async def test_invite_workspace_user_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful workspace invitation."""
        invite_data = {'detail': ['User invitation sent.']}
        mock_http_client.post.return_value = invite_data

        result = await invite_workspace_user(
            email='newuser@example.com',
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert result['data'] == invite_data
        assert result['email'] == 'newuser@example.com'

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/workspaces/users/invite/',
            token='test-token',
            data={'email': 'newuser@example.com'},
        )

    @pytest.mark.asyncio
    async def test_invite_workspace_user_different_region(
        self, mock_http_client, mock_token_manager
    ):
        """Test workspace invitation with a specific region."""
        mock_http_client.post.return_value = {'detail': ['User invitation sent.']}

        result = await invite_workspace_user(
            email='user@example.com',
            workspace='testworkspace',
            region='us1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='us1',
            workspace='testworkspace',
            endpoint='/api/workspaces/users/invite/',
            token='test-token',
            data={'email': 'user@example.com'},
        )


class TestIAMApplicationManagement:
    """Test IAM application management functions."""

    @pytest.fixture
    def sample_application(self):
        """Sample application data for testing."""
        return {
            'id': APP_ID,
            'name': 'my-service',
            'description': 'My service application',
            'added_at': '2024-01-01T00:00:00Z',
        }

    @pytest.mark.asyncio
    async def test_list_iam_applications_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful applications list retrieval."""
        apps_data = {
            'count': 2,
            'results': [
                {'id': 'app-1', 'name': 'service-a'},
                {'id': 'app-2', 'name': 'service-b'},
            ],
        }
        mock_http_client.get.return_value = apps_data

        result = await list_iam_applications(workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data'] == apps_data
        assert len(result['data']['results']) == 2

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/applications/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_iam_applications_pagination(
        self, mock_http_client, mock_token_manager
    ):
        """Test applications list with pagination parameters."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        await list_iam_applications(workspace='testworkspace', page=2, page_size=5)

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/applications/',
            token='test-token',
            params={'page': 2, 'page_size': 5},
        )

    @pytest.mark.asyncio
    async def test_create_iam_application_success(
        self, mock_http_client, mock_token_manager, sample_application
    ):
        """Test successful application creation."""
        mock_http_client.post.return_value = sample_application

        result = await create_iam_application(
            name='my-service',
            workspace='testworkspace',
            description='My service application',
        )

        assert result['status'] == 'success'
        assert result['data'] == sample_application
        assert result['app_name'] == 'my-service'

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/applications/',
            token='test-token',
            data={'name': 'my-service', 'description': 'My service application'},
        )

    @pytest.mark.asyncio
    async def test_create_iam_application_no_description(
        self, mock_http_client, mock_token_manager, sample_application
    ):
        """Test application creation without optional description."""
        mock_http_client.post.return_value = sample_application

        await create_iam_application(name='my-service', workspace='testworkspace')

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/applications/',
            token='test-token',
            data={'name': 'my-service'},
        )

    @pytest.mark.asyncio
    async def test_create_iam_application_invalid_service_type(
        self, mock_http_client, mock_token_manager
    ):
        """Test application creation rejects an unknown service type locally."""
        result = await create_iam_application(
            name='my-service',
            workspace='testworkspace',
            service_type='oauth',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_iam_application_success(
        self, mock_http_client, mock_token_manager, sample_application
    ):
        """Test successful application retrieval."""
        mock_http_client.get.return_value = sample_application

        result = await get_iam_application(app_id=APP_ID, workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data'] == sample_application
        assert result['app_id'] == APP_ID

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/applications/{APP_ID}/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_update_iam_application_success(
        self, mock_http_client, mock_token_manager, sample_application
    ):
        """Test successful application update."""
        updated_app = sample_application.copy()
        updated_app['name'] = 'my-service-v2'
        mock_http_client.patch.return_value = updated_app

        result = await update_iam_application(
            app_id=APP_ID,
            workspace='testworkspace',
            name='my-service-v2',
        )

        assert result['status'] == 'success'
        assert result['data']['name'] == 'my-service-v2'
        assert result['app_id'] == APP_ID

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/applications/{APP_ID}/',
            token='test-token',
            data={'name': 'my-service-v2'},
        )

    @pytest.mark.asyncio
    async def test_update_iam_application_no_data(
        self, mock_http_client, mock_token_manager
    ):
        """Test update application with no fields returns error."""
        result = await update_iam_application(app_id=APP_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_iam_application_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful application deletion."""
        mock_http_client.delete.return_value = {'message': 'Application deleted'}

        result = await delete_iam_application(app_id=APP_ID, workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['app_id'] == APP_ID

        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/applications/{APP_ID}/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_assign_application_system_users_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful system user assignment to an application."""
        assigned = [{'id': SYSTEM_USER_ID, 'username': 'svc-my-service'}]
        mock_http_client.post.return_value = assigned

        result = await assign_application_system_users(
            app_id=APP_ID,
            system_user_ids=[SYSTEM_USER_ID],
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert result['data'] == assigned
        assert result['app_id'] == APP_ID

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/applications/{APP_ID}/system-users/',
            token='test-token',
            data={'system_user_ids': [SYSTEM_USER_ID]},
        )

    @pytest.mark.asyncio
    async def test_unassign_application_system_users_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful system user unassignment from an application."""
        unassigned = {'unassigned': 1, 'system_user_ids': [SYSTEM_USER_ID]}
        mock_http_client.post.return_value = unassigned

        result = await unassign_application_system_users(
            app_id=APP_ID,
            system_user_ids=[SYSTEM_USER_ID],
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert result['data'] == unassigned
        assert result['app_id'] == APP_ID

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/iam/applications/{APP_ID}/system-users/unassign/',
            token='test-token',
            data={'system_user_ids': [SYSTEM_USER_ID]},
        )

    @pytest.mark.asyncio
    async def test_assign_application_system_users_empty_list(
        self, mock_http_client, mock_token_manager
    ):
        """Test assignment rejects an empty system user list locally."""
        result = await assign_application_system_users(
            app_id=APP_ID,
            system_user_ids=[],
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
