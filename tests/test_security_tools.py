"""Unit tests for security ACL tools."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.security_tools import (
    bulk_server_acl,
    create_command_acl,
    create_file_acl,
    create_server_acl,
    delete_command_acl,
    delete_file_acl,
    delete_server_acl,
    list_command_acls,
    list_file_acls,
    list_server_acls,
    update_command_acl,
    update_file_acl,
    update_server_acl,
)


@pytest.fixture
def mock_http_client():
    with patch('tools.security_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.patch = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


SERVER_UUID = '7e3984de-49ab-4cc6-bcdf-21fbd35858b8'
SERVER_UUID_2 = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'


# ===============================
# CommandACL tests
# ===============================


class TestListCommandAcls:
    @pytest.mark.asyncio
    async def test_list_no_filter(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_command_acls(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/command-acl/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_filter_by_api_token(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': []}

        result = await list_command_acls(
            workspace='testworkspace',
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/command-acl/',
            token='test-token',
            params={'api_token': 'token-uuid'},
        )

    @pytest.mark.asyncio
    async def test_list_filter_by_service_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await list_command_acls(
            workspace='testworkspace',
            service_token_id='svc-uuid',
            page=2,
            page_size=10,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/command-acl/',
            token='test-token',
            params={'service_token': 'svc-uuid', 'page': 2, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_list_both_tokens_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await list_command_acls(
            workspace='testworkspace',
            api_token_id='token-uuid',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()


class TestCreateCommandAcl:
    @pytest.mark.asyncio
    async def test_create_with_api_token(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = {
            'id': 'acl-1',
            'token': 'token-uuid',
            'command': 'docker *',
            'username': '',
            'groupname': '',
        }

        result = await create_command_acl(
            workspace='testworkspace',
            command='docker *',
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/command-acl/',
            token='test-token',
            data={
                'command': 'docker *',
                'username': '',
                'groupname': '',
                'token': 'token-uuid',
            },
        )

    @pytest.mark.asyncio
    async def test_create_with_service_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'acl-2',
            'service_token': 'svc-uuid',
        }

        result = await create_command_acl(
            workspace='testworkspace',
            command='ls -la',
            service_token_id='svc-uuid',
            username='deploy',
            groupname='docker',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/command-acl/',
            token='test-token',
            data={
                'command': 'ls -la',
                'username': 'deploy',
                'groupname': 'docker',
                'service_token': 'svc-uuid',
            },
        )

    @pytest.mark.asyncio
    async def test_create_missing_token_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_command_acl(
            workspace='testworkspace',
            command='docker *',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_both_tokens_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_command_acl(
            workspace='testworkspace',
            command='docker *',
            api_token_id='token-uuid',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()


class TestUpdateCommandAcl:
    @pytest.mark.asyncio
    async def test_update_command(self, mock_http_client, mock_token_manager):
        mock_http_client.patch.return_value = {'id': 'acl-1', 'command': 'ls *'}

        result = await update_command_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            command='ls *',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-1'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/command-acl/acl-1/',
            token='test-token',
            data={'command': 'ls *'},
        )

    @pytest.mark.asyncio
    async def test_update_username_and_groupname(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': 'acl-1'}

        result = await update_command_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            username='root',
            groupname='docker',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/command-acl/acl-1/',
            token='test-token',
            data={'username': 'root', 'groupname': 'docker'},
        )

    @pytest.mark.asyncio
    async def test_update_no_data_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_command_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()


class TestDeleteCommandAcl:
    @pytest.mark.asyncio
    async def test_delete_success(self, mock_http_client, mock_token_manager):
        mock_http_client.delete.return_value = {}

        result = await delete_command_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/command-acl/acl-1/',
            token='test-token',
        )


# ===============================
# ServerACL tests
# ===============================


class TestListServerAcls:
    @pytest.mark.asyncio
    async def test_list_no_filter(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_server_acls(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_filter_by_api_token(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': []}

        result = await list_server_acls(
            workspace='testworkspace',
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/',
            token='test-token',
            params={'api_token': 'token-uuid'},
        )

    @pytest.mark.asyncio
    async def test_list_filter_by_service_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await list_server_acls(
            workspace='testworkspace',
            service_token_id='svc-uuid',
            page=2,
            page_size=10,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/',
            token='test-token',
            params={'service_token': 'svc-uuid', 'page': 2, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_list_both_tokens_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await list_server_acls(
            workspace='testworkspace',
            api_token_id='token-uuid',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()


class TestCreateServerAcl:
    @pytest.mark.asyncio
    async def test_create_with_api_token(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = {
            'id': 'acl-1',
            'token': 'token-uuid',
            'server': SERVER_UUID,
        }

        result = await create_server_acl(
            workspace='testworkspace',
            server_id=SERVER_UUID,
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/',
            token='test-token',
            data={'server': SERVER_UUID, 'token': 'token-uuid'},
        )

    @pytest.mark.asyncio
    async def test_create_with_service_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'acl-2'}

        result = await create_server_acl(
            workspace='testworkspace',
            server_id=SERVER_UUID,
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/',
            token='test-token',
            data={'server': SERVER_UUID, 'service_token': 'svc-uuid'},
        )

    @pytest.mark.asyncio
    async def test_create_missing_token_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_server_acl(
            workspace='testworkspace',
            server_id=SERVER_UUID,
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_both_tokens_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_server_acl(
            workspace='testworkspace',
            server_id=SERVER_UUID,
            api_token_id='token-uuid',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()


class TestUpdateServerAcl:
    @pytest.mark.asyncio
    async def test_update_server(self, mock_http_client, mock_token_manager):
        mock_http_client.patch.return_value = {'id': 'acl-1', 'server': SERVER_UUID_2}

        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            server_id=SERVER_UUID_2,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-1'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-1/',
            token='test-token',
            data={'server': SERVER_UUID_2},
        )

    @pytest.mark.asyncio
    async def test_update_rebind_to_api_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': 'acl-1'}

        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            api_token_id='new-token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-1/',
            token='test-token',
            data={'token': 'new-token-uuid', 'service_token': None},
        )

    @pytest.mark.asyncio
    async def test_update_rebind_to_service_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': 'acl-1'}

        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-1/',
            token='test-token',
            data={'service_token': 'svc-uuid', 'token': None},
        )

    @pytest.mark.asyncio
    async def test_update_server_and_token_combined(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': 'acl-1'}

        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            server_id=SERVER_UUID_2,
            api_token_id='new-token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-1/',
            token='test-token',
            data={
                'server': SERVER_UUID_2,
                'token': 'new-token-uuid',
                'service_token': None,
            },
        )

    @pytest.mark.asyncio
    async def test_update_no_data_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_both_tokens_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            api_token_id='token-uuid',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()


class TestDeleteServerAcl:
    @pytest.mark.asyncio
    async def test_delete_success(self, mock_http_client, mock_token_manager):
        mock_http_client.delete.return_value = {}

        result = await delete_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-1/',
            token='test-token',
        )


class TestBulkServerAcl:
    @pytest.mark.asyncio
    async def test_bulk_add_uses_correct_endpoint(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = [{'id': 'acl-1'}, {'id': 'acl-2'}]

        result = await bulk_server_acl(
            workspace='testworkspace',
            action='add',
            server_ids=[SERVER_UUID, SERVER_UUID_2],
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/bulk/',
            token='test-token',
            data={'servers': [SERVER_UUID, SERVER_UUID_2], 'token': 'token-uuid'},
        )

    @pytest.mark.asyncio
    async def test_bulk_remove_uses_delete_endpoint(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'deleted': 2}

        result = await bulk_server_acl(
            workspace='testworkspace',
            action='remove',
            server_ids=[SERVER_UUID, SERVER_UUID_2],
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/bulk/delete/',
            token='test-token',
            data={'servers': [SERVER_UUID, SERVER_UUID_2], 'token': 'token-uuid'},
        )

    @pytest.mark.asyncio
    async def test_bulk_with_service_token(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = [{'id': 'acl-1'}]

        result = await bulk_server_acl(
            workspace='testworkspace',
            action='add',
            server_ids=[SERVER_UUID],
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/bulk/',
            token='test-token',
            data={'servers': [SERVER_UUID], 'service_token': 'svc-uuid'},
        )

    @pytest.mark.asyncio
    async def test_bulk_invalid_action_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await bulk_server_acl(
            workspace='testworkspace',
            action='delete',
            server_ids=[SERVER_UUID],
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_missing_token_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await bulk_server_acl(
            workspace='testworkspace',
            action='add',
            server_ids=[SERVER_UUID],
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_both_tokens_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await bulk_server_acl(
            workspace='testworkspace',
            action='add',
            server_ids=[SERVER_UUID],
            api_token_id='token-uuid',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_empty_server_ids_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await bulk_server_acl(
            workspace='testworkspace',
            action='add',
            server_ids=[],
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_over_100_server_ids_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        server_ids = [f'00000000-0000-4000-8000-{i:012d}' for i in range(101)]

        result = await bulk_server_acl(
            workspace='testworkspace',
            action='add',
            server_ids=server_ids,
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()


# ===============================
# FileACL tests
# ===============================


class TestListFileAcls:
    @pytest.mark.asyncio
    async def test_list_no_filter(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_file_acls(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_filter_by_api_token(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': []}

        result = await list_file_acls(
            workspace='testworkspace',
            api_token_id='token-uuid',
            page=1,
            page_size=20,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/',
            token='test-token',
            params={'api_token': 'token-uuid', 'page': 1, 'page_size': 20},
        )

    @pytest.mark.asyncio
    async def test_list_filter_by_service_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await list_file_acls(
            workspace='testworkspace',
            service_token_id='svc-uuid',
            page=2,
            page_size=10,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/',
            token='test-token',
            params={'service_token': 'svc-uuid', 'page': 2, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_list_both_tokens_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await list_file_acls(
            workspace='testworkspace',
            api_token_id='token-uuid',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()


class TestCreateFileAcl:
    @pytest.mark.asyncio
    async def test_create_upload_rule(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = {
            'id': 'acl-1',
            'token': 'token-uuid',
            'path': '/var/log/*',
            'action': 'upload',
            'username': '',
            'groupname': '',
        }

        result = await create_file_acl(
            workspace='testworkspace',
            path='/var/log/*',
            action='upload',
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/',
            token='test-token',
            data={
                'path': '/var/log/*',
                'action': 'upload',
                'username': '',
                'groupname': '',
                'token': 'token-uuid',
            },
        )

    @pytest.mark.asyncio
    async def test_create_wildcard_action(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = {'id': 'acl-2'}

        result = await create_file_acl(
            workspace='testworkspace',
            path='/home/deploy/*',
            action='*',
            api_token_id='token-uuid',
            username='deploy',
            groupname='*',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/',
            token='test-token',
            data={
                'path': '/home/deploy/*',
                'action': '*',
                'username': 'deploy',
                'groupname': '*',
                'token': 'token-uuid',
            },
        )

    @pytest.mark.asyncio
    async def test_create_with_service_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'acl-3',
            'service_token': 'svc-uuid',
        }

        result = await create_file_acl(
            workspace='testworkspace',
            path='/var/log/*',
            action='download',
            service_token_id='svc-uuid',
            username='deploy',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/',
            token='test-token',
            data={
                'path': '/var/log/*',
                'action': 'download',
                'username': 'deploy',
                'groupname': '',
                'service_token': 'svc-uuid',
            },
        )

    @pytest.mark.asyncio
    async def test_create_invalid_action_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_file_acl(
            workspace='testworkspace',
            path='/var/log/*',
            action='delete',
            api_token_id='token-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_missing_token_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_file_acl(
            workspace='testworkspace',
            path='/var/log/*',
            action='upload',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_both_tokens_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_file_acl(
            workspace='testworkspace',
            path='/var/log/*',
            action='upload',
            api_token_id='token-uuid',
            service_token_id='svc-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()


class TestUpdateFileAcl:
    @pytest.mark.asyncio
    async def test_update_path(self, mock_http_client, mock_token_manager):
        mock_http_client.patch.return_value = {'id': 'acl-1', 'path': '/new/path/*'}

        result = await update_file_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            path='/new/path/*',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-1'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/acl-1/',
            token='test-token',
            data={'path': '/new/path/*'},
        )

    @pytest.mark.asyncio
    async def test_update_action_and_username(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {'id': 'acl-1'}

        result = await update_file_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            action='download',
            username='root',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/acl-1/',
            token='test-token',
            data={'action': 'download', 'username': 'root'},
        )

    @pytest.mark.asyncio
    async def test_update_invalid_action_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_file_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            action='write',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_no_data_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_file_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()


class TestDeleteFileAcl:
    @pytest.mark.asyncio
    async def test_delete_success(self, mock_http_client, mock_token_manager):
        mock_http_client.delete.return_value = {}

        result = await delete_file_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/acl-1/',
            token='test-token',
        )
