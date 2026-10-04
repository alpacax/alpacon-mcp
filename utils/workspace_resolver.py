"""Resolve a workspace URL slug to its fixed ``schema_name``.

A workspace's URL slug can be renamed while its ``schema_name`` stays fixed,
and the JWT workspace claims only carry the ``schema_name``. When the
``workspace`` argument is not a claim's ``schema_name``, ask the account
service's public lookup which workspace the segment belongs to.

Every failure resolves to ``None`` so the caller keeps rejecting the argument.
"""

import os
import time

import httpx

from utils.error_handler import validate_workspace_format
from utils.logger import escape_for_log, get_logger

logger = get_logger('workspace_resolver')

ACCOUNT_BASE_URL = 'https://account.alpacax.com'
_LOOKUP_PATH = '/api/workspaces/organization/'
_LOOKUP_TIMEOUT = 3.0
_CACHE_TTL = 60.0
_CACHE_MAX_ENTRIES = 256

# slug -> (schema_name, expiry); only successful lookups are stored.
_cache: dict[str, tuple[str, float]] = {}


def clear_cache() -> None:
    _cache.clear()


def _account_base_url() -> str:
    # ALPACON_ACCOUNT_URL already points the MFA pre-check at the account service.
    return (os.getenv('ALPACON_ACCOUNT_URL') or ACCOUNT_BASE_URL).rstrip('/')


async def lookup_schema_name(slug: str) -> str | None:
    """Return the ``schema_name`` for a slug, or None on any failure."""
    now = time.monotonic()
    cached = _cache.get(slug)
    if cached and cached[1] > now:
        return cached[0]

    try:
        async with httpx.AsyncClient(timeout=_LOOKUP_TIMEOUT) as client:
            response = await client.get(
                f'{_account_base_url()}{_LOOKUP_PATH}', params={'slug': slug}
            )
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

    if len(_cache) >= _CACHE_MAX_ENTRIES:
        for key in [k for k, (_, exp) in _cache.items() if exp <= now]:
            del _cache[key]
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            _cache.clear()
    _cache[slug] = (organization, now + _CACHE_TTL)
    return organization


async def resolve_workspace(workspace: str, claim_workspaces: list[dict]) -> str:
    """Map ``workspace`` to a claim's ``schema_name`` when it is a renamed slug.

    Returns ``workspace`` unchanged when it already is a ``schema_name`` in the
    claims (no network call), and also when the lookup fails or names a
    workspace the token does not grant, so the usual rejection applies.
    """
    schema_names = {ws.get('schema_name') for ws in claim_workspaces}
    if workspace in schema_names:
        return workspace
    resolved = await lookup_schema_name(workspace)
    if resolved is not None and resolved in schema_names:
        return resolved
    return workspace
