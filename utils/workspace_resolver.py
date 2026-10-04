"""Resolve a workspace URL slug to its fixed ``schema_name``.

A workspace's URL slug can be renamed while its ``schema_name`` stays fixed,
and the JWT workspace claims only carry the ``schema_name``. When the
``workspace`` argument is not a claim's ``schema_name``, ask the account
service's public lookup which workspace the segment belongs to.

The lookup is skipped when ``ALPACON_ACCOUNT_URL`` is unset. Every failure resolves to ``None`` so the caller keeps rejecting the argument.
"""

import os
import re
import time

import httpx

from utils.error_handler import validate_workspace_format
from utils.logger import escape_for_log, get_logger

logger = get_logger('workspace_resolver')

_SLUG_PATTERN = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')
_LOOKUP_PATH = '/api/workspaces/organization/'
_LOOKUP_TIMEOUT = 3.0
_CACHE_TTL = 60.0  # matches the lookup's own max-age
_CACHE_MAX_ENTRIES = 256

# slug -> (schema_name or None for a 404, expiry). A 429, a network error and a
# timeout are never stored.
_cache: dict[str, tuple[str | None, float]] = {}


def clear_cache() -> None:
    _cache.clear()


def _account_base_url() -> str:
    # Same variable as the MFA pre-check; unset disables the lookup.
    return os.getenv('ALPACON_ACCOUNT_URL', '').rstrip('/')


def _store(slug: str, value: str | None, now: float) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        for key in [k for k, (_, exp) in _cache.items() if exp <= now]:
            del _cache[key]
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            _cache.clear()
    _cache[slug] = (value, now + _CACHE_TTL)


async def lookup_schema_name(slug: str) -> str | None:
    """Return the ``schema_name`` for a slug, or None on any failure."""
    base_url = _account_base_url()
    if not base_url or not _SLUG_PATTERN.fullmatch(slug):
        return None

    now = time.monotonic()
    cached = _cache.get(slug)
    if cached and cached[1] > now:
        return cached[0]

    try:
        async with httpx.AsyncClient(timeout=_LOOKUP_TIMEOUT) as client:
            response = await client.get(
                f'{base_url}{_LOOKUP_PATH}', params={'slug': slug}
            )
        if response.status_code == 404:
            _store(slug, None, now)
            return None
        if response.status_code != 200:
            logger.info(
                'Workspace slug lookup for %s returned %s',
                escape_for_log(slug),
                response.status_code,
            )
            return None
        body = response.json()
        organization = body.get('organization') if isinstance(body, dict) else None
    except Exception as e:  # network error, timeout, bad JSON: keep rejecting
        logger.info(
            'Workspace slug lookup for %s failed: %s', escape_for_log(slug), type(e)
        )
        return None

    if not isinstance(organization, str) or not validate_workspace_format(organization):
        return None

    _store(slug, organization, now)
    return organization


async def resolve_workspace(workspace: str, claim_workspaces: list[dict]) -> str:
    """Map ``workspace`` to a claim's ``schema_name`` when it is a renamed slug.

    Returns ``workspace`` unchanged when it already is a ``schema_name`` in the
    claims (no network call), and also when the lookup fails or names a
    workspace the token does not grant, so the usual rejection applies.
    """
    schema_names = {ws.get('schema_name') for ws in claim_workspaces}
    if not schema_names:
        return workspace
    if workspace in schema_names:
        return workspace
    resolved = await lookup_schema_name(workspace)
    if resolved is not None and resolved in schema_names:
        return resolved
    return workspace
