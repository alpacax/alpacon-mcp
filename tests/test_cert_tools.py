"""Unit tests for certificate and PKI management tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.cert_tools import (
    create_certificate_authority,
    create_sign_request,
    list_certificate_authorities,
    list_certificates,
    list_sign_requests,
    revoke_certificate,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.cert_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
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
