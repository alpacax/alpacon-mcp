"""Unit tests for certificate and PKI management tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.cert_tools import (
    approve_revoke_request,
    approve_sign_request,
    cancel_revoke_request,
    create_certificate_authority,
    create_sign_request,
    delete_certificate_authority,
    delete_sign_request,
    deny_revoke_request,
    deny_sign_request,
    get_certificate,
    get_certificate_authority,
    get_revoke_request,
    get_sign_request,
    list_certificate_authorities,
    list_certificates,
    list_revoke_requests,
    list_sign_requests,
    retry_revoke_request,
    retry_sign_request,
    revoke_certificate,
    update_certificate_authority,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.cert_tools.http_client') as mock_client:
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


class TestCertificateAuthorities:
    """Test certificate authority tools."""

    @pytest.mark.asyncio
    async def test_list_certificate_authorities_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CA listing."""
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [{'id': 'ca-1', 'name': 'Internal CA'}],
        }

        result = await list_certificate_authorities(
            workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_create_certificate_authority_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CA creation."""
        mock_http_client.post.return_value = {
            'id': 'ca-1',
            'name': 'Internal CA',
            'common_name': 'Internal Root CA',
        }

        result = await create_certificate_authority(
            workspace='testworkspace',
            name='Internal CA',
            common_name='Internal Root CA',
            organization='ACME Corp',
            country='US',
            validity_days=3650,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/',
            token='test-token',
            data={
                'name': 'Internal CA',
                'common_name': 'Internal Root CA',
                'organization': 'ACME Corp',
                'country': 'US',
                'validity_days': 3650,
            },
        )

    @pytest.mark.asyncio
    async def test_create_certificate_authority_minimal(
        self, mock_http_client, mock_token_manager
    ):
        """Test CA creation with minimal params."""
        mock_http_client.post.return_value = {'id': 'ca-2'}

        result = await create_certificate_authority(
            workspace='testworkspace',
            name='Test CA',
            common_name='Test Root CA',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/',
            token='test-token',
            data={'name': 'Test CA', 'common_name': 'Test Root CA'},
        )


class TestSignRequests:
    """Test certificate signing request tools."""

    @pytest.mark.asyncio
    async def test_list_sign_requests_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CSR listing."""
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [{'id': 'csr-1'}],
        }

        result = await list_sign_requests(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_create_sign_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CSR creation."""
        mock_http_client.post.return_value = {
            'id': 'csr-1',
            'common_name': 'api.example.com',
        }

        result = await create_sign_request(
            workspace='testworkspace',
            authority_id='ca-1',
            common_name='api.example.com',
            san_dns=['api.example.com', 'api-internal.example.com'],
            san_ip=['10.0.0.1'],
            validity_days=365,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/',
            token='test-token',
            data={
                'authority': 'ca-1',
                'common_name': 'api.example.com',
                'san_dns': ['api.example.com', 'api-internal.example.com'],
                'san_ip': ['10.0.0.1'],
                'validity_days': 365,
            },
        )

    @pytest.mark.asyncio
    async def test_create_sign_request_minimal(
        self, mock_http_client, mock_token_manager
    ):
        """Test CSR creation with minimal params."""
        mock_http_client.post.return_value = {'id': 'csr-2'}

        result = await create_sign_request(
            workspace='testworkspace',
            authority_id='ca-1',
            common_name='web.example.com',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/',
            token='test-token',
            data={'authority': 'ca-1', 'common_name': 'web.example.com'},
        )


class TestCertificates:
    """Test certificate tools."""

    @pytest.mark.asyncio
    async def test_list_certificates_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful certificates listing."""
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [{'id': 'cert-1', 'common_name': 'api.example.com'}],
        }

        result = await list_certificates(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/certificates/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_certificates_with_authority_filter(
        self, mock_http_client, mock_token_manager
    ):
        """Test certificates listing filtered by authority."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_certificates(
            workspace='testworkspace', authority_id='ca-1', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/certificates/',
            token='test-token',
            params={'authority': 'ca-1'},
        )

    @pytest.mark.asyncio
    async def test_revoke_certificate_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful certificate revocation."""
        mock_http_client.post.return_value = {
            'id': 'cert-1',
            'status': 'revoked',
        }

        result = await revoke_certificate(
            certificate_id='cert-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['certificate_id'] == 'cert-1'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/',
            token='test-token',
            data={'certificate': 'cert-1'},
        )

    @pytest.mark.asyncio
    async def test_revoke_certificate_with_reason(
        self, mock_http_client, mock_token_manager
    ):
        """Test certificate revocation with reason."""
        mock_http_client.post.return_value = {'id': 'cert-1', 'status': 'revoked'}

        result = await revoke_certificate(
            certificate_id='cert-1',
            workspace='testworkspace',
            reason='Key compromise',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/',
            token='test-token',
            data={'certificate': 'cert-1', 'reason': 'Key compromise'},
        )


class TestGetCertificateAuthority:
    """Test get/update/delete certificate authority tools."""

    @pytest.mark.asyncio
    async def test_get_certificate_authority_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CA retrieval."""
        mock_http_client.get.return_value = {
            'id': 'ca-1',
            'name': 'Internal CA',
            'common_name': 'Internal Root CA',
        }

        result = await get_certificate_authority(
            ca_id='ca-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['ca_id'] == 'ca-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/ca-1/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_update_certificate_authority_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CA update."""
        mock_http_client.patch.return_value = {
            'id': 'ca-1',
            'name': 'Updated CA',
            'description': 'New description',
        }

        result = await update_certificate_authority(
            ca_id='ca-1',
            workspace='testworkspace',
            name='Updated CA',
            description='New description',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['ca_id'] == 'ca-1'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/ca-1/',
            token='test-token',
            data={'name': 'Updated CA', 'description': 'New description'},
        )

    @pytest.mark.asyncio
    async def test_update_certificate_authority_partial(
        self, mock_http_client, mock_token_manager
    ):
        """Test partial CA update sends only provided fields."""
        mock_http_client.patch.return_value = {'id': 'ca-1', 'description': 'Updated'}

        result = await update_certificate_authority(
            ca_id='ca-1',
            workspace='testworkspace',
            description='Updated',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/ca-1/',
            token='test-token',
            data={'description': 'Updated'},
        )

    @pytest.mark.asyncio
    async def test_update_certificate_authority_no_fields_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test that update with no optional fields returns an error."""
        result = await update_certificate_authority(
            ca_id='ca-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_certificate_authority_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CA deletion."""
        mock_http_client.delete.return_value = {}

        result = await delete_certificate_authority(
            ca_id='ca-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['ca_id'] == 'ca-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/ca-1/',
            token='test-token',
        )


class TestSignRequestDetails:
    """Test get/approve/deny/delete/retry sign request tools."""

    @pytest.mark.asyncio
    async def test_get_sign_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CSR retrieval."""
        mock_http_client.get.return_value = {
            'id': 'csr-1',
            'common_name': 'api.example.com',
            'status': 'pending',
        }

        result = await get_sign_request(
            csr_id='csr-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['csr_id'] == 'csr-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/csr-1/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_approve_sign_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CSR approval."""
        mock_http_client.post.return_value = {'id': 'csr-1', 'status': 'approved'}

        result = await approve_sign_request(
            csr_id='csr-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['csr_id'] == 'csr-1'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/csr-1/approve/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_deny_sign_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CSR denial without reason."""
        mock_http_client.post.return_value = {'id': 'csr-1', 'status': 'denied'}

        result = await deny_sign_request(
            csr_id='csr-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/csr-1/deny/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_deny_sign_request_with_reason(
        self, mock_http_client, mock_token_manager
    ):
        """Test CSR denial with reason."""
        mock_http_client.post.return_value = {'id': 'csr-1', 'status': 'denied'}

        result = await deny_sign_request(
            csr_id='csr-1',
            workspace='testworkspace',
            reason='Invalid SAN entries',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/csr-1/deny/',
            token='test-token',
            data={'reason': 'Invalid SAN entries'},
        )

    @pytest.mark.asyncio
    async def test_delete_sign_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CSR deletion."""
        mock_http_client.delete.return_value = {}

        result = await delete_sign_request(
            csr_id='csr-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['csr_id'] == 'csr-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/csr-1/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_retry_sign_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful CSR retry."""
        mock_http_client.post.return_value = {'id': 'csr-1', 'status': 'pending'}

        result = await retry_sign_request(
            csr_id='csr-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['csr_id'] == 'csr-1'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/csr-1/retry/',
            token='test-token',
            data={},
        )


class TestGetCertificate:
    """Test get certificate tool."""

    @pytest.mark.asyncio
    async def test_get_certificate_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful certificate retrieval."""
        mock_http_client.get.return_value = {
            'id': 'cert-1',
            'common_name': 'api.example.com',
            'status': 'active',
        }

        result = await get_certificate(
            certificate_id='cert-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['certificate_id'] == 'cert-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/certificates/cert-1/',
            token='test-token',
        )


class TestRevokeRequests:
    """Test revoke request tools."""

    @pytest.mark.asyncio
    async def test_list_revoke_requests_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful revoke requests listing."""
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [{'id': 'rev-1', 'status': 'pending'}],
        }

        result = await list_revoke_requests(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_revoke_requests_with_pagination(
        self, mock_http_client, mock_token_manager
    ):
        """Test revoke requests listing with pagination."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_revoke_requests(
            workspace='testworkspace', region='ap1', page=2, page_size=10
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/',
            token='test-token',
            params={'page': 2, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_get_revoke_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful revoke request retrieval."""
        mock_http_client.get.return_value = {
            'id': 'rev-1',
            'certificate': 'cert-1',
            'status': 'pending',
        }

        result = await get_revoke_request(
            revoke_id='rev-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['revoke_id'] == 'rev-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/rev-1/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_approve_revoke_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful revoke request approval."""
        mock_http_client.post.return_value = {'id': 'rev-1', 'status': 'approved'}

        result = await approve_revoke_request(
            revoke_id='rev-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['revoke_id'] == 'rev-1'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/rev-1/approve/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_deny_revoke_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful revoke request denial without reason."""
        mock_http_client.post.return_value = {'id': 'rev-1', 'status': 'denied'}

        result = await deny_revoke_request(
            revoke_id='rev-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/rev-1/deny/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_deny_revoke_request_with_reason(
        self, mock_http_client, mock_token_manager
    ):
        """Test revoke request denial with reason."""
        mock_http_client.post.return_value = {'id': 'rev-1', 'status': 'denied'}

        result = await deny_revoke_request(
            revoke_id='rev-1',
            workspace='testworkspace',
            reason='Certificate still in use',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/rev-1/deny/',
            token='test-token',
            data={'reason': 'Certificate still in use'},
        )

    @pytest.mark.asyncio
    async def test_retry_revoke_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful revoke request retry."""
        mock_http_client.post.return_value = {'id': 'rev-1', 'status': 'pending'}

        result = await retry_revoke_request(
            revoke_id='rev-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['revoke_id'] == 'rev-1'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/rev-1/retry/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_cancel_revoke_request_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful revoke request cancellation."""
        mock_http_client.post.return_value = {'id': 'rev-1', 'status': 'cancelled'}

        result = await cancel_revoke_request(
            revoke_id='rev-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['revoke_id'] == 'rev-1'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/rev-1/cancel/',
            token='test-token',
            data={},
        )
