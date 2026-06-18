"""Unit tests for approval and sudo policy tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE
from tools.approval_tools import (
    create_sudo_policy,
    explain_approval_decision,
    get_approval_request,
    list_approval_requests,
    list_sudo_policies,
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
            endpoint='/api/approvals/approvals/',
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
            endpoint='/api/approvals/approvals/',
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
            endpoint='/api/approvals/approvals/',
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
            endpoint='/api/approvals/approvals/req-1/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_approval_request_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """An http_client error envelope must surface as status='error'."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_approval_request(
            request_id='req-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['status_code'] == 404
        assert result['message'] == 'Not found'


class TestApprovalDecisionIsHumanOnly:
    """ADR 0015: an agent cannot approve/reject; there is no mutation tool."""

    def test_no_approve_or_reject_tool_exists(self):
        """The approve/reject mutation tools must not be importable."""
        import tools.approval_tools as approval_tools

        assert not hasattr(approval_tools, 'approve_request')
        assert not hasattr(approval_tools, 'reject_request')

    @pytest.mark.asyncio
    async def test_explain_returns_structured_pending_guidance(
        self, mock_http_client, mock_token_manager
    ):
        """explain_approval_decision surfaces the human-only, out-of-band signal."""
        result = await explain_approval_decision(
            request_id='req-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'pending_approval'
        assert result['category'] == 'APPROVAL_DECISION_HUMAN_ONLY'
        assert result['requires_human_approval'] is True
        assert result['approvable_by_agent'] is False
        assert result['request_id'] == 'req-1'
        assert 'out-of-band' in result['next_action']

    @pytest.mark.asyncio
    async def test_explain_never_calls_the_server(
        self, mock_http_client, mock_token_manager
    ):
        """The agent must never be the actor: no approve/reject HTTP call is made."""
        await explain_approval_decision(workspace='testworkspace', region='ap1')

        mock_http_client.post.assert_not_called()
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_explain_omits_request_id_when_absent(
        self, mock_http_client, mock_token_manager
    ):
        """request_id is optional and omitted from the payload when not given."""
        result = await explain_approval_decision(
            workspace='testworkspace', region='ap1'
        )

        assert 'request_id' not in result
        assert result['status'] == 'pending_approval'


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
            endpoint='/api/approvals/sudo-policies/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_sudo_policies_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """An http_client error envelope must surface as status='error'."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await list_sudo_policies(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['status_code'] == 404
        assert result['message'] == 'Not found'

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
            servers=['550e8400-e29b-41d4-a716-446655440000'],
            no_password=True,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/approvals/sudo-policies/',
            token='test-token',
            data={
                'name': 'deploy-sudo',
                'commands': ['/usr/bin/systemctl restart *'],
                'no_password': True,
                'users': ['user-1'],
                'servers': ['550e8400-e29b-41d4-a716-446655440000'],
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
            endpoint='/api/approvals/sudo-policies/',
            token='test-token',
            data={
                'name': 'basic',
                'commands': ['/usr/bin/apt update'],
                'no_password': False,
            },
        )

    @pytest.mark.asyncio
    async def test_create_sudo_policy_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """An http_client error envelope must surface as status='error'."""
        mock_http_client.post.return_value = HTTP_ERROR_ENVELOPE

        result = await create_sudo_policy(
            workspace='testworkspace',
            name='basic',
            commands=['/usr/bin/apt update'],
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['status_code'] == 404
        assert result['message'] == 'Not found'
