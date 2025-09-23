"""Authentication tools for Alpacon MCP server."""

from typing import Dict, Optional, List
from server import mcp
from utils.auth import login, logout, get_token
from utils.token_manager import TokenManager

# Initialize token manager
token_manager = TokenManager()


# Login function registered as MCP Tool
@mcp.tool(
    description="""
    Login to Alpacon server with given region and workspace.
    Example: 'Login to alpacax workspace in ap1 region'
    - region: 'ap1', 'us1', 'eu1' etc (default: ap1)
    - workspace: workspace name (e.g., alpacax)
    """
)
def alpacon_login(region: str = "ap1", workspace: str = "alpamon"):
    # Get token for the given region and workspace and perform login
    token = get_token(region, workspace)
    print(f"Token: {token}")
    login(region, workspace, token)
    print(f"Logged in to {workspace} in {region} region")
    return "test"


# Logout function registered as MCP Tool
@mcp.tool(
    description="""
    Logout from specified workspace.
    Example: 'Logout from alpacax workspace'
    - workspace: workspace name (e.g., alpacax)
    """
)
def alpacon_logout():
    # Perform logout from the workspace
    logout()


# New token setting tool
@mcp.tool(
    description="Set API token for specific region and workspace"
)
def auth_set_token(
    region: str,
    workspace: str,
    token: str
) -> Dict[str, str]:
    """Set API token for Alpacon authentication.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name
        token: API token

    Returns:
        Success message with token information
    """
    return token_manager.set_token(region, workspace, token)


# 토큰 제거 도구
@mcp.tool(
    description="특정 region과 워크스페이스의 API 토큰을 제거합니다"
)
def auth_remove_token(
    region: str,
    workspace: str
) -> Dict[str, str]:
    """Remove API token.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        Success or error message
    """
    return token_manager.remove_token(region, workspace)


# 인증 상태 자원
@mcp.resource(
    uri="auth://status/{region}/{workspace}",
    name="인증 상태",
    description="현재 인증 상태와 사용 가능한 토큰 정보를 확인합니다",
    mime_type="application/json"
)
def auth_status(region: str, workspace: str) -> Dict[str, any]:
    """Get authentication status.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        Authentication status information
    """
    return {
        "content": token_manager.get_auth_status()
    }


# Config 정보 자원
@mcp.resource(
    uri="auth://config",
    name="Config 정보",
    description="현재 설정 디렉토리 정보를 확인합니다 (개발/프로덕션 모드)",
    mime_type="application/json"
)
def auth_config_info() -> Dict[str, any]:
    """Get configuration directory information.

    Returns:
        Configuration directory details
    """
    return {
        "content": token_manager.get_config_info()
    }


# 토큰 조회 자원
@mcp.resource(
    uri="auth://tokens/{region}/{workspace}",
    name="저장된 토큰 조회",
    description="특정 region과 워크스페이스의 저장된 토큰을 조회합니다",
    mime_type="application/json"
)
def auth_get_token(region: str, workspace: str) -> Optional[Dict[str, str]]:
    """Get stored token for specific region and workspace.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        Token information if found
    """
    token_info = token_manager.get_token(region, workspace)

    if token_info:
        return {
            "content": token_info
        }

    return {
        "content": {
            "error": f"No token found for {workspace}.{region}"
        }
    }


# 리소스 목록 (FastMCP에서 resource_list 지원하지 않음)
# @mcp.resource_list()
def list_auth_resources() -> List[Dict[str, str]]:
    """List available authentication resources.

    Returns:
        List of available auth resources
    """
    resources = [
        {
            "uri": "auth://status",
            "name": "인증 상태",
            "description": "현재 인증 상태 확인",
            "mime_type": "application/json"
        },
        {
            "uri": "auth://config",
            "name": "Config 정보",
            "description": "설정 디렉토리 정보 확인 (개발/프로덕션 모드)",
            "mime_type": "application/json"
        }
    ]

    # Add token resources for each stored token
    auth_status_data = token_manager.get_auth_status()
    for env_info in auth_status_data["environments"]:
        env = env_info["env"]
        for workspace in env_info["workspaces"]:
            resources.append({
                "uri": f"auth://tokens/{env}/{workspace}",
                "name": f"{workspace}.{env} 토큰",
                "description": f"{env} 환경 {workspace} 워크스페이스 토큰",
                "mime_type": "application/json"
            })

    return resources
