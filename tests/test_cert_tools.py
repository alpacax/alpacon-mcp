"""Unit tests for certificate and PKI management tools module."""

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE, http_client_fixture, published_rule
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

mock_http_client = http_client_fixture('tools.cert_tools')
SERVER_ID = '7e3984de-49ab-4cc6-bcdf-21fbd35858b8'
OWNER_ID = '11111111-1111-1111-1111-111111111111'


class TestCertificateAuthorities:
    @pytest.mark.asyncio
    async def test_list_certificate_authorities_success(
        self, mock_http_client, mock_token_manager
    ):
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
        mock_http_client.post.return_value = {
            'id': 'ca-1',
            'name': 'Internal CA',
            'domain': 'internal.acme.com',
        }

        result = await create_certificate_authority(
            workspace='testworkspace',
            name='Internal CA',
            domain='internal.acme.com',
            organization='ACME Corp',
            server_id=SERVER_ID,
            owner=OWNER_ID,
            root_valid_days=3650,
            default_valid_days=365,
            max_valid_days=730,
            key_algorithm='rsa',
            key_size=4096,
            install=True,
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
                'domain': 'internal.acme.com',
                'organization': 'ACME Corp',
                'agent': SERVER_ID,
                'owner': OWNER_ID,
                'root_valid_days': 3650,
                'default_valid_days': 365,
                'max_valid_days': 730,
                'key_algorithm': 'rsa',
                'key_size': 4096,
                'install': True,
            },
        )

    @pytest.mark.asyncio
    async def test_list_certificate_authorities_with_pagination(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_certificate_authorities(
            workspace='testworkspace', region='ap1', page=2, page_size=10
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/',
            token='test-token',
            params={'page': 2, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_create_certificate_authority_minimal(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'ca-2'}

        result = await create_certificate_authority(
            workspace='testworkspace',
            name='Test CA',
            domain='test.acme.com',
            organization='ACME Corp',
            server_id=SERVER_ID,
            owner=OWNER_ID,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/',
            token='test-token',
            data={
                'name': 'Test CA',
                'domain': 'test.acme.com',
                'organization': 'ACME Corp',
                'agent': SERVER_ID,
                'owner': OWNER_ID,
            },
        )


class TestSignRequests:
    @pytest.mark.asyncio
    async def test_list_sign_requests_success(
        self, mock_http_client, mock_token_manager
    ):
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
    async def test_list_sign_requests_with_pagination(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_sign_requests(
            workspace='testworkspace', region='ap1', page=2, page_size=10
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/',
            token='test-token',
            params={'page': 2, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_create_sign_request_success(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'csr-1',
            'common_name': 'api.example.com',
        }

        result = await create_sign_request(
            workspace='testworkspace',
            domain_list=['api.example.com', 'api-internal.example.com'],
            ip_list=['10.0.0.1'],
            valid_days=365,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/',
            token='test-token',
            data={
                'domain_list': ['api.example.com', 'api-internal.example.com'],
                'ip_list': ['10.0.0.1'],
                'valid_days': 365,
            },
        )

    @pytest.mark.asyncio
    async def test_create_sign_request_minimal(
        self, mock_http_client, mock_token_manager
    ):
        """Test CSR creation with minimal params (single DNS SAN)."""
        mock_http_client.post.return_value = {'id': 'csr-2'}

        result = await create_sign_request(
            workspace='testworkspace',
            domain_list=['web.example.com'],
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/sign-requests/',
            token='test-token',
            data={'domain_list': ['web.example.com'], 'ip_list': []},
        )

    @pytest.mark.asyncio
    async def test_create_sign_request_requires_san(
        self, mock_http_client, mock_token_manager
    ):
        result = await create_sign_request(
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()


class TestCertificates:
    @pytest.mark.asyncio
    async def test_list_certificates_success(
        self, mock_http_client, mock_token_manager
    ):
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
            params={'csr__authority__id': 'ca-1'},
        )

    @pytest.mark.asyncio
    async def test_list_certificates_with_pagination(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_certificates(
            workspace='testworkspace', region='ap1', page=2, page_size=10
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/certificates/',
            token='test-token',
            params={'page': 2, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_revoke_certificate_success(
        self, mock_http_client, mock_token_manager
    ):
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
        mock_http_client.post.return_value = {'id': 'cert-1', 'status': 'revoked'}

        result = await revoke_certificate(
            certificate_id='cert-1',
            workspace='testworkspace',
            reason=1,
            requested_reason='Private key was exposed',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/',
            token='test-token',
            data={
                'certificate': 'cert-1',
                'reason': 1,
                'requested_reason': 'Private key was exposed',
            },
        )


class TestGetCertificateAuthority:
    @pytest.mark.asyncio
    async def test_get_certificate_authority_success(
        self, mock_http_client, mock_token_manager
    ):
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
        mock_http_client.patch.return_value = {
            'id': 'ca-1',
            'default_valid_days': 180,
            'max_valid_days': 365,
        }

        result = await update_certificate_authority(
            ca_id='ca-1',
            workspace='testworkspace',
            default_valid_days=180,
            max_valid_days=365,
            owner=OWNER_ID,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['ca_id'] == 'ca-1'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/ca-1/',
            token='test-token',
            data={
                'default_valid_days': 180,
                'max_valid_days': 365,
                'owner': OWNER_ID,
            },
        )

    @pytest.mark.asyncio
    async def test_update_certificate_authority_partial(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {
            'id': 'ca-1',
            'default_valid_days': 90,
        }

        result = await update_certificate_authority(
            ca_id='ca-1',
            workspace='testworkspace',
            default_valid_days=90,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/authorities/ca-1/',
            token='test-token',
            data={'default_valid_days': 90},
        )

    @pytest.mark.asyncio
    async def test_update_certificate_authority_no_fields_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_certificate_authority(
            ca_id='ca-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_certificate_authority_success(
        self, mock_http_client, mock_token_manager
    ):
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
    @pytest.mark.asyncio
    async def test_get_sign_request_success(self, mock_http_client, mock_token_manager):
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
    async def test_delete_sign_request_success(
        self, mock_http_client, mock_token_manager
    ):
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


class TestErrorPropagation:
    @pytest.mark.asyncio
    async def test_approve_sign_request_error(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = HTTP_ERROR_ENVELOPE

        result = await approve_sign_request(
            csr_id='csr-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_revoke_certificate_error(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = HTTP_ERROR_ENVELOPE

        result = await revoke_certificate(
            certificate_id='cert-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_get_certificate_error(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_certificate(
            certificate_id='cert-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'


class TestGetCertificate:
    @pytest.mark.asyncio
    async def test_get_certificate_success(self, mock_http_client, mock_token_manager):
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
    @pytest.mark.asyncio
    async def test_list_revoke_requests_success(
        self, mock_http_client, mock_token_manager
    ):
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
    async def test_retry_revoke_request_success(
        self, mock_http_client, mock_token_manager
    ):
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
        mock_http_client.delete.return_value = {'id': 'rev-1', 'status': 'canceled'}

        result = await cancel_revoke_request(
            revoke_id='rev-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['revoke_id'] == 'rev-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/cert/revoke-requests/rev-1/',
            token='test-token',
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name, param, phrase, gone',
    [
        (
            'create_certificate_authority',
            'key_algorithm',
            'rsa or ecdsa',
            'key algorithm (rsa',
        ),
        (
            'create_certificate_authority',
            'key_size',
            '256 or 384 for ECDSA',
            '2048/4096',
        ),
        ('create_sign_request', 'domain_list', 'DNS names', '(DNS names)'),
        ('create_sign_request', 'ip_list', 'IP addresses', '(IP addresses)'),
        ('revoke_certificate', 'reason', '10=AA compromise', 'RFC 5280'),
        ('revoke_certificate', 'requested_reason', 'Free-text', 'free-text'),
    ],
)
async def test_certificate_argument_rule_lives_on_the_parameter(
    tool_name, param, phrase, gone
):
    # Given a tool whose argument rule used to sit in its description

    # When reading the published parameter and tool description
    on_parameter, on_tool = await published_rule(tool_name, param)

    # Then the parameter states the rule and the tool no longer does
    assert phrase in on_parameter
    assert gone not in on_tool
