"""Unit tests for the HTTP client: GET, POST, PATCH, DELETE, and error handling."""

import inspect
import logging
from collections.abc import Mapping
from http import HTTPStatus
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolRequestParams,
    CallToolResult,
    TextContent,
)

from tests.conftest import HTTP_VERBS
from utils import request_signal
from utils.error_handler import UpstreamAuthError
from utils.http_client import AlpaconHTTPClient, http_client
from utils.recovery_hints import _detect_error_domain, enrich_error_response

SERVER_ID = '550e8400-e29b-41d4-a716-446655440123'


@pytest.fixture
def mock_httpx_client(monkeypatch):
    """Mock httpx AsyncClient for testing."""
    # The pooled client is cached on the singleton; start and end without one.
    monkeypatch.setattr(http_client, '_client', None)
    with patch('utils.http_client.httpx.AsyncClient') as mock_client_class:
        # Create a mock client with AsyncMock methods
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Set up async context manager
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Make sure the client is closed property returns False
        mock_client.is_closed = False

        # HTTP methods should be AsyncMock so they can be awaited
        mock_client.request = AsyncMock()
        yield mock_client


@pytest.fixture
def no_retry_delay(monkeypatch):
    """Drop the backoff sleep for tests that exhaust the retries.
    monkeypatch, not assignment: http_client is a singleton, so a set value would leak.
    """
    monkeypatch.setattr(http_client, 'retry_delay', 0)


def create_mock_response(
    status_code=HTTPStatus.OK, json_data=None, text_data='', headers=None
):
    """Create a properly configured mock response."""
    # Use MagicMock instead of AsyncMock for response to avoid coroutine issues
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = headers or {}
    if json_data is not None:
        mock_response.json.return_value = json_data
        # A JSON body is never empty, whatever text_data says.
        text_data = text_data or 'mock response text'
    else:
        mock_response.json.return_value = {}
    # A real body's bytes and text are empty together; the client checks the bytes.
    mock_response.text = text_data
    mock_response.content = text_data.encode()

    # Mock raise_for_status to raise HTTPStatusError for error codes
    if status_code >= HTTPStatus.BAD_REQUEST:
        error = httpx.HTTPStatusError(
            'HTTP Error', request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status.side_effect = error
    else:
        mock_response.raise_for_status.return_value = None

    return mock_response


class TestHTTPClientGet:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_httpx_client):
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'result': 'success'}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
        )

        assert result == {'result': 'success'}

    @pytest.mark.asyncio
    async def test_get_with_params(self, mock_httpx_client):
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'results': []}
        )
        mock_httpx_client.request.return_value = mock_response

        params = {'page': 1, 'page_size': 20}
        result = await http_client.get(
            region='us1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
            params=params,
        )

        assert result == {'results': []}

    @pytest.mark.asyncio
    async def test_get_404_error(self, mock_httpx_client):
        mock_response = create_mock_response(status_code=HTTPStatus.NOT_FOUND)
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/notfound/',
            token='test-token',
        )

        assert isinstance(result, dict)
        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_500_error(self, mock_httpx_client, no_retry_delay):
        """Test GET request with 500 error (should retry and then fail)."""
        mock_response = create_mock_response(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/error/',
            token='test-token',
        )

        assert isinstance(result, dict)
        assert result['error'] == 'Max retries exceeded'
        # Should have retried 3 times
        assert mock_httpx_client.request.call_count == 3

    @pytest.mark.parametrize(
        ('tool_name', 'domain'),
        [
            ('get_server', 'server'),
            ('execute_command', 'command'),
            ('execute_file', 'command'),
            ('webftp_upload_file', 'file'),
        ],
    )
    @pytest.mark.asyncio
    async def test_get_500_exhaustion_enriches_across_tool_domains(
        self, mock_httpx_client, no_retry_delay, tool_name, domain
    ):
        """tool_name mirrors the live enrich call and outranks the message. 500 has one
        (500, 'general') entry, so hints converge; a domain-specific one would split.
        """
        mock_response = create_mock_response(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/error/',
            token='test-token',
        )

        assert isinstance(result, dict)
        status_code, message = result['status_code'], result['message']
        assert status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert isinstance(status_code, int)
        assert isinstance(message, str)
        assert _detect_error_domain(status_code, message, tool_name) == domain

        enriched = enrich_error_response(dict(result), tool_name=tool_name)
        assert enriched['recovery_hints'] == [
            'The server encountered an internal error. Try again in a moment.',
            'If the issue persists, check server health.',
        ]


class TestHTTPClientPost:
    @pytest.mark.asyncio
    async def test_post_success(self, mock_httpx_client):
        mock_response = create_mock_response(
            status_code=HTTPStatus.CREATED, json_data={'id': 123, 'created': True}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.post(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/create/',
            token='test-token',
            data={'name': 'test'},
        )

        assert result == {'id': 123, 'created': True}

    @pytest.mark.asyncio
    async def test_post_validation_error(self, mock_httpx_client):
        mock_response = create_mock_response(status_code=HTTPStatus.BAD_REQUEST)
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.post(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/create/',
            token='test-token',
            data={'invalid': 'data'},
        )

        assert isinstance(result, dict)
        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == HTTPStatus.BAD_REQUEST


class TestHTTPClientPatch:
    @pytest.mark.asyncio
    async def test_patch_success(self, mock_httpx_client):
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'updated': True}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.patch(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/update/123/',
            token='test-token',
            data={'name': 'updated'},
        )

        assert result == {'updated': True}


class TestHTTPClientBodyShapes:
    """The client hands back whatever JSON the server sent, untouched."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'body',
        [
            {'results': [{'id': 'a'}]},
            [{'id': 'a'}, {'id': 'b'}],
            'plain text',
            42,
            True,
        ],
        ids=['object', 'list', 'string', 'number', 'bool'],
    )
    async def test_get_returns_the_parsed_body_as_sent(self, mock_httpx_client, body):
        mock_httpx_client.request.return_value = create_mock_response(
            status_code=HTTPStatus.OK, json_data=body
        )

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/shapes/',
            token='test-token',
        )

        assert result == body
        assert type(result) is type(body)


class TestHTTPClientDelete:
    @pytest.mark.asyncio
    async def test_delete_success(self, mock_httpx_client):
        """Test successful DELETE request (no content)."""
        mock_response = create_mock_response(
            status_code=HTTPStatus.NO_CONTENT, text_data=''
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.delete(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/delete/123/',
            token='test-token',
        )

        assert result == {'status': 'success', 'status_code': HTTPStatus.NO_CONTENT}

    @pytest.mark.asyncio
    async def test_delete_with_response(self, mock_httpx_client):
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'deleted': True, 'id': 123}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.delete(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/delete/123/',
            token='test-token',
        )

        assert result == {'deleted': True, 'id': 123}


class TestURLConstruction:
    @pytest.mark.asyncio
    async def test_url_construction_all_regions(self, mock_httpx_client):
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'region': 'test'}
        )
        mock_httpx_client.request.return_value = mock_response

        regions = ['ap1', 'us1']
        for region in regions:
            await http_client.get(
                region=region,
                workspace='testworkspace',
                endpoint='/api/test/',
                token='test-token',
            )

        # Verify URLs were constructed correctly
        calls = mock_httpx_client.request.call_args_list
        expected_urls = [
            'https://testworkspace.ap1.alpacon.io/api/test/',
            'https://testworkspace.us1.alpacon.io/api/test/',
        ]
        for i, expected_url in enumerate(expected_urls):
            assert calls[i][1]['url'] == expected_url

    @pytest.mark.asyncio
    async def test_configured_base_url_override_is_used(self, mock_httpx_client):
        """A pinned base URL is used verbatim instead of the derived host (ADR 0027).
        The host is persisted, so a workspace survives a URL slug change.
        """
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'ok': True}
        )
        mock_httpx_client.request.return_value = mock_response

        fake_tm = MagicMock()
        fake_tm.get_base_url_override.return_value = 'https://old-slug.us1.alpacon.io'
        with patch('utils.token_manager.get_token_manager', return_value=fake_tm):
            await http_client.get(
                region='us1',
                workspace='renamed-workspace',
                endpoint='/api/test/',
                token='test-token',
            )

        call = mock_httpx_client.request.call_args_list[-1]
        assert call[1]['url'] == 'https://old-slug.us1.alpacon.io/api/test/'
        fake_tm.get_base_url_override.assert_called_once_with(
            'us1', 'renamed-workspace'
        )

    def test_get_base_url_default_derivation(self):
        """With no override configured, the default Alpacon Cloud host is derived."""
        fake_tm = MagicMock()
        fake_tm.get_base_url_override.return_value = None
        with patch('utils.token_manager.get_token_manager', return_value=fake_tm):
            assert (
                http_client.get_base_url('ap1', 'myws') == 'https://myws.ap1.alpacon.io'
            )

    @pytest.mark.asyncio
    async def test_pinned_base_url_override_used(self, mock_httpx_client):
        """A configured base-URL override replaces the derived host (ADR 0027)."""
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'ok': True}
        )
        mock_httpx_client.request.return_value = mock_response

        mock_tm = MagicMock()
        mock_tm.get_base_url_override.return_value = 'https://pinned.us1.alpacon.io'
        with patch('utils.token_manager.get_token_manager', return_value=mock_tm):
            await http_client.get(
                region='ap1',
                workspace='oldlabel',
                endpoint='/api/test/',
                token='test-token',
            )

        call = mock_httpx_client.request.call_args
        # The stale workspace/region label is ignored in favor of the pinned host.
        assert call[1]['url'] == 'https://pinned.us1.alpacon.io/api/test/'

    def test_get_base_url_falls_back_when_no_override(self):
        """With no override configured, the default Alpacon Cloud host is derived."""
        mock_tm = MagicMock()
        mock_tm.get_base_url_override.return_value = None
        with patch('utils.token_manager.get_token_manager', return_value=mock_tm):
            assert (
                http_client.get_base_url('ap1', 'myws') == 'https://myws.ap1.alpacon.io'
            )


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_network_timeout(self, mock_httpx_client, no_retry_delay):
        mock_httpx_client.request.side_effect = httpx.TimeoutException(
            'Request timeout'
        )

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
        )

        assert isinstance(result, dict)
        assert result['error'] == 'Timeout'

    @pytest.mark.asyncio
    async def test_connection_error(self, mock_httpx_client, no_retry_delay):
        mock_httpx_client.request.side_effect = httpx.ConnectError('Connection failed')

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
        )

        assert isinstance(result, dict)
        assert result['error'] == 'Request Error'

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, mock_httpx_client):
        # Create a response that will cause json() to fail
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.headers = {}
        mock_response.content = b'invalid json response'
        mock_response.text = 'invalid json response'
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = Exception('JSON decode error')

        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
        )

        assert isinstance(result, dict)
        assert result['error'] == 'Unexpected Error'


class TestHTTPClientJWTAuth:
    @pytest.mark.asyncio
    async def test_jwt_token_uses_bearer_header(self, mock_httpx_client):
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'result': 'success'}
        )
        mock_httpx_client.request.return_value = mock_response

        # JWT tokens have 3 dot-separated parts (header.payload.signature)
        jwt_token = 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature'

        await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token=jwt_token,
        )

        call_kwargs = mock_httpx_client.request.call_args
        assert call_kwargs.kwargs['headers']['Authorization'] == f'Bearer {jwt_token}'

    @pytest.mark.asyncio
    async def test_api_token_uses_token_header(self, mock_httpx_client):
        mock_response = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'result': 'success'}
        )
        mock_httpx_client.request.return_value = mock_response

        api_token = 'alpacon-api-token-abc123'

        await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token=api_token,
        )

        call_kwargs = mock_httpx_client.request.call_args
        assert call_kwargs.kwargs['headers']['Authorization'] == f'token={api_token}'

    def test_is_jwt_detection(self):
        assert AlpaconHTTPClient._is_jwt('a.b.c') is True
        assert AlpaconHTTPClient._is_jwt('eyJ.eyJ.sig') is True
        assert AlpaconHTTPClient._is_jwt('simple-token') is False
        assert AlpaconHTTPClient._is_jwt('two.parts') is False
        assert AlpaconHTTPClient._is_jwt('a..c') is False


class TestHandleUpstream401:
    def _make_401_exc(self, json_body=None, text=''):
        """Create a mock HTTPStatusError with 401 response."""
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.UNAUTHORIZED
        mock_response.text = text or str(json_body)
        if json_body is not None:
            mock_response.json.return_value = json_body
        else:
            mock_response.json.side_effect = Exception('No JSON')
        exc = httpx.HTTPStatusError(
            'HTTP 401',
            request=MagicMock(),
            response=mock_response,
        )
        return exc

    def test_mfa_required_detection(self):
        """Detects auth_mfa_required code from response body."""
        exc = self._make_401_exc({'code': 'auth_mfa_required', 'source': 'websh'})
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert result['mfa_required'] is True
        assert result['status_code'] == HTTPStatus.UNAUTHORIZED
        assert result['error'] == 'MFA Required'

    def test_sign_in_mfa_missing_is_detected_as_mfa_required(self):
        """A token without the workspace's sign-in MFA needs the same browser MFA."""
        exc = self._make_401_exc({'code': 'auth_token_mfa_missing'})
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert result['mfa_required'] is True
        assert result['status_code'] == HTTPStatus.UNAUTHORIZED
        assert result['error'] == 'MFA Required'
        assert result['message'] == 'MFA verification required'

    def test_non_string_code_is_not_mfa_required(self, caplog):
        """An unhashable code is a plain 401, not a body that failed to parse."""
        exc = self._make_401_exc({'code': ['auth_token_mfa_missing']})

        with caplog.at_level(logging.DEBUG, logger='alpacon_mcp.http_client'):
            result = AlpaconHTTPClient._handle_upstream_401(exc)

        assert result['mfa_required'] is False
        assert not any('Failed to parse' in r.getMessage() for r in caplog.records)

    def test_missing_token_401_is_not_mfa_required(self):
        """A plain token refusal starts an ordinary re-auth, not an MFA one."""
        exc = self._make_401_exc({'code': 'auth_token_missing'})
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert result['mfa_required'] is False
        assert result['error'] == 'HTTP Error'

    def test_non_mfa_401(self):
        """Regular 401 without MFA code."""
        exc = self._make_401_exc({'detail': 'Unauthorized'})
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert result['mfa_required'] is False
        assert result['error'] == 'HTTP Error'

    def test_non_json_body(self):
        """Handles non-JSON 401 response gracefully."""
        exc = self._make_401_exc(json_body=None, text='Unauthorized')
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert result['mfa_required'] is False
        assert result['status_code'] == HTTPStatus.UNAUTHORIZED

    def test_no_response_body_in_result(self):
        """Error dict should NOT contain raw response body (PII protection)."""
        exc = self._make_401_exc({'code': 'auth_mfa_required', 'source': 'websh'})
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert 'response' not in result

    @patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'true'})
    def test_raises_and_signals_in_remote_mode(self):
        """Raises UpstreamAuthError and records the request signal in remote mode."""
        token = 'header.payload.signature'  # Must pass _is_jwt() check
        exc = self._make_401_exc({'code': 'auth_mfa_required', 'source': 'websh'})
        holder = request_signal.begin_request()

        with pytest.raises(UpstreamAuthError) as exc_info:
            AlpaconHTTPClient._handle_upstream_401(exc, token=token)

        assert exc_info.value.mfa_required is True
        assert exc_info.value.source == 'websh'

        assert holder['mfa_required'] is True
        assert holder['source'] == 'websh'

    @patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'true'})
    def test_sign_in_mfa_missing_signals_mfa_in_remote_mode(self):
        """The middleware reads this signal to put 'mfa' in the re-auth scope."""
        exc = self._make_401_exc({'code': 'auth_token_mfa_missing'})
        holder = request_signal.begin_request()

        with pytest.raises(UpstreamAuthError) as exc_info:
            AlpaconHTTPClient._handle_upstream_401(
                exc, token='header.payload.signature'
            )

        assert exc_info.value.mfa_required is True
        assert holder == {'mfa_required': True, 'source': ''}

    @patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'false'})
    def test_no_signal_in_stdio_mode(self):
        """Does NOT record a signal when auth is disabled (stdio mode)."""
        token = 'header.payload.signature'
        exc = self._make_401_exc({'code': 'auth_mfa_required', 'source': 'websh'})
        holder = request_signal.begin_request()

        AlpaconHTTPClient._handle_upstream_401(exc, token=token)

        assert holder == {}

    def test_upstream_401_decision_logs_at_debug_level(self, caplog):
        """The signaling decision is diagnostic detail, so ALPACON_MCP_LOG_LEVEL must silence it."""
        exc = self._make_401_exc({'detail': 'Unauthorized'})

        with caplog.at_level(logging.DEBUG, logger='alpacon_mcp.http_client'):
            AlpaconHTTPClient._handle_upstream_401(exc)

        records = [
            r for r in caplog.records if r.getMessage().startswith('Upstream 401 -')
        ]
        assert len(records) == 1
        assert 'signaling=False' in records[0].getMessage()
        assert all(r.levelno == logging.DEBUG for r in records)

    @patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'true'})
    def test_upstream_401_that_signals_logs_the_decision_before_raising(self, caplog):
        exc = self._make_401_exc({'detail': 'Unauthorized'})
        request_signal.begin_request()

        with (
            caplog.at_level(logging.DEBUG, logger='alpacon_mcp.http_client'),
            pytest.raises(UpstreamAuthError),
        ):
            AlpaconHTTPClient._handle_upstream_401(
                exc, token='header.payload.signature'
            )

        records = [
            r for r in caplog.records if r.getMessage().startswith('Upstream 401 -')
        ]
        assert len(records) == 1
        assert 'signaling=True' in records[0].getMessage()
        assert records[0].levelno == logging.DEBUG


class TestNoResponseCache:
    """A read is never answered from an earlier response. Reads come back filtered by
    the caller's permissions; a cache would keep serving revoked access.
    """

    LIST_URL = 'https://ws.ap1.alpacon.io/api/servers/servers/'

    @pytest.mark.asyncio
    async def test_a_repeated_read_goes_to_the_network_every_time(
        self, mock_httpx_client
    ):
        mock_httpx_client.request.return_value = create_mock_response(
            json_data={'results': []}
        )

        for _ in range(2):
            await http_client.request(method='GET', url=self.LIST_URL)

        assert mock_httpx_client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_a_second_token_gets_its_own_request(self, mock_httpx_client):
        mock_httpx_client.request.return_value = create_mock_response(
            json_data={'results': []}
        )

        for token in ('token-a', 'token-b'):
            await http_client.request(method='GET', url=self.LIST_URL, token=token)

        sent = [
            call.kwargs['headers']['Authorization']
            for call in mock_httpx_client.request.call_args_list
        ]
        assert sent == ['token=token-a', 'token=token-b']


@pytest.mark.asyncio
async def test_delete_forwards_query_parameters():
    """A DELETE whose behavior is decided by the query string must carry it."""
    with patch.object(
        http_client, 'request', new=AsyncMock(return_value={})
    ) as mock_request:
        await http_client.delete(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/',
            token='test-token',
            params={'auto': 'true'},
        )

    mock_request.assert_called_once_with(
        method='DELETE',
        url=ANY,
        token='test-token',
        params={'auto': 'true'},
    )
    assert mock_request.call_args.kwargs['url'].endswith(
        f'/api/servers/servers/{SERVER_ID}/'
    )


class TestDebugLogPayloadsAreLazy:
    """Below DEBUG level the client must not render payloads it then throws away."""

    @pytest.mark.asyncio
    async def test_no_payload_is_built_when_debug_is_off(self, mock_httpx_client):
        """A large response is repr'd on the event loop unless the calls are lazy."""
        mock_httpx_client.request.return_value = create_mock_response(
            status_code=HTTPStatus.OK,
            json_data={'servers': ['a', 'b']},
            headers={'content-type': 'application/json'},
        )

        with patch('utils.http_client.logger') as mock_logger:
            mock_logger.isEnabledFor.return_value = False
            await http_client.get(
                region='ap1',
                workspace='testworkspace',
                endpoint='/api/test/',
                token='test-token',
            )

        messages = [
            call.args[0] for call in mock_logger.debug.call_args_list if call.args
        ]
        assert not [m for m in messages if m.startswith('Request headers')]
        assert not [m for m in messages if m.startswith('Response headers')]

    @pytest.mark.asyncio
    async def test_response_body_is_passed_as_a_lazy_argument(self, mock_httpx_client):
        """The body reaches the logger as an argument, reduced to its field names."""
        payload = {'servers': ['a', 'b']}
        mock_httpx_client.request.return_value = create_mock_response(
            status_code=HTTPStatus.OK, json_data=payload
        )

        with patch('utils.http_client.logger') as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            await http_client.get(
                region='ap1',
                workspace='testworkspace',
                endpoint='/api/test/',
                token='test-token',
            )

        body_calls = [
            call
            for call in mock_logger.debug.call_args_list
            if call.args and call.args[0].startswith('Response body')
        ]
        assert body_calls
        assert '%s' in body_calls[0].args[0]
        assert body_calls[0].args[1:] == ({'servers': '<list items=2>'},)

    @pytest.mark.asyncio
    async def test_request_and_empty_response_payloads_are_lazy_arguments(
        self, mock_httpx_client
    ):
        """Every payload the client logs reaches the logger unrendered, by field name."""
        params: dict[str, int | str] = {'page': 1, 'search': 'db-prod'}
        data = {'name': 'web-01'}
        mock_httpx_client.request.return_value = create_mock_response(
            status_code=HTTPStatus.OK
        )

        with patch('utils.http_client.logger') as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            await http_client.post(
                region='ap1',
                workspace='testworkspace',
                endpoint='/api/test/',
                token='test-token',
                data=data,
                params=params,
            )

        logged = {
            call.args[0]: call.args[1:]
            for call in mock_logger.debug.call_args_list
            if call.args
        }

        def payload_for(prefix):
            fmt = next(m for m in logged if m.startswith(prefix))
            assert '%s' in fmt
            return logged[fmt]

        assert payload_for('Request params') == ({'page': 1, 'search': '<str len=7>'},)
        assert payload_for('Request body') == ({'name': '<str len=6>'},)
        assert payload_for('Empty response') == (
            {'status': 'success', 'status_code': HTTPStatus.OK},
        )


class TestUpstreamAuthErrorReachesTheClient:
    """The SDK boundary that turns a bare Exception into 'Error executing tool <name>'."""

    async def test_upstream_auth_error_message_survives_the_tool_boundary(self, caplog):
        mcp_server = MCPServer(name='test-upstream-auth-error')

        @mcp_server.tool()
        async def failing_tool() -> str:
            raise UpstreamAuthError(mfa_required=True, source='websh')

        with caplog.at_level(logging.ERROR, logger='mcp.server.mcpserver.server'):
            result = await mcp_server._handle_call_tool(
                ServerRequestContext(
                    session=MagicMock(),
                    lifespan_context={},
                    protocol_version=LATEST_PROTOCOL_VERSION,
                    method='tools/call',
                ),
                CallToolRequestParams(name='failing_tool', arguments={}),
            )

        assert isinstance(result, CallToolResult)
        assert result.is_error is True
        content = result.content[0]
        assert isinstance(content, TextContent)
        # A plain Exception collapses to just this prefix; ToolError keeps the
        # original message after it.
        assert content.text == (
            'Error executing tool failing_tool: MFA verification required'
        )
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)


class TestHTTPVerbsConstant:
    NON_VERB_ASYNC_METHODS = frozenset({'close', 'request'})

    def test_covers_every_public_async_client_method(self):
        public_async = {
            name
            for name, _ in inspect.getmembers(
                AlpaconHTTPClient, inspect.iscoroutinefunction
            )
            if not name.startswith('_')
        }

        assert set(HTTP_VERBS) == public_async - self.NON_VERB_ASYNC_METHODS


COMMAND_URL = 'https://ws.ap1.alpacon.io/api/events/commands/'
SERVERS_URL = 'https://ws.ap1.alpacon.io/api/servers/servers/'
NON_IDEMPOTENT = pytest.mark.parametrize('method', ['POST', 'PATCH'])
IDEMPOTENT = pytest.mark.parametrize('method', ['GET', 'PUT', 'DELETE'])
MAY_HAVE_LANDED = pytest.mark.parametrize(
    ('error', 'expected'),
    [
        (httpx.ReadTimeout, 'Timeout'),
        (httpx.WriteTimeout, 'Timeout'),
        (httpx.ReadError, 'Request Error'),
        (httpx.RemoteProtocolError, 'Request Error'),
        (httpx.LocalProtocolError, 'Request Error'),
    ],
)
NEVER_SENT = pytest.mark.parametrize(
    ('error', 'expected'),
    [
        (httpx.ConnectError, 'Request Error'),
        (httpx.ConnectTimeout, 'Timeout'),
        (httpx.PoolTimeout, 'Timeout'),
        (httpx.ProxyError, 'Request Error'),
        (httpx.UnsupportedProtocol, 'Request Error'),
    ],
)
CREATED = (HTTPStatus.CREATED, {'id': 'command-1'})


def scripted(*steps: type[httpx.TransportError] | tuple[int, Mapping[str, str]]):
    """A transport raising or answering each step in turn, and the requests it saw."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        step = steps[min(len(seen), len(steps)) - 1]
        if isinstance(step, tuple):
            status, body = step
            return httpx.Response(status, json=body)
        raise step('scripted failure', request=request)

    return httpx.MockTransport(answer), seen


class TestNonIdempotentRequestIsNotReplayed:
    @NON_IDEMPOTENT
    @MAY_HAVE_LANDED
    async def test_request_that_may_have_reached_the_server_is_sent_once(
        self, make_client, method, error, expected
    ):
        transport, seen = scripted(error, CREATED)
        client = make_client(transport)

        result = await client.request(method, COMMAND_URL, json_data={'line': 'ls'})

        assert [r.method for r in seen] == [method]
        assert result['error'] == expected
        assert result['outcome_unknown'] is True
        assert result['message'].endswith(
            f'The {method} was not resent: the server may already have acted on it.'
        )

    @NON_IDEMPOTENT
    @pytest.mark.parametrize(
        ('body', 'error_code'),
        [({'code': 'db_unavailable'}, 'db_unavailable'), ({}, None)],
    )
    async def test_server_error_is_returned_without_a_second_request(
        self, make_client, method, body, error_code
    ):
        transport, seen = scripted((HTTPStatus.BAD_GATEWAY, body), CREATED)
        client = make_client(transport)

        result = await client.request(method, COMMAND_URL, json_data={'line': 'ls'})

        assert len(seen) == 1
        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == HTTPStatus.BAD_GATEWAY
        assert result.get('error_code') == error_code
        assert result['outcome_unknown'] is True

    @NON_IDEMPOTENT
    async def test_credential_check_outage_is_retried_as_never_reaching_a_view(
        self, make_client, method
    ):
        unavailable = (
            HTTPStatus.SERVICE_UNAVAILABLE,
            {'code': 'auth_verification_unavailable'},
        )
        transport, seen = scripted(unavailable, CREATED)
        client = make_client(transport)

        result = await client.request(method, COMMAND_URL, json_data={'line': 'ls'})

        assert len(seen) == 2
        assert result == {'id': 'command-1'}

    async def test_post_credential_check_outage_exhausts_retries_with_a_known_outcome(
        self, make_client
    ):
        transport, seen = scripted(
            (HTTPStatus.SERVICE_UNAVAILABLE, {'code': 'auth_verification_unavailable'})
        )
        client = make_client(transport)

        result = await client.request('POST', COMMAND_URL, json_data={'line': 'ls'})

        assert len(seen) == client.max_retries
        assert result['error_code'] == 'auth_verification_unavailable'
        assert 'outcome_unknown' not in result

    @NON_IDEMPOTENT
    @NEVER_SENT
    async def test_request_that_never_left_is_retried_and_succeeds(
        self, make_client, method, error, expected
    ):
        transport, seen = scripted(error, CREATED)
        client = make_client(transport)

        result = await client.request(method, COMMAND_URL, json_data={'line': 'ls'})

        assert len(seen) == 2
        assert result == {'id': 'command-1'}

    @NON_IDEMPOTENT
    @NEVER_SENT
    async def test_request_that_never_left_exhausts_retries_with_a_known_outcome(
        self, make_client, method, error, expected
    ):
        transport, seen = scripted(error)
        client = make_client(transport)

        result = await client.request(method, COMMAND_URL, json_data={'line': 'ls'})

        assert len(seen) == client.max_retries
        assert result['error'] == expected
        assert 'outcome_unknown' not in result

    @NON_IDEMPOTENT
    async def test_retry_after_a_failed_connect_stops_at_the_first_lost_response(
        self, make_client, method
    ):
        transport, seen = scripted(httpx.ConnectError, httpx.ReadTimeout, CREATED)
        client = make_client(transport)

        result = await client.request(method, COMMAND_URL, json_data={'line': 'ls'})

        assert len(seen) == 2  # only the second attempt could have reached the server
        assert result['outcome_unknown'] is True

    async def test_post_answered_with_an_unreadable_body_may_have_run(
        self, make_client
    ):
        client = make_client(
            httpx.MockTransport(
                lambda request: httpx.Response(HTTPStatus.OK, text='<html>ok</html>')
            )
        )

        result = await client.request('POST', COMMAND_URL, json_data={'line': 'ls'})

        assert result['error'] == 'Unexpected Error'
        assert result['outcome_unknown'] is True


class TestIdempotentRequestIsRetried:
    @IDEMPOTENT
    async def test_request_whose_response_timed_out_is_retried(
        self, make_client, method
    ):
        transport, seen = scripted(httpx.ReadTimeout, (HTTPStatus.OK, {'id': 'x'}))
        client = make_client(transport)

        result = await client.request(method, SERVERS_URL)

        assert len(seen) == 2
        assert result == {'id': 'x'}

    @IDEMPOTENT
    async def test_server_error_is_retried(self, make_client, method):
        transport, seen = scripted(
            (HTTPStatus.BAD_GATEWAY, {}), (HTTPStatus.OK, {'id': 'x'})
        )
        client = make_client(transport)

        result = await client.request(method, SERVERS_URL)

        assert len(seen) == 2
        assert result == {'id': 'x'}

    @IDEMPOTENT
    async def test_exhausted_retries_carry_no_outcome_unknown(
        self, make_client, method
    ):
        transport, seen = scripted(httpx.ReadTimeout)
        client = make_client(transport)

        result = await client.request(method, SERVERS_URL)

        assert len(seen) == client.max_retries
        assert result['error'] == 'Timeout'
        assert 'outcome_unknown' not in result
