"""
Unit tests for webftp_tools module.

Tests WebFTP functionality including session management, file uploads,
file downloads, and file transfer history.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.webftp_tools import (
    _STATUS_ERROR,
    _aiter_file,
    _ensure_parent_dir,
    _LocalSaveError,
    _S3DownloadError,
    _save_stream,
    webftp_bulk_download,
    webftp_bulk_upload,
    webftp_download_file,
    webftp_downloads_list,
    webftp_session_create,
    webftp_sessions_list,
    webftp_upload_file,
    webftp_uploads_list,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.webftp_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


@pytest.fixture
def mock_httpx():
    """Mock httpx for S3 operations."""
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        yield mock_client


class TestWebFtpSessionCreate:
    """Test webftp_session_create function."""

    @pytest.mark.asyncio
    async def test_session_create_success(self, mock_http_client, mock_token_manager):
        """Test successful WebFTP session creation."""

        # Mock successful response
        mock_http_client.post.return_value = {
            'id': 'session-123',
            'server': '550e8400-e29b-41d4-a716-446655440001',
            'username': 'testuser',
            'created_at': '2024-01-01T00:00:00Z',
        }

        result = await webftp_session_create(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            workspace='testworkspace',
            username='testuser',
            region='ap1',
        )

        # Verify response structure
        assert result['status'] == 'success'
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'
        assert result['username'] == 'testuser'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result

        # Verify HTTP client was called correctly
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/webftp/sessions/',
            token='test-token',
            data={
                'server': '550e8400-e29b-41d4-a716-446655440001',
                'username': 'testuser',
            },
        )

    @pytest.mark.asyncio
    async def test_session_create_without_username(
        self, mock_http_client, mock_token_manager
    ):
        """Test WebFTP session creation without username."""

        mock_http_client.post.return_value = {'id': 'session-123'}

        result = await webftp_session_create(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['username'] is None

        # Verify username was not included in data
        call_args = mock_http_client.post.call_args
        assert 'username' not in call_args[1]['data']

    @pytest.mark.asyncio
    async def test_session_create_no_token(self, mock_http_client, mock_token_manager):
        """Test session creation when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await webftp_session_create(
            server_id='550e8400-e29b-41d4-a716-446655440001', workspace='testworkspace'
        )

        assert result['status'] == _STATUS_ERROR
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_create_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test session creation with HTTP error."""

        mock_http_client.post.side_effect = Exception('HTTP 500 Internal Server Error')

        result = await webftp_session_create(
            server_id='550e8400-e29b-41d4-a716-446655440001', workspace='testworkspace'
        )

        assert result['status'] == _STATUS_ERROR
        assert 'HTTP 500' in result['message']


class TestWebFtpSessionsList:
    """Test webftp_sessions_list function."""

    @pytest.mark.asyncio
    async def test_sessions_list_success(self, mock_http_client, mock_token_manager):
        """Test successful WebFTP sessions listing."""

        # Mock successful response
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {
                    'id': 'session-123',
                    'server': '550e8400-e29b-41d4-a716-446655440001',
                    'username': 'testuser1',
                    'created_at': '2024-01-01T00:00:00Z',
                },
                {
                    'id': 'session-124',
                    'server': '550e8400-e29b-41d4-a716-446655440002',
                    'username': 'testuser2',
                    'created_at': '2024-01-01T00:01:00Z',
                },
            ],
        }

        result = await webftp_sessions_list(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert result['server_id'] is None
        assert result['data']['count'] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/webftp/sessions/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_sessions_list_with_server_filter(
        self, mock_http_client, mock_token_manager
    ):
        """Test sessions listing with server filter."""

        mock_http_client.get.return_value = {'count': 1, 'results': []}

        result = await webftp_sessions_list(
            workspace='testworkspace',
            server_id='550e8400-e29b-41d4-a716-446655440001',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'

        # Verify server filter was applied
        call_args = mock_http_client.get.call_args
        assert (
            call_args[1]['params']['server'] == '550e8400-e29b-41d4-a716-446655440001'
        )

    @pytest.mark.asyncio
    async def test_sessions_list_no_token(self, mock_http_client, mock_token_manager):
        """Test sessions listing when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await webftp_sessions_list(workspace='testworkspace')

        assert result['status'] == _STATUS_ERROR
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()


class TestWebFtpUploadFile:
    """Test webftp_upload_file function."""

    @pytest.mark.asyncio
    async def test_upload_file_success_with_s3(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful file upload with S3."""

        # Mock file content
        file_content = b'test file content'

        with patch.object(Path, 'read_bytes', return_value=file_content):
            # Mock API response with S3 URL
            mock_http_client.post.return_value = {
                'id': 'upload-123',
                'name': 'test.txt',
                'upload_url': 'https://s3.amazonaws.com/bucket/presigned-url',
                'download_url': 'https://s3.amazonaws.com/bucket/download-url',
            }

            # Mock httpx directly within the context
            with patch('httpx.AsyncClient') as mock_httpx_class:
                mock_client = AsyncMock()
                mock_httpx_class.return_value.__aenter__.return_value = mock_client

                # Mock S3 upload response - use MagicMock not AsyncMock for response
                mock_s3_response = MagicMock()
                mock_s3_response.status_code = 200
                mock_s3_response.text = 'Success'
                mock_client.put = AsyncMock(return_value=mock_s3_response)

                # Mock upload trigger response
                mock_http_client.get.return_value = {'status': 'processed'}

                result = await webftp_upload_file(
                    server_id='550e8400-e29b-41d4-a716-446655440001',
                    local_file_path='/local/test.txt',
                    remote_file_path='/remote/test.txt',
                    workspace='testworkspace',
                    username='testuser',
                    region='ap1',
                )

                assert result['status'] == 'success'
                assert 'uploaded successfully and processed' in result['message']
                assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'
                assert result['local_file_path'] == '/local/test.txt'
                assert result['remote_file_path'] == '/remote/test.txt'
                assert result['file_size'] == len(file_content)
                assert 'upload_url' in result
                assert 'download_url' in result

                # Verify API calls
                mock_http_client.post.assert_called_once()
                mock_client.put.assert_called_once_with(
                    'https://s3.amazonaws.com/bucket/presigned-url',
                    content=file_content,
                )
                mock_http_client.get.assert_called_once_with(
                    region='ap1',
                    workspace='testworkspace',
                    endpoint='/api/webftp/uploads/upload-123/upload/',
                    token='test-token',
                )

    @pytest.mark.asyncio
    async def test_upload_file_success_direct(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful file upload without S3."""

        file_content = b'test file content'

        with patch.object(Path, 'read_bytes', return_value=file_content):
            # Mock API response without S3 URL
            mock_http_client.post.return_value = {
                'id': 'upload-123',
                'name': 'test.txt',
            }

            result = await webftp_upload_file(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                local_file_path='/local/test.txt',
                remote_file_path='/remote/test.txt',
                workspace='testworkspace',
            )

            assert result['status'] == 'success'
            assert 'direct upload' in result['message']
            assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'

    @pytest.mark.asyncio
    async def test_upload_file_not_found(self, mock_http_client, mock_token_manager):
        """Test file upload when local file doesn't exist."""

        with patch.object(
            Path,
            'read_bytes',
            side_effect=FileNotFoundError('File not found'),
        ):
            result = await webftp_upload_file(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                local_file_path='/nonexistent/test.txt',
                remote_file_path='/remote/test.txt',
                workspace='testworkspace',
            )

            assert result['status'] == _STATUS_ERROR
            assert 'Local file not found' in result['message']
            mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_file_s3_error(
        self, mock_http_client, mock_token_manager, mock_httpx
    ):
        """Test file upload with S3 error."""

        file_content = b'test file content'

        with patch.object(Path, 'read_bytes', return_value=file_content):
            mock_http_client.post.return_value = {
                'id': 'upload-123',
                'upload_url': 'https://s3.amazonaws.com/bucket/presigned-url',
            }

            # Mock S3 error response
            mock_s3_response = MagicMock()
            mock_s3_response.status_code = 500
            mock_s3_response.text = 'Internal Server Error'
            mock_httpx.put.return_value = mock_s3_response

            result = await webftp_upload_file(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                local_file_path='/local/test.txt',
                remote_file_path='/remote/test.txt',
                workspace='testworkspace',
            )

            assert result['status'] == _STATUS_ERROR
            assert 'Failed to upload to S3' in result['message']

    @pytest.mark.asyncio
    async def test_upload_file_no_token(self, mock_http_client, mock_token_manager):
        """Test file upload when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await webftp_upload_file(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            local_file_path='/local/test.txt',
            remote_file_path='/remote/test.txt',
            workspace='testworkspace',
        )

        assert result['status'] == _STATUS_ERROR
        assert 'No token found' in result['message']


class TestWebFtpDownloadFile:
    """Test webftp_download_file function."""

    @pytest.mark.asyncio
    async def test_download_file_success(self, mock_http_client, mock_token_manager):
        """Test successful file download."""

        # Mock API response with S3 URL
        mock_http_client.post.return_value = {
            'id': 'download-123',
            'name': 'test.txt',
            'download_url': 'https://s3.amazonaws.com/bucket/download-url',
        }

        file_content = b'downloaded file content'
        with patch(
            'tools.webftp_tools._stream_s3_to_file',
            new=AsyncMock(return_value=len(file_content)),
        ) as mock_stream:
            result = await webftp_download_file(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                remote_file_path='/remote/test.txt',
                local_file_path='/local/test.txt',
                workspace='testworkspace',
                username='testuser',
                region='ap1',
            )

            assert result['status'] == 'success'
            assert 'downloaded successfully' in result['message']
            assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'
            assert result['remote_file_path'] == '/remote/test.txt'
            assert result['local_file_path'] == '/local/test.txt'
            assert result['file_size'] == len(file_content)
            assert result['resource_type'] == 'file'

            mock_stream.assert_called_once_with(
                'https://s3.amazonaws.com/bucket/download-url',
                '/local/test.txt',
            )

    @pytest.mark.asyncio
    async def test_download_folder_success(self, mock_http_client, mock_token_manager):
        """Test successful folder download as zip."""

        mock_http_client.post.return_value = {
            'id': 'download-123',
            'name': 'folder.zip',
            'download_url': 'https://s3.amazonaws.com/bucket/download-url',
        }

        with patch(
            'tools.webftp_tools._stream_s3_to_file',
            new=AsyncMock(return_value=16),
        ):
            result = await webftp_download_file(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                remote_file_path='/remote/folder',
                local_file_path='/local/folder.zip',
                workspace='testworkspace',
                resource_type='folder',
            )

            assert result['status'] == 'success'
            assert result['resource_type'] == 'folder'

            # Verify correct data was sent to API
            call_args = mock_http_client.post.call_args
            assert call_args[1]['data']['resource_type'] == 'folder'
            assert call_args[1]['data']['name'] == 'folder.zip'

    @pytest.mark.asyncio
    async def test_download_file_direct_mode(
        self, mock_http_client, mock_token_manager
    ):
        """Test file download without S3 (direct mode)."""

        # Mock API response without S3 URL
        mock_http_client.post.return_value = {'id': 'download-123', 'name': 'test.txt'}

        result = await webftp_download_file(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            remote_file_path='/remote/test.txt',
            local_file_path='/local/test.txt',
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert 'Download request created' in result['message']
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'

    @pytest.mark.asyncio
    async def test_download_file_s3_error(self, mock_http_client, mock_token_manager):
        """Test file download with S3 error."""

        mock_http_client.post.return_value = {
            'id': 'download-123',
            'download_url': 'https://s3.amazonaws.com/bucket/download-url',
        }

        with patch(
            'tools.webftp_tools._stream_s3_to_file',
            new=AsyncMock(side_effect=_S3DownloadError('404 - Not Found')),
        ):
            result = await webftp_download_file(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                remote_file_path='/remote/test.txt',
                local_file_path='/local/test.txt',
                workspace='testworkspace',
            )

        assert result['status'] == _STATUS_ERROR
        assert 'Failed to download from S3' in result['message']

    @pytest.mark.asyncio
    async def test_download_file_save_error(self, mock_http_client, mock_token_manager):
        """Test file download with local save error."""

        mock_http_client.post.return_value = {
            'id': 'download-123',
            'download_url': 'https://s3.amazonaws.com/bucket/download-url',
        }

        with patch(
            'tools.webftp_tools._stream_s3_to_file',
            new=AsyncMock(side_effect=_LocalSaveError('Permission denied')),
        ):
            result = await webftp_download_file(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                remote_file_path='/remote/test.txt',
                local_file_path='/local/test.txt',
                workspace='testworkspace',
            )

        assert result['status'] == _STATUS_ERROR
        assert 'Failed to save file locally' in result['message']

    @pytest.mark.asyncio
    async def test_download_file_no_token(self, mock_http_client, mock_token_manager):
        """Test file download when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await webftp_download_file(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            remote_file_path='/remote/test.txt',
            local_file_path='/local/test.txt',
            workspace='testworkspace',
        )

        assert result['status'] == _STATUS_ERROR
        assert 'No token found' in result['message']


class TestWebFtpUploadsList:
    """Test webftp_uploads_list function."""

    @pytest.mark.asyncio
    async def test_uploads_list_success(self, mock_http_client, mock_token_manager):
        """Test successful uploads list retrieval."""

        # Mock successful response
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {
                    'id': 'upload-123',
                    'name': 'file1.txt',
                    'server': '550e8400-e29b-41d4-a716-446655440001',
                    'created_at': '2024-01-01T00:00:00Z',
                },
                {
                    'id': 'upload-124',
                    'name': 'file2.txt',
                    'server': '550e8400-e29b-41d4-a716-446655440002',
                    'created_at': '2024-01-01T00:01:00Z',
                },
            ],
        }

        result = await webftp_uploads_list(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert result['data']['count'] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/webftp/uploads/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_uploads_list_with_server_filter(
        self, mock_http_client, mock_token_manager
    ):
        """Test uploads list with server filter."""

        mock_http_client.get.return_value = {'count': 1, 'results': []}

        result = await webftp_uploads_list(
            workspace='testworkspace', server_id='550e8400-e29b-41d4-a716-446655440001'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'

        # Verify server filter was applied
        call_args = mock_http_client.get.call_args
        assert (
            call_args[1]['params']['server'] == '550e8400-e29b-41d4-a716-446655440001'
        )

    @pytest.mark.asyncio
    async def test_uploads_list_no_token(self, mock_http_client, mock_token_manager):
        """Test uploads list when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await webftp_uploads_list(workspace='testworkspace')

        assert result['status'] == _STATUS_ERROR
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_uploads_list_http_error(self, mock_http_client, mock_token_manager):
        """Test uploads list with HTTP error."""

        mock_http_client.get.side_effect = Exception('HTTP 500 Internal Server Error')

        result = await webftp_uploads_list(workspace='testworkspace')

        assert result['status'] == _STATUS_ERROR
        assert 'HTTP 500' in result['message']


class TestWebFtpDownloadsList:
    """Test webftp_downloads_list function."""

    @pytest.mark.asyncio
    async def test_downloads_list_success(self, mock_http_client, mock_token_manager):
        """Test successful downloads list retrieval."""

        # Mock successful response
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {
                    'id': 'download-123',
                    'name': 'file1.txt',
                    'server': '550e8400-e29b-41d4-a716-446655440001',
                    'created_at': '2024-01-01T00:00:00Z',
                },
                {
                    'id': 'download-124',
                    'name': 'file2.txt',
                    'server': '550e8400-e29b-41d4-a716-446655440002',
                    'created_at': '2024-01-01T00:01:00Z',
                },
            ],
        }

        result = await webftp_downloads_list(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert result['data']['count'] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/webftp/downloads/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_downloads_list_with_server_filter(
        self, mock_http_client, mock_token_manager
    ):
        """Test downloads list with server filter."""

        mock_http_client.get.return_value = {'count': 1, 'results': []}

        result = await webftp_downloads_list(
            workspace='testworkspace', server_id='550e8400-e29b-41d4-a716-446655440001'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'

        # Verify server filter was applied
        call_args = mock_http_client.get.call_args
        assert (
            call_args[1]['params']['server'] == '550e8400-e29b-41d4-a716-446655440001'
        )

    @pytest.mark.asyncio
    async def test_downloads_list_no_token(self, mock_http_client, mock_token_manager):
        """Test downloads list when no token is available."""

        mock_token_manager.get_token.return_value = None

        result = await webftp_downloads_list(workspace='testworkspace')

        assert result['status'] == _STATUS_ERROR
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_downloads_list_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test downloads list with HTTP error."""

        mock_http_client.get.side_effect = Exception('HTTP 500 Internal Server Error')

        result = await webftp_downloads_list(workspace='testworkspace')

        assert result['status'] == _STATUS_ERROR
        assert 'HTTP 500' in result['message']


class TestWebFtpBulkUpload:
    """Test webftp_bulk_upload function."""

    SERVER_ID = '550e8400-e29b-41d4-a716-446655440001'

    @staticmethod
    def _patch_local_file_checks():
        """Patch path/access/stat checks so validation passes."""
        stat_result = MagicMock()
        stat_result.st_size = 100
        return (
            patch('pathlib.Path.is_file', return_value=True),
            patch('tools.webftp_tools.os.access', return_value=True),
            patch('tools.webftp_tools.os.stat', return_value=stat_result),
        )

    @staticmethod
    def _bulk_create_response(count: int) -> list[dict]:
        return [
            {'id': f'upload-{i}', 'upload_url': f'https://s3.example.com/p{i}'}
            for i in range(count)
        ]

    @pytest.mark.asyncio
    async def test_bulk_upload_success_all(self, mock_http_client, mock_token_manager):
        """All three uploads succeed; counts reflect that."""

        mock_http_client.post.side_effect = [self._bulk_create_response(3), None]

        is_file, os_access, os_stat = self._patch_local_file_checks()
        with is_file, os_access, os_stat, patch('httpx.AsyncClient') as httpx_cls:
            client = AsyncMock()
            httpx_cls.return_value.__aenter__.return_value = client
            ok = MagicMock(status_code=200)
            client.put = AsyncMock(return_value=ok)

            result = await webftp_bulk_upload(
                server_id=self.SERVER_ID,
                local_file_paths=['/local/a.txt', '/local/b.txt', '/local/c.txt'],
                remote_directory='/remote/',
                workspace='ws',
            )

        assert result['status'] == 'success'
        assert result['successful_count'] == 3
        assert result['failed_count'] == 0
        assert all(r['status'] == 'uploaded' for r in result['data'])

    @pytest.mark.asyncio
    async def test_bulk_upload_partial_success(
        self, mock_http_client, mock_token_manager
    ):
        """One S3 PUT returns 500; counts split accordingly."""

        mock_http_client.post.side_effect = [self._bulk_create_response(3), None]

        is_file, os_access, os_stat = self._patch_local_file_checks()
        with is_file, os_access, os_stat, patch('httpx.AsyncClient') as httpx_cls:
            client = AsyncMock()
            httpx_cls.return_value.__aenter__.return_value = client
            client.put = AsyncMock(
                side_effect=[
                    MagicMock(status_code=200),
                    MagicMock(status_code=500),
                    MagicMock(status_code=200),
                ]
            )

            result = await webftp_bulk_upload(
                server_id=self.SERVER_ID,
                local_file_paths=['/local/a.txt', '/local/b.txt', '/local/c.txt'],
                remote_directory='/remote/',
                workspace='ws',
            )

        assert result['successful_count'] == 2
        assert result['failed_count'] == 1
        statuses = [r['status'] for r in result['data']]
        assert statuses.count('uploaded') == 2
        assert statuses.count('failed') == 1

    @staticmethod
    def _fake_gather(return_value):
        """Build a gather replacement that closes incoming coroutines.

        Closing them avoids 'coroutine was never awaited' warnings since the
        test bypasses the real gather and never awaits the supplied tasks.
        """
        captured: dict = {}

        async def fake(*coros, **kwargs):
            captured['kwargs'] = kwargs
            for coro in coros:
                close = getattr(coro, 'close', None)
                if callable(close):
                    close()
            return return_value

        fake.captured = captured  # type: ignore[attr-defined]
        return fake

    @pytest.mark.asyncio
    async def test_bulk_upload_uses_return_exceptions(
        self, mock_http_client, mock_token_manager
    ):
        """asyncio.gather must be called with return_exceptions=True."""

        mock_http_client.post.side_effect = [self._bulk_create_response(2), None]

        is_file, os_access, os_stat = self._patch_local_file_checks()
        fake = self._fake_gather(
            [
                {
                    'file': 'a.txt',
                    'status': 'uploaded',
                    'file_id': 'upload-0',
                    'size': 100,
                },
                {
                    'file': 'b.txt',
                    'status': 'uploaded',
                    'file_id': 'upload-1',
                    'size': 100,
                },
            ]
        )
        with (
            is_file,
            os_access,
            os_stat,
            patch('httpx.AsyncClient'),
            patch('tools.webftp_tools.asyncio.gather', new=fake),
        ):
            await webftp_bulk_upload(
                server_id=self.SERVER_ID,
                local_file_paths=['/local/a.txt', '/local/b.txt'],
                remote_directory='/remote/',
                workspace='ws',
            )

        assert fake.captured['kwargs'].get('return_exceptions') is True

    @pytest.mark.asyncio
    async def test_bulk_upload_normalizes_exception_to_error_dict(
        self, mock_http_client, mock_token_manager
    ):
        """An Exception in gather output is normalized using the file index."""

        mock_http_client.post.side_effect = [self._bulk_create_response(3), None]

        is_file, os_access, os_stat = self._patch_local_file_checks()
        mixed_results = [
            {'file': 'a.txt', 'status': 'uploaded', 'file_id': 'upload-0', 'size': 100},
            RuntimeError('boom'),
            {'file': 'c.txt', 'status': 'uploaded', 'file_id': 'upload-2', 'size': 100},
        ]
        with (
            is_file,
            os_access,
            os_stat,
            patch('httpx.AsyncClient'),
            patch(
                'tools.webftp_tools.asyncio.gather',
                new=self._fake_gather(mixed_results),
            ),
        ):
            result = await webftp_bulk_upload(
                server_id=self.SERVER_ID,
                local_file_paths=['/local/a.txt', '/local/b.txt', '/local/c.txt'],
                remote_directory='/remote/',
                workspace='ws',
            )

        data = result['data']
        assert data[1]['status'] == _STATUS_ERROR
        assert data[1]['file'] == 'b.txt'
        assert 'boom' in data[1]['message']
        assert result['successful_count'] == 2
        assert result['failed_count'] == 1

    @pytest.mark.asyncio
    async def test_bulk_upload_baseexception_propagates(
        self, mock_http_client, mock_token_manager
    ):
        """Non-Exception BaseException in gather output is re-raised, not swallowed."""

        mock_http_client.post.side_effect = [self._bulk_create_response(2), None]

        is_file, os_access, os_stat = self._patch_local_file_checks()
        with (
            is_file,
            os_access,
            os_stat,
            patch('httpx.AsyncClient'),
            patch(
                'tools.webftp_tools.asyncio.gather',
                new=self._fake_gather([KeyboardInterrupt(), {'file': 'b.txt'}]),
            ),
            pytest.raises(KeyboardInterrupt),
        ):
            await webftp_bulk_upload(
                server_id=self.SERVER_ID,
                local_file_paths=['/local/a.txt', '/local/b.txt'],
                remote_directory='/remote/',
                workspace='ws',
            )

    @pytest.mark.asyncio
    async def test_bulk_upload_empty_paths(self, mock_http_client, mock_token_manager):
        """Empty local_file_paths returns an error without API calls."""

        result = await webftp_bulk_upload(
            server_id=self.SERVER_ID,
            local_file_paths=[],
            remote_directory='/remote/',
            workspace='ws',
        )

        assert result['status'] == _STATUS_ERROR
        assert 'must not be empty' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_upload_invalid_path(self, mock_http_client, mock_token_manager):
        """A path-traversal local path is rejected by validation."""

        result = await webftp_bulk_upload(
            server_id=self.SERVER_ID,
            local_file_paths=['../../etc/passwd'],
            remote_directory='/remote/',
            workspace='ws',
        )

        assert result['status'] == _STATUS_ERROR
        mock_http_client.post.assert_not_called()


class TestWebFtpBulkDownload:
    """Test webftp_bulk_download function."""

    SERVER_ID = '550e8400-e29b-41d4-a716-446655440001'

    @pytest.mark.asyncio
    async def test_bulk_download_success(self, mock_http_client, mock_token_manager):
        """Successful streaming download returns size and metadata."""

        mock_http_client.post.return_value = {
            'id': 'bulk-1',
            'download_url': 'https://s3.example.com/zip',
        }
        with patch(
            'tools.webftp_tools._stream_s3_to_file',
            new=AsyncMock(return_value=2048),
        ) as mock_stream:
            result = await webftp_bulk_download(
                server_id=self.SERVER_ID,
                remote_paths=['/remote/a.txt', '/remote/b.txt'],
                local_file_path='/local/out.zip',
                workspace='ws',
            )

        assert result['status'] == 'success'
        assert result['file_size'] == 2048
        assert result['local_file_path'] == '/local/out.zip'
        mock_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_download_s3_error(self, mock_http_client, mock_token_manager):
        """An _S3DownloadError is surfaced with download_url context."""

        mock_http_client.post.return_value = {
            'id': 'bulk-1',
            'download_url': 'https://s3.example.com/zip',
        }
        with patch(
            'tools.webftp_tools._stream_s3_to_file',
            new=AsyncMock(side_effect=_S3DownloadError('connection reset')),
        ):
            result = await webftp_bulk_download(
                server_id=self.SERVER_ID,
                remote_paths=['/remote/a.txt'],
                local_file_path='/local/out.zip',
                workspace='ws',
            )

        assert result['status'] == _STATUS_ERROR
        assert 'Failed to download from S3' in result['message']
        assert result['download_url'] == 'https://s3.example.com/zip'

    @pytest.mark.asyncio
    async def test_bulk_download_save_error(self, mock_http_client, mock_token_manager):
        """A _LocalSaveError is surfaced separately from the S3 path."""

        mock_http_client.post.return_value = {
            'id': 'bulk-1',
            'download_url': 'https://s3.example.com/zip',
        }
        with patch(
            'tools.webftp_tools._stream_s3_to_file',
            new=AsyncMock(side_effect=_LocalSaveError('disk full')),
        ):
            result = await webftp_bulk_download(
                server_id=self.SERVER_ID,
                remote_paths=['/remote/a.txt'],
                local_file_path='/local/out.zip',
                workspace='ws',
            )

        assert result['status'] == _STATUS_ERROR
        assert 'Failed to save file locally' in result['message']

    @pytest.mark.asyncio
    async def test_save_stream_unlinks_partial_file_on_error(self):
        """Stream error mid-write triggers os.unlink on the partial file."""

        async def boom_chunks(chunk_size):
            del chunk_size
            yield b'partial'
            raise RuntimeError('mid-stream failure')

        response = MagicMock()
        response.aiter_bytes = boom_chunks

        with (
            patch('tools.webftp_tools.os.unlink') as mock_unlink,
            patch('tools.webftp_tools.open', MagicMock(), create=True),
        ):
            with pytest.raises(RuntimeError, match='mid-stream failure'):
                await _save_stream(response, '/tmp/partial.zip')

            mock_unlink.assert_called_once_with('/tmp/partial.zip')

    @pytest.mark.asyncio
    async def test_bulk_download_empty_paths(
        self, mock_http_client, mock_token_manager
    ):
        """Empty remote_paths returns an error without API calls."""

        result = await webftp_bulk_download(
            server_id=self.SERVER_ID,
            remote_paths=[],
            local_file_path='/local/out.zip',
            workspace='ws',
        )

        assert result['status'] == _STATUS_ERROR
        assert 'must not be empty' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_download_different_parents(
        self, mock_http_client, mock_token_manager
    ):
        """Paths in different parent directories are rejected."""

        result = await webftp_bulk_download(
            server_id=self.SERVER_ID,
            remote_paths=['/dir1/a.txt', '/dir2/b.txt'],
            local_file_path='/local/out.zip',
            workspace='ws',
        )

        assert result['status'] == _STATUS_ERROR
        assert 'same parent directory' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_download_async_processing(
        self, mock_http_client, mock_token_manager
    ):
        """API response without download_url returns processing-in-progress."""

        mock_http_client.post.return_value = {'id': 'bulk-1', 'status': 'queued'}

        result = await webftp_bulk_download(
            server_id=self.SERVER_ID,
            remote_paths=['/remote/a.txt'],
            local_file_path='/local/out.zip',
            workspace='ws',
        )

        assert result['status'] == 'success'
        assert 'processing in progress' in result['message']


class TestRemoteModeUnsupported:
    """Test that file-transfer tools return a clear error in remote mode."""

    SERVER_ID = '550e8400-e29b-41d4-a716-446655440001'

    @pytest.mark.asyncio
    async def test_upload_file_remote_mode(self, mock_http_client, mock_token_manager):
        """webftp_upload_file returns remote_mode_unsupported error in remote mode.

        The decorator's auth check is bypassed (auth disabled) so the function
        body's _is_remote_mode check is what we're exercising here.
        """
        with (
            patch('utils.decorators._is_auth_enabled', return_value=False),
            patch('tools.webftp_tools._is_remote_mode', return_value=True),
        ):
            result = await webftp_upload_file(
                server_id=self.SERVER_ID,
                local_file_path='/local/test.txt',
                remote_file_path='/remote/test.txt',
                workspace='ws',
                region='ap1',
            )
        assert result['status'] == 'error'
        assert 'remote mode' in result['message']
        assert result.get('code') == 'remote_mode_unsupported'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_file_remote_mode(self, mock_http_client, mock_token_manager):
        """webftp_download_file returns remote_mode_unsupported error in remote mode."""
        with (
            patch('utils.decorators._is_auth_enabled', return_value=False),
            patch('tools.webftp_tools._is_remote_mode', return_value=True),
        ):
            result = await webftp_download_file(
                server_id=self.SERVER_ID,
                remote_file_path='/remote/test.txt',
                local_file_path='/local/test.txt',
                workspace='ws',
                region='ap1',
            )
        assert result['status'] == 'error'
        assert 'remote mode' in result['message']
        assert result.get('code') == 'remote_mode_unsupported'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_upload_remote_mode(self, mock_http_client, mock_token_manager):
        """webftp_bulk_upload returns remote_mode_unsupported error in remote mode."""
        with (
            patch('utils.decorators._is_auth_enabled', return_value=False),
            patch('tools.webftp_tools._is_remote_mode', return_value=True),
        ):
            result = await webftp_bulk_upload(
                server_id=self.SERVER_ID,
                local_file_paths=['/local/a.txt', '/local/b.txt'],
                remote_directory='/remote/',
                workspace='ws',
                region='ap1',
            )
        assert result['status'] == 'error'
        assert 'remote mode' in result['message']
        assert result.get('code') == 'remote_mode_unsupported'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_download_remote_mode(self, mock_http_client, mock_token_manager):
        """webftp_bulk_download returns remote_mode_unsupported error in remote mode."""
        with (
            patch('utils.decorators._is_auth_enabled', return_value=False),
            patch('tools.webftp_tools._is_remote_mode', return_value=True),
        ):
            result = await webftp_bulk_download(
                server_id=self.SERVER_ID,
                remote_paths=['/remote/a.txt'],
                local_file_path='/local/out.zip',
                workspace='ws',
                region='ap1',
            )
        assert result['status'] == 'error'
        assert 'remote mode' in result['message']
        assert result.get('code') == 'remote_mode_unsupported'
        mock_http_client.post.assert_not_called()


class TestAiterFile:
    """Test the _aiter_file streaming-upload helper."""

    @pytest.mark.asyncio
    async def test_aiter_file_yields_chunks(self, tmp_path):
        """Yields exact file contents in chunks bounded by chunk_size."""

        path = tmp_path / 'src.bin'
        payload = b'x' * (1024 * 3 + 17)
        path.write_bytes(payload)

        chunks = [c async for c in _aiter_file(str(path), chunk_size=1024)]

        assert b''.join(chunks) == payload
        assert all(len(c) <= 1024 for c in chunks)

    @pytest.mark.asyncio
    async def test_aiter_file_closes_handle(self):
        """Closes the underlying file handle after iteration completes."""

        fake_handle = MagicMock()
        fake_handle.read.side_effect = [b'chunk1', b'']

        with patch('tools.webftp_tools.open', return_value=fake_handle, create=True):
            chunks = [c async for c in _aiter_file('/tmp/anything')]

        assert chunks == [b'chunk1']
        fake_handle.close.assert_called_once()


class TestEnsureParentDir:
    """Test the _ensure_parent_dir helper."""

    @pytest.mark.asyncio
    async def test_ensure_parent_dir_wraps_oserror_as_local_save_error(self):
        """OSError from mkdir surfaces as _LocalSaveError with the OS message."""

        with patch('tools.webftp_tools.Path') as mock_path_cls:
            mock_path_cls.return_value.mkdir.side_effect = PermissionError('denied')
            with pytest.raises(_LocalSaveError, match='denied'):
                await _ensure_parent_dir('/forbidden/dir/file.txt')

    @pytest.mark.asyncio
    async def test_ensure_parent_dir_noop_when_no_parent(self):
        """No mkdir attempt when the path has no parent component."""

        with patch('tools.webftp_tools.Path') as mock_path_cls:
            await _ensure_parent_dir('file.txt')
            mock_path_cls.assert_not_called()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
