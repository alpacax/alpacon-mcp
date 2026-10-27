"""Token management utilities for Alpacon MCP server."""

import json
import os
from pathlib import Path
from typing import TypedDict

from utils.logger import get_logger
from utils.types import JsonValue

logger = get_logger('token_manager')


class RegionStatus(TypedDict):
    region: str
    workspaces: list[str]
    count: int


class AuthStatus(TypedDict):
    authenticated: bool
    total_tokens: int
    regions: list[RegionStatus]
    config_dir: str
    token_file: str


class TokenManager:
    """Reads and writes the region -> workspace -> token store in the config file."""

    def __init__(self, config_file: str | None = None):
        """Config file: explicit path, else ALPACON_MCP_CONFIG_FILE, else the existing
        ~/.alpacon-mcp/token.json or ./config/token.json, else the global path."""
        if config_file:
            # Use specific config file path, expand ~ to home directory
            expanded_path = os.path.expanduser(config_file)
            self.token_file = Path(expanded_path)
            logger.info('Using specified config file: %s', self.token_file)
        else:
            # Check environment variable first
            env_config_file = os.getenv('ALPACON_MCP_CONFIG_FILE')
            if env_config_file:
                # Expand ~ to home directory
                expanded_path = os.path.expanduser(env_config_file)
                self.token_file = Path(expanded_path)
                logger.info('Using config file from environment: %s', self.token_file)
            else:
                # Use global config by default, fall back to local
                global_config = Path.home() / '.alpacon-mcp' / 'token.json'
                local_config = Path('config/token.json')

                if global_config.exists():
                    self.token_file = global_config
                    logger.info('Using global config file: %s', self.token_file)
                elif local_config.exists():
                    self.token_file = local_config
                    logger.info('Using local config file: %s', self.token_file)
                else:
                    # Default to global config location
                    self.token_file = global_config
                    logger.info(
                        'No config found, will use global location: %s', self.token_file
                    )

        self.config_dir = self.token_file.parent

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        logger.debug('Config directory created/verified: %s', self.config_dir)

        self.tokens = self._load_tokens()

    def _load_tokens(self) -> dict[str, JsonValue]:
        """Return the file's token object; {} if missing, unreadable or not one."""
        if not self.token_file.exists():
            logger.warning(
                'No token file at %s, starting with empty tokens', self.token_file
            )
            return {}

        try:
            with open(self.token_file) as f:
                tokens = json.load(f)
        except json.JSONDecodeError as e:
            logger.error('JSON decode error in %s: %s', self.token_file, e)
            return {}
        except OSError as e:
            logger.error('IO error reading %s: %s', self.token_file, e)
            return {}

        if not isinstance(tokens, dict):  # an array or scalar parses too
            logger.error(
                '%s must hold a JSON object of regions, found %s',
                self.token_file,
                type(tokens).__name__,
            )
            return {}

        logger.info('Loaded tokens from %s: %s regions', self.token_file, len(tokens))
        return tokens

    def _save_tokens_to_file(
        self, tokens: dict[str, JsonValue], file_path: Path
    ) -> None:
        """Write the tokens to file_path."""
        # Ensure directory exists
        file_path.parent.mkdir(exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(tokens, f, indent=2)

    def _save_tokens(self) -> None:
        """Persist the tokens to the config file."""
        self._save_tokens_to_file(self.tokens, self.token_file)

    def set_token(self, region: str, workspace: str, token: str) -> dict[str, str]:
        """Store the token under region and workspace, persisting to the config file."""
        workspaces = self.tokens.get(region)
        if not isinstance(workspaces, dict):  # absent, or not an object to add to
            workspaces = self.tokens[region] = {}

        # Simplified structure: region -> workspace -> token (string only)
        workspaces[workspace] = token

        self._save_tokens()

        return {
            'status': 'success',
            'message': f'Token saved for {workspace}.{region}',
            'region': region,
            'workspace': workspace,
        }

    @staticmethod
    def _entry_token(entry: JsonValue) -> str | None:
        """Return a config entry's token (string or ``{"token", ...}``), or None."""
        if isinstance(entry, dict):
            token = entry.get('token')
            return token if isinstance(token, str) and token else None
        if isinstance(entry, str) and entry:
            return entry
        return None

    def get_token(self, region: str, workspace: str) -> str | None:
        """Return the token from ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN, else the config
        file; None if neither has one."""
        logger.debug('Getting token for %s.%s', workspace, region)

        # First try environment variable: ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN
        env_var_name = f'ALPACON_MCP_{region.upper()}_{workspace.upper()}_TOKEN'
        env_token = os.getenv(env_var_name)
        if env_token:
            logger.debug(
                'Found token for %s.%s from environment variable', workspace, region
            )
            return env_token

        # Fall back to config file. An entry may be a bare token string or an
        # object ``{"token": "...", "url": "..."}``; unwrap either form.
        workspaces = self.tokens.get(region)
        if isinstance(workspaces, dict) and workspace in workspaces:
            token = self._entry_token(workspaces[workspace])
            if token:
                logger.debug(
                    'Found token for %s.%s from config file', workspace, region
                )
                return token

        logger.warning('No token found for %s.%s', workspace, region)
        return None

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        """Add https:// to a scheme-less base URL and drop the trailing '/'."""
        url = url.strip().rstrip('/')
        if url and '://' not in url:
            url = 'https://' + url
        return url

    def get_base_url_override(self, region: str, workspace: str) -> str | None:
        """Return the pinned API base URL, or None so the caller derives it (ADR 0027).
        Checks ALPACON_MCP_<REGION>_<WORKSPACE>_URL, then the entry's ``url``."""
        env_var_name = f'ALPACON_MCP_{region.upper()}_{workspace.upper()}_URL'
        env_url = os.getenv(env_var_name)
        if env_url and env_url.strip():
            return self._normalize_base_url(env_url)

        workspaces = self.tokens.get(region)
        if isinstance(workspaces, dict) and workspace in workspaces:
            entry = workspaces[workspace]
            if isinstance(entry, dict):
                url = entry.get('url')
                if isinstance(url, str) and url.strip():
                    return self._normalize_base_url(url)

        return None

    def get_all_tokens(self) -> dict[str, dict[str, JsonValue]]:
        """Get the stored tokens by region, without top-level non-object values."""
        return {
            region: workspaces
            for region, workspaces in self.tokens.items()
            if isinstance(workspaces, dict)
        }

    def get_available_regions(self) -> list[str]:
        """Return the regions that have a token object configured."""
        return list(self.get_all_tokens())

    def get_default_region(self) -> str | None:
        """Return the region when exactly one is configured, else None."""
        regions = self.get_available_regions()
        if len(regions) == 1:
            return regions[0]
        return None

    def find_region_for_workspace(self, workspace: str) -> str | None:
        """Return the region holding the workspace; None if it is in none or several."""
        matching_regions = [
            region
            for region, workspaces in self.tokens.items()
            if isinstance(workspaces, dict) and workspace in workspaces
        ]
        if len(matching_regions) == 1:
            return matching_regions[0]
        return None

    def remove_token(self, region: str, workspace: str) -> dict[str, str]:
        """Delete the token, dropping an emptied region; an error dict if absent."""
        workspaces = self.tokens.get(region)
        if isinstance(workspaces, dict) and workspace in workspaces:
            del workspaces[workspace]

            # Clean up empty region
            if not workspaces:
                del self.tokens[region]

            self._save_tokens()

            return {
                'status': 'success',
                'message': f'Token removed for {workspace}.{region}',
            }

        return {
            'status': 'error',
            'message': f'No token found for {workspace}.{region}',
        }

    def get_auth_status(self) -> AuthStatus:
        """Summarize the stored tokens per region, with the config paths."""
        by_region = {
            region: workspaces
            for region, workspaces in self.tokens.items()
            if isinstance(workspaces, dict)  # a non-object value holds no tokens
        }
        total_tokens = sum(len(workspaces) for workspaces in by_region.values())

        regions: list[RegionStatus] = []
        for region, workspaces in by_region.items():
            regions.append(
                {
                    'region': region,
                    'workspaces': list(workspaces.keys()),
                    'count': len(workspaces),
                }
            )

        return {
            'authenticated': total_tokens > 0,
            'total_tokens': total_tokens,
            'regions': regions,
            'config_dir': str(self.config_dir),
            'token_file': str(self.token_file),
        }


# Global token manager instance
_global_token_manager = None


def get_token_manager() -> TokenManager:
    """Return the process-wide TokenManager, creating it on first use."""
    global _global_token_manager
    if _global_token_manager is None:
        # Let TokenManager handle config file resolution logic
        _global_token_manager = TokenManager()
    return _global_token_manager
