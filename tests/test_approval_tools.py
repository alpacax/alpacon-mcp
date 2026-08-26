"""Unit tests for approval and sudo policy tools module."""

from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE
from tools.approval_tools import (
    explain_approval_decision,
    get_approval_request,
    list_approval_requests,
    list_sudo_policies,
    request_sudo_policy,
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
        assert result['status_code'] == HTTPStatus.NOT_FOUND
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
            endpoint='/api/sudo/policies/',
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
        assert result['status_code'] == HTTPStatus.NOT_FOUND
        assert result['message'] == 'Not found'

    @pytest.mark.asyncio
    async def test_list_sudo_policies_uses_sudo_app_path(
        self, mock_http_client, mock_token_manager
    ):
        """The sudo app owns policies now: /api/sudo/policies/, not the approvals app."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

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
    async def test_list_sudo_policies_forwards_user_and_server_filters(
        self, mock_http_client, mock_token_manager
    ):
        """SudoPolicyFilter accepts user and server; both reach the query string."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_sudo_policies(
            workspace='testworkspace',
            region='ap1',
            user='550e8400-e29b-41d4-a716-446655440001',
            server_id='550e8400-e29b-41d4-a716-446655440002',
        )

        assert result['status'] == 'success'
        assert mock_http_client.get.call_args.kwargs['params'] == {
            'user': '550e8400-e29b-41d4-a716-446655440001',
            'server': '550e8400-e29b-41d4-a716-446655440002',
        }

    @pytest.mark.asyncio
    async def test_list_sudo_policies_rejects_a_server_name(
        self, mock_http_client, mock_token_manager
    ):
        """The filter is named server_id so a name dies at the validator, not at the API."""
        result = await list_sudo_policies(
            workspace='testworkspace',
            region='ap1',
            server_id='web-server-01',
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()


class TestRequestSudoPolicy:
    """Tests for request_sudo_policy tool."""

    @pytest.mark.asyncio
    async def test_request_sudo_policy_posts_required_fields(
        self, mock_http_client, mock_token_manager
    ):
        """Required fields reach the policy-requests endpoint verbatim."""
        mock_http_client.post.return_value = {'id': 'apr-1', 'status': 'pending'}

        result = await request_sudo_policy(
            workspace='testworkspace',
            servers=['550e8400-e29b-41d4-a716-446655440002'],
            commands=['/usr/bin/systemctl restart nginx'],
            reason='Deploy window for the nginx config rollout',
            region='ap1',
        )

        assert result['status'] == 'pending_approval'
        assert result['category'] == 'SUDO_POLICY_REQUEST_PENDING'
        assert result['requires_human_approval'] is True
        assert result['approvable_by_agent'] is False
        assert result['data'] == {'id': 'apr-1', 'status': 'pending'}
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/sudo/policy-requests/',
            token='test-token',
            data={
                'servers': ['550e8400-e29b-41d4-a716-446655440002'],
                'commands': ['/usr/bin/systemctl restart nginx'],
                'reason': 'Deploy window for the nginx config rollout',
            },
        )

    @pytest.mark.asyncio
    async def test_request_sudo_policy_forwards_optional_fields(
        self, mock_http_client, mock_token_manager
    ):
        """users and the validity window are sent only when supplied."""
        mock_http_client.post.return_value = {'id': 'apr-2'}

        await request_sudo_policy(
            workspace='testworkspace',
            servers=['550e8400-e29b-41d4-a716-446655440002'],
            commands=['/usr/bin/systemctl restart nginx'],
            reason='Deploy window for the nginx config rollout',
            users=['550e8400-e29b-41d4-a716-446655440001'],
            valid_from='2026-08-26T09:00:00Z',
            valid_until='2026-08-26T18:00:00Z',
            region='ap1',
        )

        assert mock_http_client.post.call_args.kwargs['data'] == {
            'servers': ['550e8400-e29b-41d4-a716-446655440002'],
            'commands': ['/usr/bin/systemctl restart nginx'],
            'reason': 'Deploy window for the nginx config rollout',
            'users': ['550e8400-e29b-41d4-a716-446655440001'],
            'valid_from': '2026-08-26T09:00:00Z',
            'valid_until': '2026-08-26T18:00:00Z',
        }

    @pytest.mark.asyncio
    async def test_request_sudo_policy_http_error_stays_an_error(
        self, mock_http_client, mock_token_manager
    ):
        """A failed call is not dressed up as a pending approval."""
        mock_http_client.post.return_value = HTTP_ERROR_ENVELOPE

        result = await request_sudo_policy(
            workspace='testworkspace',
            servers=['550e8400-e29b-41d4-a716-446655440002'],
            commands=['/usr/bin/systemctl restart nginx'],
            reason='Deploy window for the nginx config rollout',
            region='ap1',
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_request_sudo_policy_takes_no_bypass_parameter(self):
        """The server rejects allow_bypass_mfa on this endpoint, so the tool never offers it."""
        import inspect

        assert (
            'allow_bypass_mfa' not in inspect.signature(request_sudo_policy).parameters
        )

    @pytest.mark.asyncio
    async def test_create_sudo_policy_is_gone(self):
        """The direct-write policy tool is no longer part of the tool surface."""
        import tools.approval_tools as approval_tools

        assert not hasattr(approval_tools, 'create_sudo_policy')
