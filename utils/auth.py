import json
import subprocess
from pathlib import Path

# Base directory where our data lives
DATA_DIR = Path(__file__).resolve().parent.parent / "config"
default_file_path = DATA_DIR / "token.json"


def get_token(region: str, workspace: str, config_file: str = None):
    """Get token for region and workspace from config file.

    Args:
        region: Region name (e.g., 'ap1', 'us1')
        workspace: Workspace/schema name (e.g., 'alpacax')
        config_file: Path to config file (optional, uses default if not provided)

    Returns:
        Token string directly
    """
    file_path = config_file if config_file else default_file_path
    with open(file_path, "r") as f:
        data = json.load(f)
    return data[region][workspace]


def login(region: str, workspace: str, token: str):
    # region is now used directly (ap1, us1, eu1, etc.)
    domain = f'{workspace}.{region}.alpacon.io'
    print(f"Logging in to {domain}")

    subprocess.run(["alpacon", "login", domain, "-t", token])


def logout():
    subprocess.run(["alpacon", "logout"])
