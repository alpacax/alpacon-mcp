"""Auth0 JWT verification for remote MCP server mode."""

import asyncio
import json
import os
import time
from typing import Any

import httpx
import jwt
from mcp.server.auth.provider import AccessToken

from utils.logger import get_logger

logger = get_logger('auth')

# JWKS cache: stores fetched keys and expiry time
_jwks_cache: dict[str, Any] = {}
_jwks_cache_expiry: float = 0
_JWKS_CACHE_TTL = 3600  # 1 hour
_jwks_lock: asyncio.Lock | None = None

# Auth0 can rotate its signing key at any time, so a kid the cache does not know
# is a reason to refetch before the TTL expires. The cooldown bounds how often an
# unknown kid can reach Auth0, and matches the 60-second MFA re-auth cooldown in
# auth_error_middleware.
_JWKS_FORCED_FETCH_COOLDOWN = 60
_jwks_last_forced_fetch: float = 0


def _get_jwks_lock() -> asyncio.Lock:
    """Get or create the JWKS cache lock (lazy init for event loop safety)."""
    global _jwks_lock
    if _jwks_lock is None:
        _jwks_lock = asyncio.Lock()
    return _jwks_lock


def _get_auth0_config() -> dict[str, str]:
    """Get Auth0 configuration from environment variables."""
    domain = os.getenv('AUTH0_DOMAIN', '')
    audience = os.getenv('AUTH0_AUDIENCE', 'https://alpacon.io/access/')
    namespace = os.getenv('AUTH0_NAMESPACE', 'https://alpacon.io/').rstrip('/') + '/'

    if not domain:
        raise ValueError('AUTH0_DOMAIN environment variable is required')

    return {
        'domain': domain,
        'audience': audience,
        'namespace': namespace,
        'issuer': f'https://{domain}/',
        'jwks_url': f'https://{domain}/.well-known/jwks.json',
    }


async def _fetch_jwks(jwks_url: str, *, force: bool = False) -> dict[str, Any]:
    """Fetch JWKS from Auth0 endpoint with caching.

    Uses an async lock to prevent concurrent fetches from racing
    on the module-level cache. With ``force``, the cached keys are read
    again unless another forced fetch beat this one to it, in which case
    the caller gets those fresh keys instead of a second round trip.
    """
    global _jwks_cache, _jwks_cache_expiry, _jwks_last_forced_fetch

    now = time.time()
    if not force and _jwks_cache and now < _jwks_cache_expiry:
        return _jwks_cache

    async with _get_jwks_lock():
        # Double-check after acquiring lock (another coroutine may have refreshed)
        now = time.time()
        if not force and _jwks_cache and now < _jwks_cache_expiry:
            return _jwks_cache

        if force:
            if now - _jwks_last_forced_fetch < _JWKS_FORCED_FETCH_COOLDOWN:
                logger.warning('Skipping forced JWKS fetch: cooldown still active')
                return _jwks_cache
            _jwks_last_forced_fetch = now

        logger.info(f'Fetching JWKS from {jwks_url}')
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_expiry = now + _JWKS_CACHE_TTL

        logger.info(f'JWKS fetched: {len(_jwks_cache.get("keys", []))} keys')
        return _jwks_cache


def _has_kid(token: str) -> bool:
    """Check whether the token header carries a kid worth looking up again."""
    try:
        return bool(jwt.get_unverified_header(token).get('kid'))
    except jwt.exceptions.DecodeError:
        return False


def _get_signing_key(jwks: dict[str, Any], token: str) -> Any | None:
    """Extract the signing key from JWKS matching the token's kid."""
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError as e:
        logger.error(f'Failed to decode JWT header: {e}')
        return None

    kid = unverified_header.get('kid')
    if not kid:
        logger.error('JWT header missing kid')
        return None

    for key in jwks.get('keys', []):
        if key.get('kid') == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))

    logger.error(f'No matching key found for kid: {kid}')
    return None


def decode_jwt(
    token: str, public_key: Any, config: dict[str, str]
) -> dict[str, Any] | None:
    """Decode and verify a JWT token.

    Args:
        token: The raw JWT string
        public_key: RSA public key from JWKS
        config: Auth0 configuration dict

    Returns:
        Decoded claims dict, or None if verification fails
    """
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            audience=config['audience'],
            issuer=config['issuer'],
        )
        return claims
    except jwt.ExpiredSignatureError:
        logger.warning('JWT token has expired')
    except jwt.InvalidAudienceError:
        logger.warning('JWT token has invalid audience')
    except jwt.InvalidIssuerError:
        logger.warning('JWT token has invalid issuer')
    except jwt.InvalidTokenError as e:
        logger.warning(f'JWT token validation failed: {e}')
    return None


def decode_claims_unverified(jwt_token: str) -> dict[str, Any] | None:
    """Read a JWT's claims without verifying it.

    Only for tokens the auth middleware has already verified; it re-parses the
    same string to read claims the AccessToken does not carry.
    """
    try:
        return jwt.decode(
            jwt_token,
            options={
                'verify_signature': False,
                'verify_aud': False,
                'verify_iss': False,
                'verify_exp': False,
            },
        )
    except Exception as e:
        logger.error(f'JWT decode failed: {e}')
        return None


def get_token_workspaces(jwt_token: str) -> list[dict[str, str]]:
    """List the workspaces a verified JWT grants access to.

    Resolves the Auth0 namespace from AUTH0_NAMESPACE, so callers do not have
    to know how the claim key is built.
    """
    return get_token_workspaces_with_dropped(jwt_token)[0]


def get_token_workspaces_with_dropped(
    jwt_token: str,
) -> tuple[list[dict[str, str]], int]:
    """The same list, paired with how many claim entries were dropped as unusable.

    Only `list_workspaces` needs the count: it enumerates workspaces for an
    agent, which cannot otherwise tell a short list from a complete one.
    """
    claims = decode_claims_unverified(jwt_token)
    if not claims:
        return [], 0

    namespace = os.getenv('AUTH0_NAMESPACE', 'https://alpacon.io/').rstrip('/') + '/'
    return _partition_workspaces(claims, namespace)


def extract_workspaces(claims: dict[str, Any], namespace: str) -> list[dict[str, str]]:
    """Extract the usable workspaces from JWT claims.

    An entry is dropped unless it names both a workspace and a region as
    non-blank strings: every caller walks the list as workspace dicts, so half
    an entry either crashes one or lists a workspace with an empty name.

    Args:
        claims: Decoded JWT claims
        namespace: Auth0 namespace prefix (e.g. 'https://alpacon.io/')

    Returns:
        List of workspace dicts with schema_name, auth0_id, region
    """
    return _partition_workspaces(claims, namespace)[0]


def _partition_workspaces(
    claims: dict[str, Any], namespace: str
) -> tuple[list[dict[str, str]], int]:
    """Split the workspaces claim into the usable entries and a count of the rest.

    A claim that is not a list at all holds no entries, so it drops nothing.
    """
    # Ensure namespace ends with '/' to build correct claim key
    if namespace and not namespace.endswith('/'):
        namespace = namespace + '/'
    claim_key = f'{namespace}workspaces'
    workspaces = claims.get(claim_key, [])
    if not isinstance(workspaces, list):
        logger.warning(f'Invalid workspaces claim type: {type(workspaces)}')
        return [], 0

    usable = []
    dropped = 0
    for entry in workspaces:
        if not isinstance(entry, dict):
            logger.warning(
                f'Dropping workspaces claim entry: expected an object, '
                f'got {type(entry).__name__}'
            )
            dropped += 1
            continue
        # Only the field names reach the log: nothing here controls what else
        # the Auth0 Action puts in an entry.
        blank = [
            field
            for field in ('schema_name', 'region')
            if not (isinstance(entry.get(field), str) and entry[field].strip())
        ]
        if blank:
            logger.warning(
                f'Dropping workspaces claim entry: {", ".join(blank)} missing or blank'
            )
            dropped += 1
            continue
        usable.append(entry)
    return usable, dropped


def match_workspace(
    workspaces: list[dict[str, str]], region: str, workspace: str
) -> bool:
    """Check if a workspace/region pair is authorized by JWT claims.

    Args:
        workspaces: List of workspace dicts from JWT claims
        region: Region to match (e.g. 'ap1')
        workspace: Workspace name to match (schema_name)

    Returns:
        True if the workspace/region pair is found in claims
    """
    return any(
        ws.get('schema_name') == workspace and ws.get('region') == region
        for ws in workspaces
    )


class Auth0TokenVerifier:
    """Auth0 JWT token verifier implementing FastMCP's TokenVerifier protocol.

    Verifies RS256-signed JWTs using Auth0's JWKS endpoint and extracts
    workspace claims for authorization.
    """

    def __init__(self):
        """Initialize with Auth0 config from environment variables."""
        self._config = _get_auth0_config()
        logger.info(
            f'Auth0TokenVerifier initialized - '
            f'domain: {self._config["domain"]}, '
            f'audience: {self._config["audience"]}'
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a Bearer token and return access info if valid.

        Implements the TokenVerifier protocol for FastMCP integration.

        Args:
            token: Raw JWT string from Authorization header

        Returns:
            AccessToken with JWT info, or None if invalid
        """
        try:
            # Fetch JWKS and find signing key
            jwks = await _fetch_jwks(self._config['jwks_url'])
            public_key = _get_signing_key(jwks, token)
            if public_key is None and _has_kid(token):
                # The cached keys may predate an Auth0 key rotation: read them
                # once more before rejecting a kid they do not know.
                logger.info('Unknown kid in cached JWKS, forcing a refetch')
                jwks = await _fetch_jwks(self._config['jwks_url'], force=True)
                public_key = _get_signing_key(jwks, token)
            if not public_key:
                return None

            # Decode and verify JWT
            claims = decode_jwt(token, public_key, self._config)
            if not claims:
                return None

            # Extract workspace info for logging
            workspaces = extract_workspaces(claims, self._config['namespace'])
            ws_names = [ws.get('schema_name', '?') for ws in workspaces]
            logger.info(
                f'JWT verified - sub: {claims.get("sub")}, workspaces: {ws_names}'
            )

            return AccessToken(
                token=token,
                client_id=claims.get('sub', 'unknown'),
                scopes=claims.get('scope', '').split() if claims.get('scope') else [],
                expires_at=claims.get('exp'),
            )

        except ValueError as e:
            logger.error(f'Auth0 configuration error: {e}')
            return None
        except httpx.HTTPError as e:
            logger.error(f'Failed to fetch JWKS: {e}')
            return None
        except Exception as e:
            logger.error(f'Unexpected error during token verification: {e}')
            return None
