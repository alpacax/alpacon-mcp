"""Token management utilities for Alpacon MCP server."""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Any


class TokenManager:
    """Manages API tokens for different regions and workspaces."""

    def __init__(self, config_dir: Optional[str] = None):
        """Initialize token manager.

        Args:
            config_dir: Directory to store token configuration.
                       If None, will try .config first (dev), then config (prod)
        """
        if config_dir:
            self.config_dir = Path(config_dir)
            self.config_dirs = [self.config_dir]
        else:
            # Development: .config (hidden directory for local dev)
            # Production: config (standard directory for MCP)
            self.dev_config = Path(".config")
            self.prod_config = Path("config")
            self.config_dirs = [self.dev_config, self.prod_config]

            # Use .config if it exists or if we're in development mode
            # Otherwise use config for production
            if self.dev_config.exists() or os.getenv("ALPACON_DEV", "false").lower() == "true":
                self.config_dir = self.dev_config
            else:
                self.config_dir = self.prod_config

        # Ensure config directory exists
        self.config_dir.mkdir(exist_ok=True)
        self.token_file = self.config_dir / "token.json"
        self.tokens = self._load_tokens()

    def _load_tokens(self) -> Dict[str, Any]:
        """Load tokens from configuration file.

        Tries to load from multiple config directories in order.

        Returns:
            Dictionary containing token data
        """
        # Try to load from primary config directory first
        if self.token_file.exists():
            try:
                with open(self.token_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # If using automatic config detection, try other directories
        if hasattr(self, 'config_dirs') and len(self.config_dirs) > 1:
            for config_dir in self.config_dirs:
                if config_dir != self.config_dir:
                    token_file = config_dir / "token.json"
                    if token_file.exists():
                        try:
                            with open(token_file, 'r') as f:
                                tokens = json.load(f)
                                # Copy tokens to primary config if they exist
                                if tokens:
                                    self._save_tokens_to_file(tokens, self.token_file)
                                return tokens
                        except (json.JSONDecodeError, IOError):
                            continue

        return {}

    def _save_tokens_to_file(self, tokens: Dict[str, Any], file_path: Path) -> None:
        """Save tokens to specific file.

        Args:
            tokens: Token data to save
            file_path: Path to save the tokens
        """
        # Ensure directory exists
        file_path.parent.mkdir(exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(tokens, f, indent=2)

    def _save_tokens(self) -> None:
        """Save tokens to configuration file."""
        self._save_tokens_to_file(self.tokens, self.token_file)

    def set_token(self, region: str, workspace: str, token: str) -> Dict[str, str]:
        """Set token for specific region and workspace.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name
            token: API token

        Returns:
            Success message with details
        """
        if region not in self.tokens:
            self.tokens[region] = {}

        self.tokens[region][workspace] = {
            "token": token,
            "workspace": workspace,
            "region": region
        }

        self._save_tokens()

        return {
            "status": "success",
            "message": f"Token saved for {workspace}.{region}",
            "region": region,
            "workspace": workspace
        }

    def get_token(self, region: str, workspace: str) -> Optional[Dict[str, str]]:
        """Get token for specific region and workspace.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name

        Returns:
            Token information if found, None otherwise
        """
        if region in self.tokens and workspace in self.tokens[region]:
            return self.tokens[region][workspace]
        return None

    def get_all_tokens(self) -> Dict[str, Any]:
        """Get all stored tokens.

        Returns:
            All token data
        """
        return self.tokens

    def remove_token(self, region: str, workspace: str) -> Dict[str, str]:
        """Remove token for specific region and workspace.

        Args:
            region: Region (ap1, us1, eu1, etc.)
            workspace: Workspace name

        Returns:
            Success or error message
        """
        if region in self.tokens and workspace in self.tokens[region]:
            del self.tokens[region][workspace]

            # Clean up empty region
            if not self.tokens[region]:
                del self.tokens[region]

            self._save_tokens()

            return {
                "status": "success",
                "message": f"Token removed for {workspace}.{region}"
            }

        return {
            "status": "error",
            "message": f"No token found for {workspace}.{region}"
        }

    def get_auth_status(self) -> Dict[str, Any]:
        """Get authentication status for all stored tokens.

        Returns:
            Authentication status information
        """
        total_tokens = sum(len(workspaces) for workspaces in self.tokens.values())

        regions = []
        for region, workspaces in self.tokens.items():
            regions.append({
                "region": region,
                "workspaces": list(workspaces.keys()),
                "count": len(workspaces)
            })

        return {
            "authenticated": total_tokens > 0,
            "total_tokens": total_tokens,
            "regions": regions,
            "config_dir": str(self.config_dir),
            "is_dev_mode": str(self.config_dir).endswith(".config")
        }

    def get_config_info(self) -> Dict[str, Any]:
        """Get configuration directory information.

        Returns:
            Configuration directory details
        """
        available_configs = []
        if hasattr(self, 'config_dirs'):
            for config_dir in self.config_dirs:
                token_file = config_dir / "token.json"
                available_configs.append({
                    "dir": str(config_dir),
                    "exists": config_dir.exists(),
                    "token_file_exists": token_file.exists(),
                    "is_current": config_dir == self.config_dir
                })

        return {
            "current_config_dir": str(self.config_dir),
            "is_dev_mode": str(self.config_dir).endswith(".config"),
            "available_configs": available_configs,
            "env_var_dev_mode": os.getenv("ALPACON_DEV", "false").lower() == "true"
        }