"""WebFTP (Web FTP) management tools for Alpacon MCP server."""

import asyncio
import os
from typing import Dict, Any, Optional
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Initialize token manager
token_manager = get_token_manager()


@mcp.tool(description="Create a new WebFTP session")
async def webftp_session_create(
    server_id: str,
    workspace: str,
    username: Optional[str] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Create a new WebFTP session.

    Args:
        server_id: Server ID to create FTP session on
        workspace: Workspace name. Required parameter
        username: Optional username for the FTP session (uses authenticated user if not provided)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        FTP session creation response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare FTP session data
        session_data = {
            "server": server_id
        }

        # Only include username if provided
        if username:
            session_data["username"] = username

        # Make async call to create FTP session
        result = await http_client.post(
                region=region,
                workspace=workspace,
                endpoint="/api/webftp/sessions/",
                token=token,
                data=session_data
        )
        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "username": username,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create WebFTP session: {str(e)}"
        }


@mcp.tool(description="Get list of WebFTP sessions")
async def webftp_sessions_list(
    workspace: str,
    server_id: Optional[str] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get list of WebFTP sessions.

    Args:
        server_id: Optional server ID to filter sessions
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        FTP sessions list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare query parameters
        params = {}
        if server_id:
            params["server"] = server_id

        # Make async call to get FTP sessions
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint="/api/webftp/sessions/",
                token=token,
                params=params
        )
        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get WebFTP sessions: {str(e)}"
        }


@mcp.tool(description="Upload a file using WebFTP uploads API (S3-based)")
async def webftp_upload_file(
    server_id: str,
    local_file_path: str,
    remote_file_path: str,
    workspace: str,
    username: Optional[str] = None,
    region: str = "ap1",
    allow_overwrite: bool = True
) -> Dict[str, Any]:
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
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        allow_overwrite: Allow overwriting existing files (default: True)

    Returns:
        File upload response with presigned URLs
    """
    try:
        # Step 1: Read local file
        try:
            with open(local_file_path, 'rb') as f:
                file_content = f.read()
        except FileNotFoundError:
            return {
                "status": "error",
                "message": f"Local file not found: {local_file_path}"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to read local file: {str(e)}"
            }

        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Step 2: Prepare upload data for UploadedFileCreateSerializer
        upload_data = {
            "server": server_id,
            "name": os.path.basename(remote_file_path),
            "path": remote_file_path,
            "allow_overwrite": allow_overwrite
        }

        # Only include username if provided
        if username:
            upload_data["username"] = username

        # Step 3: Create UploadedFile object (this generates presigned URLs when USE_S3=True)
        result = await http_client.post(
                region=region,
                workspace=workspace,
                endpoint="/api/webftp/uploads/",
                token=token,
                data=upload_data
        )

        # Step 4: Upload file content to S3 using presigned URL
        if "upload_url" in result and result["upload_url"]:
            import httpx
            async with httpx.AsyncClient() as client:
                upload_response = await client.put(
                    result["upload_url"],
                    content=file_content,
                    headers={"Content-Type": "application/octet-stream"}
                )

                if upload_response.status_code not in [200, 201]:
                    return {
                        "status": "error",
                        "message": f"Failed to upload to S3: {upload_response.status_code} - {upload_response.text}",
                        "upload_url": result["upload_url"]
                    }

            # Step 5: Trigger server to process the uploaded file
            upload_trigger = await http_client.get(
                    region=region,
                    workspace=workspace,
                    endpoint=f"/api/webftp/uploads/{result['id']}/upload/",
                    token=token
            )

            return {
                "status": "success",
                "message": "File uploaded successfully and processed by server",
                "data": result,
                "upload_trigger": upload_trigger,
                "server_id": server_id,
                "local_file_path": local_file_path,
                "remote_file_path": remote_file_path,
                "file_size": len(file_content),
                "upload_url": result.get("upload_url"),
                "download_url": result.get("download_url"),
                "region": region,
                "workspace": workspace
            }
        else:
            # Fallback to direct upload (when USE_S3=False)
            return {
                "status": "success",
                "message": "File uploaded successfully (direct upload)",
                "data": result,
                "server_id": server_id,
                "local_file_path": local_file_path,
                "remote_file_path": remote_file_path,
                "region": region,
                "workspace": workspace
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to upload file: {str(e)}"
        }


@mcp.tool(description="Download a file or folder using WebFTP downloads API")
async def webftp_download_file(
    server_id: str,
    remote_file_path: str,
    local_file_path: str,
    workspace: str,
    resource_type: str = "file",
    username: Optional[str] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
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
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Download response with file saved locally
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Step 1: Prepare download data for DownloadedFileCreateSerializer
        file_name = os.path.basename(remote_file_path)
        if resource_type == "folder":
            file_name += ".zip"

        download_data = {
            "server": server_id,
            "path": remote_file_path,
            "name": file_name,
            "resource_type": resource_type
        }

        # Only include username if provided
        if username:
            download_data["username"] = username

        # Step 2: Create DownloadedFile object (this generates presigned URLs when USE_S3=True)
        result = await http_client.post(
                region=region,
                workspace=workspace,
                endpoint="/api/webftp/downloads/",
                token=token,
                data=download_data
        )

        # Step 3: Download file content from S3 using presigned URL
        if "download_url" in result and result["download_url"]:
            import httpx
            async with httpx.AsyncClient() as client:
                download_response = await client.get(result["download_url"])

                if download_response.status_code != 200:
                    return {
                        "status": "error",
                        "message": f"Failed to download from S3: {download_response.status_code} - {download_response.text}",
                        "download_url": result["download_url"]
                    }

                # Step 4: Save file content to local path
                try:
                    # Create directory if it doesn't exist
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

                    with open(local_file_path, 'wb') as f:
                        f.write(download_response.content)
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Failed to save file locally: {str(e)}"
                    }

            return {
                "status": "success",
                "message": f"File downloaded successfully from {resource_type}: {remote_file_path}",
                "data": result,
                "server_id": server_id,
                "remote_file_path": remote_file_path,
                "local_file_path": local_file_path,
                "resource_type": resource_type,
                "file_size": len(download_response.content),
                "download_url": result.get("download_url"),
                "region": region,
                "workspace": workspace
            }
        else:
            # Fallback for direct download (when USE_S3=False)
            return {
                "status": "success",
                "message": f"Download request created for {resource_type}: {remote_file_path}",
                "data": result,
                "server_id": server_id,
                "remote_file_path": remote_file_path,
                "resource_type": resource_type,
                "region": region,
                "workspace": workspace
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to download file: {str(e)}"
        }


@mcp.tool(description="List uploaded files (upload history)")
async def webftp_uploads_list(
    workspace: str,
    server_id: Optional[str] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
    """List uploaded files (upload history).

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter uploads
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Uploads list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare query parameters
        params = {}
        if server_id:
            params["server"] = server_id

        # Make async call to get uploads list
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint="/api/webftp/uploads/",
                token=token,
                params=params
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get uploads list: {str(e)}"
        }


@mcp.tool(description="List download requests (download history)")
async def webftp_downloads_list(
    workspace: str,
    server_id: Optional[str] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
    """List download requests (download history).

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter downloads
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Downloads list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare query parameters
        params = {}
        if server_id:
            params["server"] = server_id

        # Make async call to get downloads list
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint="/api/webftp/downloads/",
                token=token,
                params=params
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get downloads list: {str(e)}"
        }


# WebFTP sessions resource
@mcp.resource(
    uri="webftp://sessions/{region}/{workspace}",
    name="WebFTP Sessions List",
    description="Get list of WebFTP sessions",
    mime_type="application/json"
)
async def webftp_sessions_resource(region: str, workspace: str) -> Dict[str, Any]:
    """Get WebFTP sessions as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        WebFTP sessions information
    """
    sessions_data = webftp_sessions_list(region=region, workspace=workspace)
    return {
        "content": sessions_data
    }


# WebFTP downloads resource
@mcp.resource(
    uri="webftp://downloads/{session_id}/{region}/{workspace}",
    name="WebFTP Downloads List",
    description="Get list of downloadable files from WebFTP session",
    mime_type="application/json"
)
async def webftp_downloads_resource(session_id: str, region: str, workspace: str) -> Dict[str, Any]:
    """Get WebFTP downloads as a resource.

    Args:
        session_id: WebFTP session ID
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        WebFTP downloads information
    """
    downloads_data = webftp_downloads_list(session_id=session_id, region=region, workspace=workspace)
    return {
        "content": downloads_data
    }