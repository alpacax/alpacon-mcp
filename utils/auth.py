"""Auth0 JWT verification for remote MCP server mode."""

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


def _get_auth0_config() -> dict[str, str]:
    """Get Auth0 configuration from environment variables."""
    domain = os.getenv('AUTH0_DOMAIN', '')
    audience = os.getenv('AUTH0_AUDIENCE', 'https://alpacon.io/access/')
    namespace = os.getenv('AUTH0_NAMESPACE', 'https://alpacon.io/')

    if not domain:
        raise ValueError('AUTH0_DOMAIN environment variable is required')

    return {
        'domain': domain,
        'audience': audience,
        'namespace': namespace,
        'issuer': f'https://{domain}/',
        'jwks_url': f'https://{domain}/.well-known/jwks.json',
    }


async def _fetch_jwks(jwks_url: str) -> dict[str, Any]:
    """Fetch JWKS from Auth0 endpoint with caching."""
    global _jwks_cache, _jwks_cache_expiry

    now = time.time()
    if _jwks_cache and now < _jwks_cache_expiry:
        return _jwks_cache

    logger.info(f'Fetching JWKS from {jwks_url}')
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_expiry = now + _JWKS_CACHE_TTL

    logger.info(f'JWKS fetched: {len(_jwks_cache.get("keys", []))} keys')
    return _jwks_cache


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
            import json

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


def extract_workspaces(claims: dict[str, Any], namespace: str) -> list[dict[str, str]]:
    """Extract workspaces from JWT claims.

    Args:
        claims: Decoded JWT claims
        namespace: Auth0 namespace prefix (e.g. 'https://alpacon.io/')

    Returns:
        List of workspace dicts with schema_name, auth0_id, region
    """
    claim_key = f'{namespace}workspaces'
    workspaces = claims.get(claim_key, [])
    if not isinstance(workspaces, list):
        logger.warning(f'Invalid workspaces claim type: {type(workspaces)}')
        return []
    return workspaces


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
