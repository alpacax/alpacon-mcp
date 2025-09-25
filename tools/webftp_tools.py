"""WebFTP (Web FTP) management tools for Alpacon MCP server."""

import asyncio
from typing import Dict, Any, Optional
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Initialize token manager
token_manager = get_token_manager()


@mcp.tool(description="Create a new WebFTP session")
async def webftp_session_create(
    server_id: str,
    username: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Create a new WebFTP session.

    Args:
        server_id: Server ID to create FTP session on
        username: Username for the FTP session
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

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
            "server": server_id,
            "username": username
        }

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


@mcp.tool(description="Upload a file through WebFTP session")
async def webftp_upload_file(
    session_id: str,
    file_path: str,
    file_data: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Upload a file through WebFTP session.

    Args:
        session_id: WebFTP session ID
        file_path: Path where to upload the file
        file_data: File content (base64 encoded or text)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        File upload response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare upload data
        upload_data = {
            "file_path": file_path,
            "file_data": file_data
        }

        # Make async call to upload file
        result = await http_client.post(
                region=region,
                workspace=workspace,
                endpoint=f"/api/webftp/sessions/{session_id}/upload/",
                token=token,
                data=upload_data
        )
        return {
            "status": "success",
            "data": result,
            "session_id": session_id,
            "file_path": file_path,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to upload file: {str(e)}"
        }


@mcp.tool(description="Get list of downloadable files from WebFTP session")
async def webftp_downloads_list(
    session_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get list of downloadable files from WebFTP session.

    Args:
        session_id: WebFTP session ID
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

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

        # Make async call to get downloads list
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint=f"/api/webftp/sessions/{session_id}/downloads/",
                token=token
        )

        return {
            "status": "success",
            "data": result,
            "session_id": session_id,
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