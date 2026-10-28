"""Cache per-workspace security settings from the account service for the MFA pre-check
in remote mode."""

import asyncio
import hashlib
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx

from utils.logger import escape_for_log, get_logger
from utils.types import JsonValue

logger = get_logger('security_settings')

_CACHE_TTL = 300  # 5 minutes
_DEFAULT_MFA_TIMEOUT = 3600  # the server reads a null mfa_timeout as this


def _str_list(value: JsonValue) -> list[str] | None:
    """A JSON list of strings, or None for any other value, a mixed list included."""
    if not isinstance(value, list):
        return None
    strings = [item for item in value if isinstance(item, str)]
    return strings if len(strings) == len(value) else None


class WorkspaceSecuritySettings:
    def __init__(self, data: Mapping[str, JsonValue]) -> None:
        # A malformed field reads as its strictest value, never looser than meant.
        self.mfa_required = bool(data.get('mfa_required', False))
        timeout = data.get('mfa_timeout')
        if timeout is None:
            timeout = _DEFAULT_MFA_TIMEOUT
        elif isinstance(timeout, bool) or not isinstance(timeout, int | float):
            timeout = 0
        self.mfa_timeout: float = timeout
        # None: malformed, so every action requires MFA and no method satisfies it.
        self.mfa_required_actions = _str_list(data.get('mfa_required_actions', []))
        self.allowed_mfa_methods = _str_list(data.get('allowed_mfa_methods', []))

    def is_action_mfa_required(self, action: str) -> bool:
        if not self.mfa_required:
            return False
        actions = self.mfa_required_actions
        return actions is None or action in actions


class SecuritySettingsCache:
    """In-memory settings cache keyed by token hash, so one user's settings never serve
    another."""

    def __init__(self, ttl: float = _CACHE_TTL) -> None:
        self._ttl = ttl
        # {token_key: {workspace: (settings, expiry_time)}}
        self._cache: dict[str, dict[str, tuple[WorkspaceSecuritySettings, float]]] = {}
        # Per-token in-flight deduplication to prevent thundering herd
        self._inflight: dict[
            str, asyncio.Task[dict[str, WorkspaceSecuritySettings]]
        ] = {}
        # Timestamp of last global prune (max once per TTL period)
        self._last_prune: float = 0

    @staticmethod
    def _token_key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()[:16]

    def _prune_expired(self) -> None:
        """Drop expired entries; runs from get_settings at most once per TTL period."""
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
        key = self._token_key(token)
        if key not in self._cache:
            self._cache[key] = {}
        expiry = time.time() + self._ttl
        for workspace, settings in settings_by_workspace.items():
            self._cache[key][workspace] = (settings, expiry)

    async def fetch_and_cache(self, token: str) -> dict[str, WorkspaceSecuritySettings]:
        """Fetch and cache the token's workspace settings; returns {} when
        ALPACON_ACCOUNT_URL is unset or the fetch fails."""
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
        """Settings for a workspace, fetched on a cache miss with concurrent fetches per
        token shared; None when undeterminable (fail-open)."""
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
    jwt_claims: Mapping[str, object],
    settings: WorkspaceSecuritySettings,
) -> bool:
    """True when a non-expired MFA completion in the JWT satisfies the settings; mirrors
    alpacon-server's check_mfa_completed()."""
    namespace = os.getenv('AUTH0_NAMESPACE', 'https://alpacon.io/').rstrip('/') + '/'
    mfa_claim_key = f'{namespace}completed_mfa_methods'
    completed_mfa = jwt_claims.get(mfa_claim_key, {})

    if not completed_mfa or not isinstance(completed_mfa, dict):
        return False

    allowed_methods = settings.allowed_mfa_methods
    if allowed_methods is None:
        return False
    now = datetime.now(tz=UTC)

    for method, timestamp_str in completed_mfa.items():
        if allowed_methods and method not in allowed_methods:
            continue

        if not isinstance(timestamp_str, str):
            logger.warning(
                'MFA claim value is not a string for method %s: %s',
                escape_for_log(method),
                escape_for_log(repr(timestamp_str)),
            )
            continue

        try:
            mfa_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            if mfa_time.tzinfo is None:
                mfa_time = mfa_time.replace(tzinfo=UTC)

            elapsed = (now - mfa_time).total_seconds()
            if elapsed < 0:
                logger.warning(
                    'MFA timestamp from future rejected: %s',
                    escape_for_log(timestamp_str),
                )
                continue

            if elapsed < settings.mfa_timeout:
                return True
        except (ValueError, TypeError) as e:
            logger.warning(
                'Failed to parse MFA timestamp %s: %s',
                escape_for_log(timestamp_str),
                escape_for_log(e),
            )
            continue

    return False


def get_action_for_tool(tool_name: str) -> str | None:
    """Return the MFA action type ('webftp' or 'command') for a tool name, or None."""
    if tool_name.startswith('webftp_'):
        return 'webftp'
    if tool_name in (
        'execute_command',
        'execute_file',
        'execute_command_multi_server',
        'list_commands',
    ):
        return 'command'
    return None


# Singleton
security_cache = SecuritySettingsCache()
