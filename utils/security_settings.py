"""Workspace security settings cache for MFA pre-check.

Fetches and caches per-workspace security settings from the Alpacon
account service. Used in remote (streamable-http) mode to proactively
determine whether MFA is required before making API calls.
"""

import asyncio
import hashlib
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from utils.logger import get_logger

logger = get_logger('security_settings')

_CACHE_TTL = 300  # 5 minutes


class WorkspaceSecuritySettings:
    """Parsed security settings for a single workspace."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.mfa_required: bool = data.get('mfa_required', False)
        self.mfa_timeout: int = data.get('mfa_timeout', 3600)
        self.mfa_required_actions: list[str] = data.get('mfa_required_actions', [])
        self.allowed_mfa_methods: list[str] = data.get('allowed_mfa_methods', [])

    def is_action_mfa_required(self, action: str) -> bool:
        """Check if a specific action requires MFA."""
        if not self.mfa_required:
            return False
        return action in self.mfa_required_actions


class SecuritySettingsCache:
    """In-memory cache for workspace security settings.

    Fetches from the account service API and caches per-user (token hash)
    with a configurable TTL.
    """

    def __init__(self, ttl: float = _CACHE_TTL) -> None:
        self._ttl = ttl
        # {token_key: {workspace: (settings, expiry_time)}}
        self._cache: dict[str, dict[str, tuple[WorkspaceSecuritySettings, float]]] = {}
        # Per-token in-flight deduplication to prevent thundering herd
        self._inflight: dict[str, asyncio.Task] = {}
        # Timestamp of last global prune (max once per TTL period)
        self._last_prune: float = 0

    @staticmethod
    def _token_key(token: str) -> str:
        """Derive a short hash key from a JWT for cache isolation."""
        return hashlib.sha256(token.encode()).hexdigest()[:16]

    def _prune_expired(self) -> None:
        """Remove all expired entries across all tokens.

        Called opportunistically from get_settings, at most once per TTL
        period to avoid excessive iteration on every lookup.
        """
        now = time.time()
        if (now - self._last_prune) < self._ttl:
            return
        self._last_prune = now

        empty_keys = []
        for token_key, ws_cache in self._cache.items():
            expired = [ws for ws, (_, exp) in ws_cache.items() if now > exp]
            for ws in expired:
                del ws_cache[ws]
            if not ws_cache:
                empty_keys.append(token_key)
        for key in empty_keys:
            del self._cache[key]

    def get_cached(
        self, token: str, workspace: str
    ) -> WorkspaceSecuritySettings | None:
        """Return cached settings if still valid, None otherwise."""
        key = self._token_key(token)
        user_cache = self._cache.get(key)
        if not user_cache:
            return None

        entry = user_cache.get(workspace)
        if not entry:
            return None

        settings, expiry = entry
        if time.time() > expiry:
            del user_cache[workspace]
            if not user_cache:
                del self._cache[key]
            return None

        return settings

    def _put_bulk(
        self, token: str, settings_by_workspace: dict[str, WorkspaceSecuritySettings]
    ) -> None:
        """Store multiple workspace settings at once."""
        key = self._token_key(token)
        if key not in self._cache:
            self._cache[key] = {}
        expiry = time.time() + self._ttl
        for workspace, settings in settings_by_workspace.items():
            self._cache[key][workspace] = (settings, expiry)

    async def fetch_and_cache(self, token: str) -> dict[str, WorkspaceSecuritySettings]:
        """Fetch security settings from account service and cache them.

        Args:
            token: JWT token for authentication

        Returns:
            Dict of workspace name -> settings
        """
        account_url = os.getenv('ALPACON_ACCOUNT_URL', '').rstrip('/')
        if not account_url:
            if not hasattr(self, '_account_url_warned'):
                logger.warning(
                    'ALPACON_ACCOUNT_URL not set, skipping security settings fetch'
                )
                self._account_url_warned = True
            return {}

        endpoint = f'{account_url}/api/workspaces/security/'

        try:
            headers = {
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(endpoint, headers=headers)
                response.raise_for_status()
                data = response.json()

            results: dict[str, WorkspaceSecuritySettings] = {}

            # Handle both list and paginated response formats
            items = data if isinstance(data, list) else data.get('results', [])
            for item in items:
                ws_name = item.get('workspace') or item.get('schema_name', '')
                if not ws_name:
                    continue
                results[ws_name] = WorkspaceSecuritySettings(item)

            self._put_bulk(token, results)
            logger.info('Fetched security settings for %d workspaces', len(results))
            return results

        except Exception as e:
            logger.warning('Failed to fetch security settings: %s', e)
            return {}

    async def get_settings(
        self, token: str, workspace: str
    ) -> WorkspaceSecuritySettings | None:
        """Get settings for a workspace, fetching if not cached.

        Uses per-token in-flight deduplication to prevent thundering herd
        when multiple concurrent tool calls trigger a cache miss for the
        same token.

        Returns None if settings cannot be determined (fail-open).
        """
        self._prune_expired()

        cached = self.get_cached(token, workspace)
        if cached is not None:
            return cached

        key = self._token_key(token)

        # Deduplicate concurrent fetches for the same token
        if key in self._inflight:
            try:
                results = await self._inflight[key]
            except Exception:
                return None
            return results.get(workspace)

        task = asyncio.ensure_future(self.fetch_and_cache(token))
        self._inflight[key] = task
        try:
            results = await task
        finally:
            self._inflight.pop(key, None)

        return results.get(workspace)


def check_mfa_completed(
    jwt_claims: dict[str, Any],
    settings: WorkspaceSecuritySettings,
) -> bool:
    """Check if JWT has valid (non-expired) MFA completion.

    Mirrors alpacon-server's check_mfa_completed() logic.

    Args:
        jwt_claims: Decoded JWT claims
        settings: Workspace security settings

    Returns:
        True if MFA is completed and within timeout, False otherwise
    """
    namespace = os.getenv('AUTH0_NAMESPACE', 'https://alpacon.io/').rstrip('/') + '/'
    mfa_claim_key = f'{namespace}completed_mfa_methods'
    completed_mfa = jwt_claims.get(mfa_claim_key, {})

    if not completed_mfa or not isinstance(completed_mfa, dict):
        return False

    allowed_methods = settings.allowed_mfa_methods
    now = datetime.now(tz=UTC)

    for method, timestamp_str in completed_mfa.items():
        if allowed_methods and method not in allowed_methods:
            continue

        if not isinstance(timestamp_str, str):
            logger.warning(
                'MFA claim value is not a string for method %s: %r',
                method,
                timestamp_str,
            )
            continue

        try:
            mfa_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            if mfa_time.tzinfo is None:
                mfa_time = mfa_time.replace(tzinfo=UTC)

            elapsed = (now - mfa_time).total_seconds()
            if elapsed < 0:
                logger.warning('MFA timestamp from future rejected: %s', timestamp_str)
                continue

            if elapsed < settings.mfa_timeout:
                return True
        except (ValueError, TypeError) as e:
            logger.warning('Failed to parse MFA timestamp %s: %s', timestamp_str, e)
            continue

    return False


def get_action_for_tool(tool_name: str) -> str | None:
    """Determine MFA action type from tool function name.

    Returns 'websh', 'webftp', 'command', or None.
    """
    if tool_name.startswith('websh_') or tool_name in (
        'execute_command',
        'execute_command_batch',
    ):
        return 'websh'
    if tool_name.startswith('webftp_'):
        return 'webftp'
    if tool_name in (
        'execute_command_with_acl',
        'execute_command_sync',
        'execute_command_multi_server',
        'get_command_result',
        'list_commands',
    ):
        return 'command'
    return None


# Singleton
security_cache = SecuritySettingsCache()
