"""WebFTP (Web FTP) management tools for Alpacon MCP server."""

import asyncio
import os
from http import HTTPStatus
from typing import Any

import anyio
import httpx

from server import mcp
from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error, validate_file_path
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, READ_ONLY

# API endpoints
_API_SESSIONS = '/api/webftp/sessions/'
_API_UPLOADS = '/api/webftp/uploads/'
_API_DOWNLOADS = '/api/webftp/downloads/'
_API_BULK_UPLOADS = '/api/webftp/uploads/bulk/'
_API_BULK_UPLOAD_TRIGGER = '/api/webftp/uploads/bulk-upload/'
_API_BULK_DOWNLOADS = '/api/webftp/downloads/bulk/'

# Transfer configuration
_CHUNK_SIZE = 65536
_UPLOAD_CONCURRENCY = 10
_BULK_DOWNLOAD_TIMEOUT = 60.0
_S3_SUCCESS_CODES = (HTTPStatus.OK, HTTPStatus.CREATED)
_CONTENT_TYPE_BINARY = 'application/octet-stream'


async def _stream_s3_to_file(
    url: str,
    local_path: str,
    *,
    timeout: float | None = None,
) -> int:
    """Stream a presigned S3 GET to a local file. Returns bytes written."""
    dir_name = os.path.dirname(local_path)
    if dir_name:
        await anyio.Path(dir_name).mkdir(parents=True, exist_ok=True)
    file_size = 0
    async with httpx.AsyncClient() as client:
        async with client.stream('GET', url, timeout=timeout) as response:
            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f'Failed to download from S3: {response.status_code}',
                    request=response.request,
                    response=response,
                )
            async with await anyio.open_file(local_path, 'wb') as f:
                async for chunk in response.aiter_bytes(chunk_size=_CHUNK_SIZE):
                    file_size += len(chunk)
                    await f.write(chunk)
    return file_size


@mcp_tool_handler(
    description='Create a new WebFTP file transfer session on a server. Returns session ID and connection details. When to use: advanced session management. For simple file transfers, use webftp_upload_file or webftp_download_file directly. Related: webftp_sessions_list (view sessions), webftp_upload_file, webftp_download_file.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'webftp session create file transfer'},
)
async def webftp_session_create(
    server_id: str,
    workspace: str,
    username: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new WebFTP session.

    Args:
        server_id: Server ID to create FTP session on
        workspace: Workspace name. Required parameter
        username: Optional username for the FTP session (uses authenticated user if not provided)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        FTP session creation response
    """
    token = kwargs.get('token')

    # Prepare FTP session data
    session_data = {'server': server_id}

    # Only include username if provided
    if username:
        session_data['username'] = username

    # Make async call to create FTP session
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_SESSIONS,
        token=token,
        data=session_data,
    )

    return success_response(
        data=result,
        server_id=server_id,
        username=username,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='List active and past WebFTP file transfer sessions in a workspace. Filterable by server ID. When to use: checking which file transfer sessions are currently open. Related: webftp_session_create (create new session).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'webftp sessions list active file transfer'},
)
async def webftp_sessions_list(
    workspace: str, server_id: str | None = None, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get list of WebFTP sessions.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter sessions
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        FTP sessions list response
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {}
    if server_id:
        params['server'] = server_id

    # Make async call to get FTP sessions
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_SESSIONS,
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Upload a local file to a remote server. Reads the file from a local absolute path, transfers it via S3 presigned URL, and places it at the specified remote path on the server. When to use: transferring a single file to a server. Related: webftp_bulk_upload (multiple files), webftp_download_file (download from server), webftp_uploads_list (check upload history). Note: Both local and remote paths must be absolute.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'file upload transfer scp sftp send server'},
)
async def webftp_upload_file(
    server_id: str,
    local_file_path: str,
    remote_file_path: str,
    workspace: str,
    username: str | None = None,
    region: str = '',
    allow_overwrite: bool = True,
    **kwargs,
) -> dict[str, Any]:
    """Upload a file using WebFTP uploads API with S3 presigned URLs.

    This creates an UploadedFile object which generates presigned S3 URLs for upload.
    The process:
    1. Read file from local path
    2. Create UploadedFile object with metadata
    3. Get presigned upload URL from response
    4. Upload file content to S3 using the presigned URL
    5. File is automatically processed on the server

    Args:
        server_id: Server ID to upload file to
        local_file_path: Local file path to read from (e.g., "/Users/user/file.txt")
        remote_file_path: Remote path where the file should be uploaded on the server (e.g., "/home/user/file.txt")
        workspace: Workspace name. Required parameter
        username: Optional username for the upload (uses authenticated user if not provided)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        allow_overwrite: Allow overwriting existing files (default: True)

    Returns:
        File upload response with presigned URLs
    """
    token = kwargs.get('token')

    # Validate file paths
    if not validate_file_path(local_file_path):
        return format_validation_error('local_file_path', local_file_path)
    if not validate_file_path(remote_file_path):
        return format_validation_error('remote_file_path', remote_file_path)

    # Step 1: Read local file
    try:
        file_content = await anyio.Path(local_file_path).read_bytes()
    except FileNotFoundError:
        return error_response(f'Local file not found: {local_file_path}')
    except Exception as e:
        return error_response(f'Failed to read local file: {str(e)}')

    # Step 2: Prepare upload data for UploadedFileCreateSerializer
    upload_data = {
        'server': server_id,
        'name': os.path.basename(remote_file_path),
        'path': remote_file_path,
        'allow_overwrite': allow_overwrite,
    }

    # Only include username if provided
    if username:
        upload_data['username'] = username

    # Step 3: Create UploadedFile object (this generates presigned URLs when USE_S3=True)
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_UPLOADS,
        token=token,
        data=upload_data,
    )

    # Step 4: Upload file content to S3 using presigned URL
    if 'upload_url' in result and result['upload_url']:
        async with httpx.AsyncClient() as client:
            upload_response = await client.put(
                result['upload_url'],
                content=file_content,
                headers={'Content-Type': _CONTENT_TYPE_BINARY},
            )

            if upload_response.status_code not in _S3_SUCCESS_CODES:
                return error_response(
                    f'Failed to upload to S3: {upload_response.status_code} - {upload_response.text}',
                    upload_url=result['upload_url'],
                )

        # Step 5: Trigger server to process the uploaded file
        upload_trigger = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f'{_API_UPLOADS}{result["id"]}/upload/',
            token=token,
        )

        return success_response(
            message='File uploaded successfully and processed by server',
            data=result,
            upload_trigger=upload_trigger,
            server_id=server_id,
            local_file_path=local_file_path,
            remote_file_path=remote_file_path,
            file_size=len(file_content),
            upload_url=result.get('upload_url'),
            download_url=result.get('download_url'),
            region=region,
            workspace=workspace,
        )
    else:
        # Fallback to direct upload (when USE_S3=False)
        return success_response(
            message='File uploaded successfully (direct upload)',
            data=result,
            server_id=server_id,
            local_file_path=local_file_path,
            remote_file_path=remote_file_path,
            region=region,
            workspace=workspace,
        )


@mcp_tool_handler(
    description='Download a file or folder from a remote server and save it to a local path. For folders, the content is automatically packaged as a ZIP archive. When to use: retrieving a single file or folder from a server. Related: webftp_bulk_download (multiple files as ZIP), webftp_upload_file (upload to server), webftp_downloads_list (check download history). Note: Set resource_type="folder" for directories.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'file download transfer get retrieve server'},
)
async def webftp_download_file(
    server_id: str,
    remote_file_path: str,
    local_file_path: str,
    workspace: str,
    resource_type: str = 'file',
    username: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Download a file or folder using WebFTP downloads API.

    This creates a DownloadedFile object which generates presigned S3 URLs for download,
    then downloads the file content and saves it to local path.
    For folders, it creates a zip file automatically.

    Args:
        server_id: Server ID to download from
        remote_file_path: Path of the file or folder to download from server
        local_file_path: Local path where the file should be saved
        workspace: Workspace name. Required parameter
        resource_type: Type of resource - "file" or "folder" (default: "file")
        username: Optional username for the download (uses authenticated user if not provided)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Download response with file saved locally
    """
    token = kwargs.get('token')

    # Validate file paths
    if not validate_file_path(remote_file_path):
        return format_validation_error('remote_file_path', remote_file_path)
    if not validate_file_path(local_file_path):
        return format_validation_error('local_file_path', local_file_path)

    # Step 1: Prepare download data for DownloadedFileCreateSerializer
    file_name = os.path.basename(remote_file_path)
    if resource_type == 'folder':
        file_name += '.zip'

    download_data = {
        'server': server_id,
        'path': remote_file_path,
        'name': file_name,
        'resource_type': resource_type,
    }

    # Only include username if provided
    if username:
        download_data['username'] = username

    # Step 2: Create DownloadedFile object (this generates presigned URLs when USE_S3=True)
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_DOWNLOADS,
        token=token,
        data=download_data,
    )

    # Step 3: Download file content from S3 using presigned URL
    if 'download_url' in result and result['download_url']:
        try:
            file_size = await _stream_s3_to_file(result['download_url'], local_file_path)
        except Exception as e:
            return error_response(str(e), download_url=result['download_url'])

        return success_response(
            message=f'File downloaded successfully from {resource_type}: {remote_file_path}',
            data=result,
            server_id=server_id,
            remote_file_path=remote_file_path,
            local_file_path=local_file_path,
            resource_type=resource_type,
            file_size=file_size,
            download_url=result.get('download_url'),
            region=region,
            workspace=workspace,
        )
    else:
        # Fallback for direct download (when USE_S3=False)
        return success_response(
            message=f'Download request created for {resource_type}: {remote_file_path}',
            data=result,
            server_id=server_id,
            remote_file_path=remote_file_path,
            resource_type=resource_type,
            region=region,
            workspace=workspace,
        )


@mcp_tool_handler(
    description='List file upload history showing filenames, sizes, timestamps, and transfer status. Filterable by server ID. When to use: verifying past uploads or checking upload progress. Related: webftp_upload_file (upload files), webftp_check_status (check specific transfer), list_webftp_logs (audit trail).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'webftp uploads history list files'},
)
async def webftp_uploads_list(
    workspace: str, server_id: str | None = None, region: str = '', **kwargs
) -> dict[str, Any]:
    """List uploaded files (upload history).

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter uploads
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Uploads list response
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {}
    if server_id:
        params['server'] = server_id

    # Make async call to get uploads list
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_UPLOADS,
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='List file download history showing filenames, sizes, timestamps, and transfer status. Filterable by server ID. When to use: verifying past downloads or checking download progress. Related: webftp_download_file (download files), webftp_check_status (check specific transfer), list_webftp_logs (audit trail).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'webftp downloads history list files'},
)
async def webftp_downloads_list(
    workspace: str, server_id: str | None = None, region: str = '', **kwargs
) -> dict[str, Any]:
    """List download requests (download history).

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter downloads
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Downloads list response
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {}
    if server_id:
        params['server'] = server_id

    # Make async call to get downloads list
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_DOWNLOADS,
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


# ===============================
# BULK WEBFTP TOOLS
# ===============================


@mcp_tool_handler(
    description='Upload multiple local files to a remote server in a single operation. All files are placed in the same destination directory. Uses S3 presigned URLs with concurrent uploads. When to use: uploading several files at once (more efficient than repeated webftp_upload_file calls). Related: webftp_upload_file (single file), webftp_bulk_download (download multiple). Note: All files go to the same remote directory.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'bulk upload multiple files batch transfer'},
)
async def webftp_bulk_upload(
    server_id: str,
    local_file_paths: list[str],
    remote_directory: str,
    workspace: str,
    username: str | None = None,
    region: str = '',
    allow_overwrite: bool = True,
    **kwargs,
) -> dict[str, Any]:
    """Upload multiple files to a server using bulk WebFTP API.

    Args:
        server_id: Server ID to upload files to
        local_file_paths: List of local file paths to upload (must not be empty)
        remote_directory: Remote directory to place all files (e.g., "/home/user/uploads/")
        workspace: Workspace name. Required parameter
        username: Optional username for the upload (uses authenticated user if not provided)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        allow_overwrite: Allow overwriting existing files (default: True)

    Returns:
        Bulk upload response with per-file status
    """
    token = kwargs.get('token')

    # Validate non-empty file list
    if not local_file_paths:
        return error_response('local_file_paths must not be empty')

    # Validate all file paths and ensure they are regular, readable files
    for path in local_file_paths:
        if not validate_file_path(path):
            return format_validation_error('local_file_paths', path)
        if not await anyio.Path(path).is_file():
            return error_response(f'Local file is not a regular file: {path}')
        if not await anyio.to_thread.run_sync(os.access, path, os.R_OK):
            return error_response(f'Local file is not readable: {path}')
    if not validate_file_path(remote_directory):
        return format_validation_error('remote_directory', remote_directory)

    # Create bulk upload records via API
    file_names = [os.path.basename(p) for p in local_file_paths]
    bulk_data: dict[str, Any] = {
        'server': server_id,
        'path': remote_directory,
        'names': file_names,
        'allow_overwrite': allow_overwrite,
    }
    if username:
        bulk_data['username'] = username

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_BULK_UPLOADS,
        token=token,
        data=bulk_data,
    )

    # Upload files to S3 concurrently using presigned URLs
    file_ids = []
    upload_items = (
        result if isinstance(result, list) else result.get('results', [result])
    )

    # Collect file IDs
    for item in upload_items:
        file_id = item.get('id')
        if file_id:
            file_ids.append(file_id)

    semaphore = asyncio.Semaphore(_UPLOAD_CONCURRENCY)

    async def _upload_one(
        client: httpx.AsyncClient,
        idx: int,
        item: dict,
    ) -> dict[str, Any]:
        upload_url = item.get('upload_url')
        file_id = item.get('id')
        name = file_names[idx] if idx < len(file_names) else 'unknown'

        if not upload_url or idx >= len(local_file_paths):
            return {'file': name, 'status': 'created', 'file_id': file_id}

        async with semaphore:
            try:
                file_content = await anyio.Path(local_file_paths[idx]).read_bytes()
                resp = await client.put(
                    upload_url,
                    content=file_content,
                    headers={'Content-Type': _CONTENT_TYPE_BINARY},
                )
                return {
                    'file': name,
                    'status': 'uploaded'
                    if resp.status_code in _S3_SUCCESS_CODES
                    else 'failed',
                    'file_id': file_id,
                    'size': len(file_content),
                }
            except Exception as e:
                return {'file': name, 'status': 'error', 'message': str(e)}

    async with httpx.AsyncClient() as client:
        upload_results = await asyncio.gather(
            *[_upload_one(client, i, item) for i, item in enumerate(upload_items)]
        )
    upload_results = list(upload_results)

    # Trigger bulk upload processing
    if file_ids:
        await http_client.post(
            region=region,
            workspace=workspace,
            endpoint=_API_BULK_UPLOAD_TRIGGER,
            token=token,
            data={'ids': file_ids},
        )

    successful = sum(
        1 for r in upload_results if r['status'] in ['uploaded', 'created']
    )

    return success_response(
        message=f'Bulk upload completed: {successful}/{len(local_file_paths)} files',
        data=upload_results,
        server_id=server_id,
        remote_directory=remote_directory,
        total_files=len(local_file_paths),
        successful_count=successful,
        failed_count=len(local_file_paths) - successful,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Download multiple files or folders from a remote server as a single ZIP archive. All paths must share the same parent directory. When to use: downloading several files at once. Related: webftp_download_file (single file), webftp_bulk_upload (upload multiple), webftp_check_status (poll if still processing). Note: If ZIP is not ready, poll with webftp_check_status then retry.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'bulk download multiple files zip archive batch'},
)
async def webftp_bulk_download(
    server_id: str,
    remote_paths: list[str],
    local_file_path: str,
    workspace: str,
    username: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Download multiple files/folders as a ZIP archive.

    Args:
        server_id: Server ID to download from
        remote_paths: List of remote file/folder paths to download (must share same parent directory)
        local_file_path: Local path to save the ZIP file (e.g., "/Users/user/downloads/files.zip")
        workspace: Workspace name. Required parameter
        username: Optional username for the download (uses authenticated user if not provided)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Bulk download response with file saved locally
    """
    token = kwargs.get('token')

    # Validate non-empty paths list
    if not remote_paths:
        return error_response('remote_paths must not be empty')

    # Validate paths
    for path in remote_paths:
        if not validate_file_path(path):
            return format_validation_error('remote_paths', path)
    if not validate_file_path(local_file_path):
        return format_validation_error('local_file_path', local_file_path)

    # Ensure all remote paths share the same parent directory
    if len(remote_paths) > 1:
        base_dir = os.path.dirname(remote_paths[0])
        for path in remote_paths[1:]:
            if os.path.dirname(path) != base_dir:
                return error_response(
                    'All remote_paths must share the same parent directory',
                    remote_paths=remote_paths,
                )

    # Create bulk download record
    download_data: dict[str, Any] = {
        'server': server_id,
        'path': remote_paths,
    }
    if username:
        download_data['username'] = username

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_BULK_DOWNLOADS,
        token=token,
        data=download_data,
    )

    # Download ZIP from S3 using streaming to avoid high memory usage
    download_url = result.get('download_url') if isinstance(result, dict) else None
    if download_url:
        try:
            file_size = await _stream_s3_to_file(
                download_url, local_file_path, timeout=_BULK_DOWNLOAD_TIMEOUT
            )
        except Exception as e:
            return error_response(str(e), download_url=download_url)

        return success_response(
            message=f'Bulk download completed: {len(remote_paths)} items saved as ZIP',
            data=result,
            server_id=server_id,
            remote_paths=remote_paths,
            local_file_path=local_file_path,
            file_size=file_size,
            download_url=download_url,
            region=region,
            workspace=workspace,
        )
    else:
        return success_response(
            message='Bulk download request created (file processing in progress)',
            data=result,
            server_id=server_id,
            remote_paths=remote_paths,
            region=region,
            workspace=workspace,
        )


@mcp_tool_handler(
    description='Check the transfer status of a WebFTP upload or download operation. Returns whether the transfer is still in progress, succeeded, or failed. When to use: polling for completion after webftp_bulk_download or other async file transfers. Related: webftp_bulk_download, webftp_upload_file.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'webftp transfer status check poll progress'},
)
async def webftp_check_status(
    file_id: str,
    transfer_type: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Check status of a WebFTP file transfer.

    Args:
        file_id: File ID from upload or download operation
        transfer_type: Type of transfer - "upload" or "download"
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Transfer status (success, in_progress, or failed)
    """
    token = kwargs.get('token')

    endpoint_map = {
        'upload': f'{_API_UPLOADS}{file_id}/status/',
        'download': f'{_API_DOWNLOADS}{file_id}/status/',
    }

    if transfer_type not in endpoint_map:
        return error_response(
            f'Invalid transfer_type: {transfer_type}. Must be "upload" or "download".'
        )

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=endpoint_map[transfer_type],
        token=token,
    )

    return success_response(
        data=result,
        file_id=file_id,
        transfer_type=transfer_type,
        region=region,
        workspace=workspace,
    )


# WebFTP sessions resource
@mcp.resource(
    uri='webftp://sessions/{region}/{workspace}',
    name='WebFTP Sessions List',
    description='Get list of WebFTP sessions',
    mime_type='application/json',
)
async def webftp_sessions_resource(region: str, workspace: str) -> dict[str, Any]:
    """Get WebFTP sessions as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        WebFTP sessions information
    """
    sessions_data = await webftp_sessions_list(region=region, workspace=workspace)
    return {'content': sessions_data}


# WebFTP downloads resource
@mcp.resource(
    uri='webftp://downloads/{session_id}/{region}/{workspace}',
    name='WebFTP Downloads List',
    description='Get list of downloadable files from WebFTP session',
    mime_type='application/json',
)
async def webftp_downloads_resource(
    session_id: str, region: str, workspace: str
) -> dict[str, Any]:
    """Get WebFTP downloads as a resource.

    Args:
        session_id: WebFTP session ID
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        WebFTP downloads information
    """
    downloads_data = await webftp_downloads_list(
        session_id=session_id, region=region, workspace=workspace
    )
    return {'content': downloads_data}
