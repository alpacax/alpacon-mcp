"""Unit tests for IAM tools: users, groups, memberships, and applications."""

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE, http_client_fixture, published_rule
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
SECOND_USER_ID = '33333333-3333-3333-3333-333333333333'
MEMBERSHIP_ID = '44444444-4444-4444-4444-444444444444'
SECOND_MEMBERSHIP_ID = '77777777-7777-7777-7777-777777777777'
APP_ID = '55555555-5555-5555-5555-555555555555'
SYSTEM_USER_ID = '66666666-6666-6666-6666-666666666666'


mock_http_client = http_client_fixture('tools.iam_tools')


@pytest.fixture
def sample_user():
    """Sample user data for testing."""
    return {
        'id': USER_ID,
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
                'id': USER_ID,
                'username': 'testuser1',
                'email': 'test1@example.com',
                'first_name': 'Test',
                'last_name': 'User1',
                'is_active': True,
                'num_groups': 1,
            },
            {
                'id': SECOND_USER_ID,
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
    @pytest.mark.asyncio
    async def test_list_iam_users_success(
        self, mock_http_client, mock_token_manager, sample_users_list
    ):
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
        mock_token_manager.get_token.return_value = None

        result = await list_iam_users(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_iam_users_pagination(
        self, mock_http_client, mock_token_manager, sample_users_list
    ):
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
        result = await get_iam_user(user_id='not-a-uuid', workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_iam_user_success(
        self, mock_http_client, mock_token_manager, sample_user
    ):
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
        result = await update_iam_user(
            user_id='not-a-uuid', workspace='testworkspace', first_name='Updated'
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_iam_user_success(self, mock_http_client, mock_token_manager):
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
        result = await delete_iam_user(user_id='not-a-uuid', workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.delete.assert_not_called()


class TestIAMGroupsManagement:
    @pytest.mark.asyncio
    async def test_list_iam_groups_success(self, mock_http_client, mock_token_manager):
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
        for invalid_name in ('Developers', 'dev team', 'dev.team', ''):
            result = await create_iam_group(
                name=invalid_name, workspace='testworkspace'
            )

            assert result['status'] == 'error'

        mock_http_client.post.assert_not_called()


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_missing_token_error(self, mock_http_client, mock_token_manager):
        mock_token_manager.get_token.return_value = None

        result = await create_iam_user(
            username='test', email='test@example.com', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()


class TestHTTPErrorEnvelope:
    @pytest.mark.asyncio
    async def test_get_iam_user_http_error(self, mock_http_client, mock_token_manager):
        """get_iam_user reports error when http_client returns an error envelope."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_iam_user(user_id=USER_ID, workspace='testworkspace')

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_create_iam_user_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """create_iam_user reports error when http_client returns an error envelope."""
        mock_http_client.post.return_value = HTTP_ERROR_ENVELOPE

        result = await create_iam_user(
            username='testuser', email='test@example.com', workspace='testworkspace'
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_delete_iam_user_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """delete_iam_user reports error when http_client returns an error envelope."""
        mock_http_client.delete.return_value = HTTP_ERROR_ENVELOPE

        result = await delete_iam_user(user_id=USER_ID, workspace='testworkspace')

        assert result['status'] == 'error'


class TestParameterValidation:
    @pytest.mark.asyncio
    async def test_optional_parameters(
        self, mock_http_client, mock_token_manager, sample_user
    ):
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
        result = await get_iam_group(group_id='not-a-uuid', workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_iam_group_no_data(self, mock_http_client, mock_token_manager):
        result = await update_iam_group(group_id=GROUP_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_iam_group_invalid_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_iam_group(
            group_id='not-a-uuid',
            display_name='Senior Admins',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_iam_group_success(self, mock_http_client, mock_token_manager):
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

    @pytest.mark.asyncio
    async def test_delete_iam_group_invalid_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await delete_iam_group(
            group_id='not-a-uuid', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        mock_http_client.delete.assert_not_called()


class TestIAMMembershipManagement:
    @pytest.mark.asyncio
    async def test_list_iam_memberships_success(
        self, mock_http_client, mock_token_manager
    ):
        memberships_data = {
            'count': 2,
            'results': [
                {'id': MEMBERSHIP_ID, 'group': GROUP_ID, 'user': USER_ID},
                {'id': SECOND_MEMBERSHIP_ID, 'group': GROUP_ID, 'user': SECOND_USER_ID},
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
        result = await list_iam_memberships(
            workspace='testworkspace', group_id='not-a-uuid'
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_iam_member_success(self, mock_http_client, mock_token_manager):
        membership_data = {'id': MEMBERSHIP_ID, 'group': GROUP_ID, 'user': USER_ID}
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
        mock_http_client.post.return_value = {
            'id': SECOND_MEMBERSHIP_ID,
            'role': 'manager',
        }

        result = await add_iam_member(
            group_id=GROUP_ID,
            user_id=SECOND_USER_ID,
            workspace='testworkspace',
            role='manager',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/iam/memberships/',
            token='test-token',
            data={'group': GROUP_ID, 'user': SECOND_USER_ID, 'role': 'manager'},
        )

    @pytest.mark.asyncio
    async def test_add_iam_member_invalid_role(
        self, mock_http_client, mock_token_manager
    ):
        result = await add_iam_member(
            group_id=GROUP_ID,
            user_id=USER_ID,
            workspace='testworkspace',
            role='admin',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_iam_member_invalid_group_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await add_iam_member(
            group_id='not-a-uuid',
            user_id=USER_ID,
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_iam_member_invalid_user_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await add_iam_member(
            group_id=GROUP_ID,
            user_id='not-a-uuid',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_iam_member_success(
        self, mock_http_client, mock_token_manager
    ):
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

    @pytest.mark.asyncio
    async def test_remove_iam_member_invalid_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await remove_iam_member(
            membership_id='not-a-uuid', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        mock_http_client.delete.assert_not_called()


class TestWorkspaceUserInvitation:
    @pytest.mark.asyncio
    async def test_invite_workspace_user_success(
        self, mock_http_client, mock_token_manager
    ):
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
    async def test_get_iam_application_invalid_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await get_iam_application(
            app_id='not-a-uuid', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_iam_application_no_data(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_iam_application(app_id=APP_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_iam_application_invalid_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_iam_application(
            app_id='not-a-uuid', workspace='testworkspace', name='new-name'
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_iam_application_success(
        self, mock_http_client, mock_token_manager
    ):
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
    async def test_delete_iam_application_invalid_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await delete_iam_application(
            app_id='not-a-uuid', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        mock_http_client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_application_system_users_success(
        self, mock_http_client, mock_token_manager
    ):
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
        result = await assign_application_system_users(
            app_id=APP_ID,
            system_user_ids=[],
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_application_system_users_invalid_system_user_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await assign_application_system_users(
            app_id=APP_ID,
            system_user_ids=['not-a-uuid'],
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_unassign_application_system_users_invalid_system_user_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await unassign_application_system_users(
            app_id=APP_ID,
            system_user_ids=['not-a-uuid'],
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_application_system_users_invalid_app_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await assign_application_system_users(
            app_id='not-a-uuid',
            system_user_ids=[SYSTEM_USER_ID],
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_unassign_application_system_users_invalid_app_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await unassign_application_system_users(
            app_id='not-a-uuid',
            system_user_ids=[SYSTEM_USER_ID],
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name, param, phrase, gone',
    [
        ('create_iam_group', 'name', 'lowercase letters', 'lowercase letters'),
        ('add_iam_member', 'role', 'member, manager or owner', 'member, manager'),
        ('create_iam_application', 'service_type', 'ci_cd, monitoring', 'ci_cd'),
    ],
)
async def test_iam_argument_rule_lives_on_the_parameter(tool_name, param, phrase, gone):
    # Given a tool whose argument rule used to sit in its description

    # When reading the published parameter and tool description
    on_parameter, on_tool = await published_rule(tool_name, param)

    # Then the parameter states the rule and the tool no longer does
    assert phrase in on_parameter
    assert gone not in on_tool


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name, param, phrase, gone',
    [
        (
            'list_iam_memberships',
            'group_id',
            'members of one group',
            'Optionally filter',
        ),
        (
            'list_iam_memberships',
            'group_id',
            'Filter by group ID',
            'see members of a specific group',
        ),
    ],
)
async def test_membership_filter_rule_lives_on_the_parameter(
    tool_name, param, phrase, gone
):
    # Given a tool whose argument rule used to sit in its description

    # When reading the published parameter and tool description
    on_parameter, on_tool = await published_rule(tool_name, param)

    # Then the parameter states the rule and the tool no longer does
    assert phrase in on_parameter
    assert gone not in on_tool


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
