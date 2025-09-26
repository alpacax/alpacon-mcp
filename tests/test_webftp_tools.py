"""
Unit tests for webftp_tools module.

Tests WebFTP functionality including session management, file uploads,
file downloads, and file transfer history.
"""
import pytest
from unittest.mock import AsyncMock, patch, mock_open, MagicMock
import os
import tempfile


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
    with patch('tools.webftp_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
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
        from tools.webftp_tools import webftp_session_create

        # Mock successful response
        mock_http_client.post.return_value = {
            "id": "session-123",
            "server": "server-001",
            "username": "testuser",
            "created_at": "2024-01-01T00:00:00Z"
        }

        result = await webftp_session_create(
            server_id="server-001",
            workspace="testworkspace",
            username="testuser",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["username"] == "testuser"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify HTTP client was called correctly
        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/webftp/sessions/",
            token="test-token",
            data={
                "server": "server-001",
                "username": "testuser"
            }
        )

    @pytest.mark.asyncio
    async def test_session_create_without_username(self, mock_http_client, mock_token_manager):
        """Test WebFTP session creation without username."""
        from tools.webftp_tools import webftp_session_create

        mock_http_client.post.return_value = {"id": "session-123"}

        result = await webftp_session_create(
            server_id="server-001",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["username"] is None

        # Verify username was not included in data
        call_args = mock_http_client.post.call_args
        assert "username" not in call_args[1]["data"]

    @pytest.mark.asyncio
    async def test_session_create_no_token(self, mock_http_client, mock_token_manager):
        """Test session creation when no token is available."""
        from tools.webftp_tools import webftp_session_create

        mock_token_manager.get_token.return_value = None

        result = await webftp_session_create(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_create_http_error(self, mock_http_client, mock_token_manager):
        """Test session creation with HTTP error."""
        from tools.webftp_tools import webftp_session_create

        mock_http_client.post.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await webftp_session_create(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to create WebFTP session" in result["message"]


class TestWebFtpSessionsList:
    """Test webftp_sessions_list function."""

    @pytest.mark.asyncio
    async def test_sessions_list_success(self, mock_http_client, mock_token_manager):
        """Test successful WebFTP sessions listing."""
        from tools.webftp_tools import webftp_sessions_list

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 2,
            "results": [
                {
                    "id": "session-123",
                    "server": "server-001",
                    "username": "testuser1",
                    "created_at": "2024-01-01T00:00:00Z"
                },
                {
                    "id": "session-124",
                    "server": "server-002",
                    "username": "testuser2",
                    "created_at": "2024-01-01T00:01:00Z"
                }
            ]
        }

        result = await webftp_sessions_list(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["server_id"] is None
        assert result["data"]["count"] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/webftp/sessions/",
            token="test-token",
            params={}
        )

    @pytest.mark.asyncio
    async def test_sessions_list_with_server_filter(self, mock_http_client, mock_token_manager):
        """Test sessions listing with server filter."""
        from tools.webftp_tools import webftp_sessions_list

        mock_http_client.get.return_value = {"count": 1, "results": []}

        result = await webftp_sessions_list(
            workspace="testworkspace",
            server_id="server-001",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"

        # Verify server filter was applied
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"]["server"] == "server-001"

    @pytest.mark.asyncio
    async def test_sessions_list_no_token(self, mock_http_client, mock_token_manager):
        """Test sessions listing when no token is available."""
        from tools.webftp_tools import webftp_sessions_list

        mock_token_manager.get_token.return_value = None

        result = await webftp_sessions_list(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()


class TestWebFtpUploadFile:
    """Test webftp_upload_file function."""

    @pytest.mark.asyncio
    async def test_upload_file_success_with_s3(self, mock_http_client, mock_token_manager):
        """Test successful file upload with S3."""
        from tools.webftp_tools import webftp_upload_file

        # Mock file content
        file_content = b"test file content"

        with patch('builtins.open', mock_open(read_data=file_content)):
            # Mock API response with S3 URL
            mock_http_client.post.return_value = {
                "id": "upload-123",
                "name": "test.txt",
                "upload_url": "https://s3.amazonaws.com/bucket/presigned-url",
                "download_url": "https://s3.amazonaws.com/bucket/download-url"
            }

            # Mock httpx directly within the context
            with patch('httpx.AsyncClient') as mock_httpx_class:
                mock_client = AsyncMock()
                mock_httpx_class.return_value.__aenter__.return_value = mock_client

                # Mock S3 upload response - use MagicMock not AsyncMock for response
                mock_s3_response = MagicMock()
                mock_s3_response.status_code = 200
                mock_s3_response.text = "Success"
                mock_client.put = AsyncMock(return_value=mock_s3_response)

                # Mock upload trigger response
                mock_http_client.get.return_value = {"status": "processed"}

                result = await webftp_upload_file(
                    server_id="server-001",
                    local_file_path="/local/test.txt",
                    remote_file_path="/remote/test.txt",
                    workspace="testworkspace",
                    username="testuser",
                    region="ap1"
                )

                assert result["status"] == "success"
                assert "uploaded successfully and processed" in result["message"]
                assert result["server_id"] == "server-001"
                assert result["local_file_path"] == "/local/test.txt"
                assert result["remote_file_path"] == "/remote/test.txt"
                assert result["file_size"] == len(file_content)
                assert "upload_url" in result
                assert "download_url" in result

                # Verify API calls
                mock_http_client.post.assert_called_once()
                mock_client.put.assert_called_once_with(
                    "https://s3.amazonaws.com/bucket/presigned-url",
                    content=file_content,
                    headers={"Content-Type": "application/octet-stream"}
                )
                mock_http_client.get.assert_called_once_with(
                    region="ap1",
                    workspace="testworkspace",
                    endpoint="/api/webftp/uploads/upload-123/upload/",
                    token="test-token"
                )

    @pytest.mark.asyncio
    async def test_upload_file_success_direct(self, mock_http_client, mock_token_manager):
        """Test successful file upload without S3."""
        from tools.webftp_tools import webftp_upload_file

        file_content = b"test file content"

        with patch('builtins.open', mock_open(read_data=file_content)):
            # Mock API response without S3 URL
            mock_http_client.post.return_value = {
                "id": "upload-123",
                "name": "test.txt"
            }

            result = await webftp_upload_file(
                server_id="server-001",
                local_file_path="/local/test.txt",
                remote_file_path="/remote/test.txt",
                workspace="testworkspace"
            )

            assert result["status"] == "success"
            assert "direct upload" in result["message"]
            assert result["server_id"] == "server-001"

    @pytest.mark.asyncio
    async def test_upload_file_not_found(self, mock_http_client, mock_token_manager):
        """Test file upload when local file doesn't exist."""
        from tools.webftp_tools import webftp_upload_file

        with patch('builtins.open', side_effect=FileNotFoundError("File not found")):
            result = await webftp_upload_file(
                server_id="server-001",
                local_file_path="/nonexistent/test.txt",
                remote_file_path="/remote/test.txt",
                workspace="testworkspace"
            )

            assert result["status"] == "error"
            assert "Local file not found" in result["message"]
            mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_file_s3_error(self, mock_http_client, mock_token_manager, mock_httpx):
        """Test file upload with S3 error."""
        from tools.webftp_tools import webftp_upload_file

        file_content = b"test file content"

        with patch('builtins.open', mock_open(read_data=file_content)):
            mock_http_client.post.return_value = {
                "id": "upload-123",
                "upload_url": "https://s3.amazonaws.com/bucket/presigned-url"
            }

            # Mock S3 error response
            mock_s3_response = MagicMock()
            mock_s3_response.status_code = 500
            mock_s3_response.text = "Internal Server Error"
            mock_httpx.put.return_value = mock_s3_response

            result = await webftp_upload_file(
                server_id="server-001",
                local_file_path="/local/test.txt",
                remote_file_path="/remote/test.txt",
                workspace="testworkspace"
            )

            assert result["status"] == "error"
            assert "Failed to upload to S3" in result["message"]

    @pytest.mark.asyncio
    async def test_upload_file_no_token(self, mock_http_client, mock_token_manager):
        """Test file upload when no token is available."""
        from tools.webftp_tools import webftp_upload_file

        mock_token_manager.get_token.return_value = None
        file_content = b"test file content"

        # Need to mock file reading since it happens before token check
        with patch('builtins.open', mock_open(read_data=file_content)):
            result = await webftp_upload_file(
                server_id="server-001",
                local_file_path="/local/test.txt",
                remote_file_path="/remote/test.txt",
                workspace="testworkspace"
            )

            assert result["status"] == "error"
            assert "No token found" in result["message"]


class TestWebFtpDownloadFile:
    """Test webftp_download_file function."""

    @pytest.mark.asyncio
    async def test_download_file_success(self, mock_http_client, mock_token_manager):
        """Test successful file download."""
        from tools.webftp_tools import webftp_download_file

        # Mock API response with S3 URL
        mock_http_client.post.return_value = {
            "id": "download-123",
            "name": "test.txt",
            "download_url": "https://s3.amazonaws.com/bucket/download-url"
        }

        with patch('builtins.open', mock_open()) as mock_file:
            with patch('os.makedirs'):
                with patch('httpx.AsyncClient') as mock_httpx_class:
                    mock_client = AsyncMock()
                    mock_httpx_class.return_value.__aenter__.return_value = mock_client

                    # Mock S3 download response
                    file_content = b"downloaded file content"
                    mock_s3_response = MagicMock()
                    mock_s3_response.status_code = 200
                    mock_s3_response.content = file_content
                    mock_client.get = AsyncMock(return_value=mock_s3_response)

                    result = await webftp_download_file(
                        server_id="server-001",
                        remote_file_path="/remote/test.txt",
                        local_file_path="/local/test.txt",
                        workspace="testworkspace",
                        username="testuser",
                        region="ap1"
                    )

                    assert result["status"] == "success"
                    assert "downloaded successfully" in result["message"]
                    assert result["server_id"] == "server-001"
                    assert result["remote_file_path"] == "/remote/test.txt"
                    assert result["local_file_path"] == "/local/test.txt"
                    assert result["file_size"] == len(file_content)
                    assert result["resource_type"] == "file"

                    # Verify file was written
                    mock_file.assert_called_once_with("/local/test.txt", "wb")
                    mock_file().write.assert_called_once_with(file_content)

    @pytest.mark.asyncio
    async def test_download_folder_success(self, mock_http_client, mock_token_manager):
        """Test successful folder download as zip."""
        from tools.webftp_tools import webftp_download_file

        mock_http_client.post.return_value = {
            "id": "download-123",
            "name": "folder.zip",
            "download_url": "https://s3.amazonaws.com/bucket/download-url"
        }

        with patch('builtins.open', mock_open()) as mock_file:
            with patch('os.makedirs'):
                with patch('httpx.AsyncClient') as mock_httpx_class:
                    mock_client = AsyncMock()
                    mock_httpx_class.return_value.__aenter__.return_value = mock_client

                    zip_content = b"zip file content"
                    mock_s3_response = MagicMock()
                    mock_s3_response.status_code = 200
                    mock_s3_response.content = zip_content
                    mock_client.get = AsyncMock(return_value=mock_s3_response)

                    result = await webftp_download_file(
                        server_id="server-001",
                        remote_file_path="/remote/folder",
                        local_file_path="/local/folder.zip",
                        workspace="testworkspace",
                        resource_type="folder"
                    )

                    assert result["status"] == "success"
                    assert result["resource_type"] == "folder"

                    # Verify correct data was sent to API
                    call_args = mock_http_client.post.call_args
                    assert call_args[1]["data"]["resource_type"] == "folder"
                    assert call_args[1]["data"]["name"] == "folder.zip"

    @pytest.mark.asyncio
    async def test_download_file_direct_mode(self, mock_http_client, mock_token_manager):
        """Test file download without S3 (direct mode)."""
        from tools.webftp_tools import webftp_download_file

        # Mock API response without S3 URL
        mock_http_client.post.return_value = {
            "id": "download-123",
            "name": "test.txt"
        }

        result = await webftp_download_file(
            server_id="server-001",
            remote_file_path="/remote/test.txt",
            local_file_path="/local/test.txt",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert "Download request created" in result["message"]
        assert result["server_id"] == "server-001"

    @pytest.mark.asyncio
    async def test_download_file_s3_error(self, mock_http_client, mock_token_manager, mock_httpx):
        """Test file download with S3 error."""
        from tools.webftp_tools import webftp_download_file

        mock_http_client.post.return_value = {
            "id": "download-123",
            "download_url": "https://s3.amazonaws.com/bucket/download-url"
        }

        # Mock S3 error response
        mock_s3_response = MagicMock()
        mock_s3_response.status_code = 404
        mock_s3_response.text = "Not Found"
        mock_httpx.get.return_value = mock_s3_response

        result = await webftp_download_file(
            server_id="server-001",
            remote_file_path="/remote/test.txt",
            local_file_path="/local/test.txt",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to download from S3" in result["message"]

    @pytest.mark.asyncio
    async def test_download_file_save_error(self, mock_http_client, mock_token_manager):
        """Test file download with local save error."""
        from tools.webftp_tools import webftp_download_file

        mock_http_client.post.return_value = {
            "id": "download-123",
            "download_url": "https://s3.amazonaws.com/bucket/download-url"
        }

        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            with patch('os.makedirs'):
                with patch('httpx.AsyncClient') as mock_httpx_class:
                    mock_client = AsyncMock()
                    mock_httpx_class.return_value.__aenter__.return_value = mock_client

                    mock_s3_response = MagicMock()
                    mock_s3_response.status_code = 200
                    mock_s3_response.content = b"content"
                    mock_client.get = AsyncMock(return_value=mock_s3_response)

                    result = await webftp_download_file(
                        server_id="server-001",
                        remote_file_path="/remote/test.txt",
                        local_file_path="/local/test.txt",
                        workspace="testworkspace"
                    )

                    assert result["status"] == "error"
                    assert "Failed to save file locally" in result["message"]

    @pytest.mark.asyncio
    async def test_download_file_no_token(self, mock_http_client, mock_token_manager):
        """Test file download when no token is available."""
        from tools.webftp_tools import webftp_download_file

        mock_token_manager.get_token.return_value = None

        result = await webftp_download_file(
            server_id="server-001",
            remote_file_path="/remote/test.txt",
            local_file_path="/local/test.txt",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestWebFtpUploadsList:
    """Test webftp_uploads_list function."""

    @pytest.mark.asyncio
    async def test_uploads_list_success(self, mock_http_client, mock_token_manager):
        """Test successful uploads list retrieval."""
        from tools.webftp_tools import webftp_uploads_list

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 2,
            "results": [
                {
                    "id": "upload-123",
                    "name": "file1.txt",
                    "server": "server-001",
                    "created_at": "2024-01-01T00:00:00Z"
                },
                {
                    "id": "upload-124",
                    "name": "file2.txt",
                    "server": "server-002",
                    "created_at": "2024-01-01T00:01:00Z"
                }
            ]
        }

        result = await webftp_uploads_list(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["count"] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/webftp/uploads/",
            token="test-token",
            params={}
        )

    @pytest.mark.asyncio
    async def test_uploads_list_with_server_filter(self, mock_http_client, mock_token_manager):
        """Test uploads list with server filter."""
        from tools.webftp_tools import webftp_uploads_list

        mock_http_client.get.return_value = {"count": 1, "results": []}

        result = await webftp_uploads_list(
            workspace="testworkspace",
            server_id="server-001"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"

        # Verify server filter was applied
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"]["server"] == "server-001"

    @pytest.mark.asyncio
    async def test_uploads_list_no_token(self, mock_http_client, mock_token_manager):
        """Test uploads list when no token is available."""
        from tools.webftp_tools import webftp_uploads_list

        mock_token_manager.get_token.return_value = None

        result = await webftp_uploads_list(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_uploads_list_http_error(self, mock_http_client, mock_token_manager):
        """Test uploads list with HTTP error."""
        from tools.webftp_tools import webftp_uploads_list

        mock_http_client.get.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await webftp_uploads_list(workspace="testworkspace")

        assert result["status"] == "error"
        assert "Failed to get uploads list" in result["message"]


class TestWebFtpDownloadsList:
    """Test webftp_downloads_list function."""

    @pytest.mark.asyncio
    async def test_downloads_list_success(self, mock_http_client, mock_token_manager):
        """Test successful downloads list retrieval."""
        from tools.webftp_tools import webftp_downloads_list

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 2,
            "results": [
                {
                    "id": "download-123",
                    "name": "file1.txt",
                    "server": "server-001",
                    "created_at": "2024-01-01T00:00:00Z"
                },
                {
                    "id": "download-124",
                    "name": "file2.txt",
                    "server": "server-002",
                    "created_at": "2024-01-01T00:01:00Z"
                }
            ]
        }

        result = await webftp_downloads_list(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["count"] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/webftp/downloads/",
            token="test-token",
            params={}
        )

    @pytest.mark.asyncio
    async def test_downloads_list_with_server_filter(self, mock_http_client, mock_token_manager):
        """Test downloads list with server filter."""
        from tools.webftp_tools import webftp_downloads_list

        mock_http_client.get.return_value = {"count": 1, "results": []}

        result = await webftp_downloads_list(
            workspace="testworkspace",
            server_id="server-001"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"

        # Verify server filter was applied
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"]["server"] == "server-001"

    @pytest.mark.asyncio
    async def test_downloads_list_no_token(self, mock_http_client, mock_token_manager):
        """Test downloads list when no token is available."""
        from tools.webftp_tools import webftp_downloads_list

        mock_token_manager.get_token.return_value = None

        result = await webftp_downloads_list(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_downloads_list_http_error(self, mock_http_client, mock_token_manager):
        """Test downloads list with HTTP error."""
        from tools.webftp_tools import webftp_downloads_list

        mock_http_client.get.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await webftp_downloads_list(workspace="testworkspace")

        assert result["status"] == "error"
        assert "Failed to get downloads list" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])