"""
Interactive setup wizard for Alpacon MCP Server configuration.

This module provides a user-friendly CLI interface for configuring the MCP server,
eliminating the need for manual JSON editing.
"""

import json
import os
import sys
from getpass import getpass
from pathlib import Path

from .token_manager import TokenManager


def get_global_config_path() -> Path:
    """Get the global configuration directory path."""
    config_dir = Path.home() / '.alpacon-mcp'
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / 'token.json'


def get_local_config_path() -> Path:
    """Get the local (project) configuration path."""
    config_dir = Path('config')
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / 'token.json'


def load_existing_config(config_path: Path) -> dict[str, dict[str, str]]:
    """Load existing configuration if it exists."""
    if config_path.exists():
        try:
            with open(config_path) as f:
                data: dict[str, dict[str, str]] = json.load(f)
                return data
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(config: dict[str, dict[str, str]], config_path: Path) -> None:
    """Save configuration to file."""
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)


def test_connection(region: str, workspace: str, token: str) -> bool:
    """Test API connection with provided credentials."""
    try:
        import asyncio

        from .http_client import AlpaconHTTPClient

        async def _test() -> bool:
            client = AlpaconHTTPClient()
            result = await client.get(
                region=region,
                workspace=workspace,
                endpoint='/api/servers/servers/',
                token=token,
            )
            # Check if result contains error
            return result is not None and 'error' not in result

        return asyncio.run(_test())
    except Exception:
        return False


def print_mcp_config() -> None:
    """Print MCP server configuration."""
    print('\n' + '=' * 60)
    print('📋 MCP Server Configuration')
    print('=' * 60)
    print('\nAdd this to your MCP client configuration:')

    print('\n```json')
    print(
        json.dumps(
            {'mcpServers': {'alpacon': {'command': 'uvx', 'args': ['alpacon-mcp']}}},
            indent=2,
        )
    )
    print('```')
    print('\n' + '=' * 60)


def run_setup_wizard(force_local: bool = False, custom_path: str | None = None) -> None:
    """
    Run interactive setup wizard for Alpacon MCP Server.

    Args:
        force_local: If True, save to local config instead of global
        custom_path: Custom path to token.json file (overrides force_local)
    """
    print('\n' + '=' * 60)
    print('🚀 Welcome to Alpacon MCP Server Setup!')
    print('=' * 60)
    print('\nThis wizard will help you configure your Alpacon credentials.')
    print('You can get your API token from: https://alpacon.io\n')

    # Determine config location
    if custom_path:
        config_path = Path(custom_path).expanduser()
        print(f'📁 Using custom config: {config_path}')
    elif force_local:
        config_path = get_local_config_path()
        print(f'📁 Using local config: {config_path}')
    else:
        config_path = get_global_config_path()
        print(f'📁 Using global config: {config_path}')

    # Load existing config
    config = load_existing_config(config_path)

    # Get region
    print('\n' + '-' * 60)
    region = input('Enter region (default: ap1): ').strip() or 'ap1'

    # Get workspace
    workspace = input('Enter workspace name: ').strip()
    if not workspace:
        print('❌ Error: Workspace name is required')
        sys.exit(1)

    # Get API token
    token = getpass('Enter API token (hidden): ').strip()
    if not token:
        print('❌ Error: API token is required')
        sys.exit(1)

    # Update config
    if region not in config:
        config[region] = {}
    config[region][workspace] = token

    # Save config
    try:
        save_config(config, config_path)
        print('\n✅ Configuration saved!')
        print(f'   📁 Location: {config_path}')
    except Exception as e:
        print(f'\n❌ Error saving configuration: {e}')
        sys.exit(1)

    # Test connection
    print('\n🔍 Testing connection...')
    if test_connection(region, workspace, token):
        print('✅ Connection test successful!')
    else:
        print('⚠️  Connection test failed. Please verify your credentials.')
        print('   You can test later with: uvx alpacon-mcp test')

    # Print MCP config
    print_mcp_config()

    print('\n✨ Setup complete!')
    print(f'   📁 Tokens stored in: {config_path}')
    print('\n   Next steps:')
    print('   1. Add the configuration above to your MCP client')
    print('   2. Restart or reconnect your MCP client')


def list_workspaces() -> None:
    """List all configured workspaces."""
    global_config_path = get_global_config_path()
    global_config = load_existing_config(global_config_path)
    local_config_path = get_local_config_path()
    local_config = (
        load_existing_config(local_config_path) if local_config_path.exists() else {}
    )

    print('\n' + '=' * 60)
    print('📋 Configured Workspaces')
    print('=' * 60)

    if global_config:
        print('\n🌍 Global Configuration:')
        for region, workspaces in global_config.items():
            print(f'\n  Region: {region}')
            for workspace in workspaces.keys():
                print(f'    - {workspace}')
    else:
        print('\n🌍 Global: (none)')

    if local_config:
        print('\n📁 Local Configuration:')
        for region, workspaces in local_config.items():
            print(f'\n  Region: {region}')
            for workspace in workspaces.keys():
                print(f'    - {workspace}')
    else:
        print('\n📁 Local: (none)')

    print('\n' + '=' * 60)


def add_workspace() -> None:
    """Add a new workspace to existing configuration."""
    print('\n' + '=' * 60)
    print('➕ Add Workspace')
    print('=' * 60)

    # Choose config location
    print('\nWhere should this workspace be saved?')
    print('1. Global (~/.alpacon-mcp/token.json)')
    print('2. Local (./config/token.json)')
    choice = input('Choice (1/2, default: 1): ').strip() or '1'

    force_local = choice == '2'
    config_path = get_local_config_path() if force_local else get_global_config_path()

    # Load and update config
    config = load_existing_config(config_path)

    region = input('\nEnter region (default: ap1): ').strip() or 'ap1'
    workspace = input('Enter workspace name: ').strip()
    if not workspace:
        print('❌ Error: Workspace name is required')
        return

    # Check if workspace already exists
    if region in config and workspace in config[region]:
        overwrite = (
            input(f"⚠️  Workspace '{workspace}' already exists. Overwrite? (y/N): ")
            .strip()
            .lower()
        )
        if overwrite != 'y':
            print('❌ Cancelled')
            return

    token = getpass('Enter API token (hidden): ').strip()
    if not token:
        print('❌ Error: API token is required')
        return

    # Update and save
    if region not in config:
        config[region] = {}
    config[region][workspace] = token

    try:
        save_config(config, config_path)
        print(f"\n✅ Workspace '{workspace}' added!")
        print(f'   📁 Location: {config_path}')

        # Test connection
        print('\n🔍 Testing connection...')
        if test_connection(region, workspace, token):
            print('✅ Connection test successful!')
        else:
            print('⚠️  Connection test failed. Please verify your credentials.')
    except Exception as e:
        print(f'\n❌ Error saving configuration: {e}')


def test_credentials() -> None:
    """Test configured credentials."""
    print('\n' + '=' * 60)
    print('🔍 Testing Credentials')
    print('=' * 60)

    region = input('\nEnter region (default: ap1): ').strip() or 'ap1'
    workspace = input('Enter workspace name: ').strip()

    if not workspace:
        print('❌ Error: Workspace name is required')
        return

    # Try to get token
    tm = TokenManager()
    token = tm.get_token(region, workspace)

    if not token:
        print(f"❌ No token found for region '{region}' and workspace '{workspace}'")
        print("   Run 'uvx alpacon-mcp setup' to configure credentials")
        return

    print('\n✅ Token found')
    print('🔍 Testing API connection...')

    if test_connection(region, workspace, token):
        print('✅ Connection successful!')
    else:
        print('❌ Connection failed. Please verify your credentials.')
        print('   You can update with: uvx alpacon-mcp setup')


def show_config_info() -> None:
    """Show configuration information and status."""
    print('\n' + '=' * 60)
    print('ℹ️  Configuration Information')
    print('=' * 60)

    # Check configuration files
    global_config_path = get_global_config_path()
    local_config_path = get_local_config_path()

    global_exists = global_config_path.exists()
    local_exists = local_config_path.exists()

    print('\n📁 Configuration Files:')
    print(f'\n  Global: {global_config_path}')
    print(f'  Status: {"✅ Exists" if global_exists else "❌ Not found"}')

    print(f'\n  Local:  {local_config_path}')
    print(f'  Status: {"✅ Exists" if local_exists else "❌ Not found"}')

    # Load and display workspaces
    global_config = load_existing_config(global_config_path) if global_exists else {}
    local_config = load_existing_config(local_config_path) if local_exists else {}

    total_workspaces = 0

    if global_config:
        print('\n🌍 Global Workspaces:')
        for region, workspaces in global_config.items():
            count = len(workspaces)
            total_workspaces += count
            print(f'  {region}: {count} workspace(s)')
            for workspace in workspaces.keys():
                print(f'    - {workspace}')

    if local_config:
        print('\n📁 Local Workspaces:')
        for region, workspaces in local_config.items():
            count = len(workspaces)
            total_workspaces += count
            print(f'  {region}: {count} workspace(s)')
            for workspace in workspaces.keys():
                print(f'    - {workspace}')

    # Environment variables
    print('\n🔐 Environment Variables:')
    env_vars = [key for key in os.environ.keys() if key.startswith('ALPACON_MCP_')]
    if env_vars:
        for var in env_vars:
            if 'TOKEN' in var:
                print(f'  ✅ {var}: configured')
            else:
                print(f'  ℹ️  {var}: {os.environ[var]}')
    else:
        print('  (none)')

    # Summary
    print('\n📊 Summary:')
    print(f'  Total workspaces: {total_workspaces}')
    print('  Configuration priority:')
    print('    1. Environment variables')
    print('    2. Local config (./config/token.json)')
    print('    3. Global config (~/.alpacon-mcp/token.json)')

    print('\n' + '=' * 60)

    if total_workspaces == 0:
        print(
            "\n💡 No workspaces configured. Run 'uvx alpacon-mcp setup' to get started."
        )
