"""Unit tests for approval and sudo policy tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.approval_tools import (
    approve_request,
    create_sudo_policy,
    get_approval_request,
    list_approval_requests,
    list_sudo_policies,
    reject_request,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.approval_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


class TestListApprovalRequests:
    """Test approval requests listing."""

    @pytest.mark.asyncio
    async def test_list_approval_requests_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful approval requests list retrieval."""
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [{'id': 'req-1'}, {'id': 'req-2'}],
        }

        result = await list_approval_requests(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/requests/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_approval_requests_with_status_filter(
        self, mock_http_client, mock_token_manager
    ):
        """Test approval requests list with status filter."""
        mock_http_client.get.return_value = {'count': 1, 'results': [{'id': 'req-1'}]}

        result = await list_approval_requests(
            workspace='testworkspace', status='pending', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/requests/',
            token='test-token',
            params={'status': 'pending'},
        )

    @pytest.mark.asyncio
    async def test_list_approval_requests_with_pagination(
        self, mock_http_client, mock_token_manager
    ):
        """Test approval requests list with pagination."""
        mock_http_client.get.return_value = {'count': 10, 'results': []}

        result = await list_approval_requests(
            workspace='testworkspace', page=2, page_size=5, region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/requests/',
            token='test-token',
            params={'page': 2, 'page_size': 5},
        )


class TestGetApprovalRequest:
    """Test approval request details."""

    @pytest.mark.asyncio
    async def test_get_approval_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful approval request retrieval."""
        mock_http_client.get.return_value = {
            'id': 'req-1',
            'status': 'pending',
            'requestor': 'user1',
        }

        result = await get_approval_request(
            request_id='req-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['request_id'] == 'req-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/requests/req-1/',
            token='test-token',
        )


class TestApproveRequest:
    """Test approval request approval."""

    @pytest.mark.asyncio
    async def test_approve_request_success(self, mock_http_client, mock_token_manager):
        """Test successful request approval."""
        mock_http_client.post.return_value = {'id': 'req-1', 'status': 'approved'}

        result = await approve_request(
            request_id='req-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['request_id'] == 'req-1'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/requests/req-1/approve/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_approve_request_with_comment(
        self, mock_http_client, mock_token_manager
    ):
        """Test request approval with comment."""
        mock_http_client.post.return_value = {'id': 'req-1', 'status': 'approved'}

        result = await approve_request(
            request_id='req-1',
            workspace='testworkspace',
            comment='Approved for production access',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/requests/req-1/approve/',
            token='test-token',
            data={'comment': 'Approved for production access'},
        )


class TestRejectRequest:
    """Test approval request rejection."""

    @pytest.mark.asyncio
    async def test_reject_request_success(self, mock_http_client, mock_token_manager):
        """Test successful request rejection."""
        mock_http_client.post.return_value = {'id': 'req-1', 'status': 'rejected'}

        result = await reject_request(
            request_id='req-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/requests/req-1/reject/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_reject_request_with_comment(
        self, mock_http_client, mock_token_manager
    ):
        """Test request rejection with reason."""
        mock_http_client.post.return_value = {'id': 'req-1', 'status': 'rejected'}

        result = await reject_request(
            request_id='req-1',
            workspace='testworkspace',
            comment='Insufficient justification',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/requests/req-1/reject/',
            token='test-token',
            data={'comment': 'Insufficient justification'},
        )


class TestSudoPolicies:
    """Test sudo policy tools."""

    @pytest.mark.asyncio
    async def test_list_sudo_policies_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful sudo policies list retrieval."""
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [{'id': 'policy-1', 'name': 'admin-sudo'}],
        }

        result = await list_sudo_policies(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/sudo/policies/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_create_sudo_policy_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful sudo policy creation."""
        mock_http_client.post.return_value = {
            'id': 'policy-1',
            'name': 'deploy-sudo',
        }

        result = await create_sudo_policy(
            workspace='testworkspace',
            name='deploy-sudo',
            commands=['/usr/bin/systemctl restart *'],
            users=['user-1'],
            servers=['server-1'],
            no_password=True,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/sudo/policies/',
            token='test-token',
            data={
                'name': 'deploy-sudo',
                'commands': ['/usr/bin/systemctl restart *'],
                'no_password': True,
                'users': ['user-1'],
                'servers': ['server-1'],
            },
        )

    @pytest.mark.asyncio
    async def test_create_sudo_policy_minimal(
        self, mock_http_client, mock_token_manager
    ):
        """Test sudo policy creation with minimal params."""
        mock_http_client.post.return_value = {'id': 'policy-2', 'name': 'basic'}

        result = await create_sudo_policy(
            workspace='testworkspace',
            name='basic',
            commands=['/usr/bin/apt update'],
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/sudo/policies/',
            token='test-token',
            data={
                'name': 'basic',
                'commands': ['/usr/bin/apt update'],
                'no_password': False,
            },
        )
