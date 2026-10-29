"""Auth0 JWT verification for remote MCP server mode."""

import asyncio
import json
import time
from collections.abc import Mapping
from typing import NotRequired, TypedDict

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from mcp.server.auth.provider import AccessToken

from utils.auth0_env import get_auth0_env
from utils.ledger_grant import (
    LedgerGrant,
    is_wrapped_access_token,
    ledger_claims,
    unwrap_access_token,
)
from utils.logger import escape_for_log, get_logger
from utils.oauth import ledger_grant_key
from utils.types import JsonValue

logger = get_logger('auth')

type JwtClaims = dict[str, JsonValue]  # a decoded JWT payload


class WorkspaceClaim(TypedDict):  # one usable entry of the workspaces claim
    schema_name: str
    region: str
    auth0_id: NotRequired[str]


# JWKS cache: stores fetched keys and expiry time
_jwks_cache: dict[str, JsonValue] = {}
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
    global _jwks_lock
    if _jwks_lock is None:
        _jwks_lock = asyncio.Lock()
    return _jwks_lock


def _get_auth0_config() -> dict[str, str]:
    """Read the Auth0 settings from the environment; raises ValueError when
    AUTH0_ALPACON_DOMAIN (or the old AUTH0_DOMAIN) is unset."""
    domain = get_auth0_env('AUTH0_ALPACON_DOMAIN', '')
    audience = get_auth0_env(
        'AUTH0_ALPACON_USER_AUDIENCE', 'https://alpacon.io/access/'
    )
    namespace = (
        get_auth0_env('AUTH0_ALPACON_NAMESPACE', 'https://alpacon.io/').rstrip('/')
        + '/'
    )

    if not domain:
        raise ValueError('AUTH0_ALPACON_DOMAIN environment variable is required')

    return {
        'domain': domain,
        'audience': audience,
        'namespace': namespace,
        'issuer': f'https://{domain}/',
        'jwks_url': f'https://{domain}/.well-known/jwks.json',
    }


async def _fetch_jwks(jwks_url: str, *, force: bool = False) -> dict[str, JsonValue]:
    """Fetch the JWKS under a lock, cached for an hour. A force fetch is skipped (cache
    returned) within the cooldown of the last forced one."""
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
            elapsed = now - _jwks_last_forced_fetch
            if elapsed < _JWKS_FORCED_FETCH_COOLDOWN:
                remaining = _JWKS_FORCED_FETCH_COOLDOWN - elapsed
                logger.info(
                    'Skipping forced JWKS fetch: cooldown active (%.0fs remaining)',
                    remaining,
                )
                return _jwks_cache
            _jwks_last_forced_fetch = now

        logger.info('Fetching JWKS from %s', jwks_url)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_expiry = now + _JWKS_CACHE_TTL

        keys = _jwks_cache.get('keys')
        logger.info('JWKS fetched: %s keys', len(keys) if isinstance(keys, list) else 0)
        return _jwks_cache


def _has_kid(token: str) -> bool:
    try:
        return bool(jwt.get_unverified_header(token).get('kid'))
    except jwt.exceptions.DecodeError:
        return False


def _get_signing_key(
    jwks: Mapping[str, JsonValue], token: str, *, quiet_miss: bool = False
) -> RSAPublicKey | None:
    """The RSA key matching the token's kid, or None. quiet_miss logs a kid miss at
    info, for callers about to retry on a forced refetch."""
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError as e:
        logger.error('Failed to decode JWT header: %s', escape_for_log(e))
        return None

    kid = unverified_header.get('kid')
    if not kid:
        logger.error('JWT header missing kid')
        return None

    keys = jwks.get('keys')
    for key in keys if isinstance(keys, list) else []:
        if isinstance(key, dict) and key.get('kid') == kid:
            rsa_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
            if isinstance(rsa_key, RSAPublicKey):
                return rsa_key
            logger.error('JWKS key for kid %s is not a public key', escape_for_log(kid))
            return None

    if quiet_miss:
        logger.info('No matching key for kid in cached JWKS: %s', escape_for_log(kid))
    else:
        logger.error('No matching key found for kid: %s', escape_for_log(kid))
    return None


def decode_jwt(
    token: str, public_key: RSAPublicKey, config: dict[str, str]
) -> JwtClaims | None:
    """Decode and verify a JWT as RS256 against the audience and issuer; None when
    verification fails."""
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
        logger.warning('JWT token validation failed: %s', escape_for_log(e))
    return None


def decode_claims_unverified(jwt_token: str) -> JwtClaims | None:
    """Read a JWT's claims without verifying it; the caller must already trust the
    token, as one the auth middleware verified or this process obtained itself."""
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
        logger.error('JWT decode failed: %s', escape_for_log(e))
        return None


def get_token_workspaces(jwt_token: str) -> list[WorkspaceClaim]:
    """List the workspaces a verified JWT grants; the claim key comes from
    AUTH0_ALPACON_NAMESPACE."""
    return get_token_workspaces_with_dropped(jwt_token)[0]


def get_token_workspaces_with_dropped(
    jwt_token: str,
) -> tuple[list[WorkspaceClaim], int]:
    """The same list, paired with the count of claim entries dropped as unusable, so
    list_workspaces can flag a short list."""
    claims = decode_claims_unverified(jwt_token)
    if not claims:
        return [], 0

    namespace = (
        get_auth0_env('AUTH0_ALPACON_NAMESPACE', 'https://alpacon.io/').rstrip('/')
        + '/'
    )
    return _partition_workspaces(claims, namespace)


def extract_workspaces(
    claims: Mapping[str, object], namespace: str
) -> list[WorkspaceClaim]:
    """Usable workspaces from the claims: an entry needs non-blank string schema_name
    and region, else it is dropped."""
    return _partition_workspaces(claims, namespace)[0]


def _partition_workspaces(
    claims: Mapping[str, object], namespace: str
) -> tuple[list[WorkspaceClaim], int]:
    """Split the workspaces claim into usable entries and a count of the dropped; a
    non-list claim drops nothing."""
    # Ensure namespace ends with '/' to build correct claim key
    if namespace and not namespace.endswith('/'):
        namespace = namespace + '/'
    claim_key = f'{namespace}workspaces'
    workspaces = claims.get(claim_key, [])
    if not isinstance(workspaces, list):
        logger.warning('Invalid workspaces claim type: %s', type(workspaces))
        return [], 0

    usable: list[WorkspaceClaim] = []
    dropped = 0
    for entry in workspaces:
        if not isinstance(entry, dict):
            logger.warning(
                'Dropping workspaces claim entry: expected an object, got %s',
                type(entry).__name__,
            )
            dropped += 1
            continue
        # Only the field names reach the log: nothing here controls what else
        # the Auth0 Action puts in an entry.
        schema_name, region = entry.get('schema_name'), entry.get('region')
        if (
            isinstance(schema_name, str)
            and schema_name.strip()
            and isinstance(region, str)
            and region.strip()
        ):
            claim: WorkspaceClaim = {'schema_name': schema_name, 'region': region}
            auth0_id = entry.get('auth0_id')
            if isinstance(auth0_id, str):
                claim['auth0_id'] = auth0_id
            usable.append(claim)
            continue
        blank = [
            field
            for field, value in (('schema_name', schema_name), ('region', region))
            if not (isinstance(value, str) and value.strip())
        ]
        logger.warning(
            'Dropping workspaces claim entry: %s missing or blank', ', '.join(blank)
        )
        dropped += 1
    return usable, dropped


def match_workspace(
    workspaces: list[WorkspaceClaim], region: str, workspace: str
) -> bool:
    """True when the claims authorize this workspace (schema_name) and region pair."""
    return any(
        ws.get('schema_name') == workspace and ws.get('region') == region
        for ws in workspaces
    )


class Auth0TokenVerifier:
    """Auth0 JWT verifier for the SDK's TokenVerifier protocol: RS256 via JWKS, with
    workspace claims."""

    def __init__(self) -> None:
        """Load the Auth0 config from the environment; raises ValueError when
        AUTH0_DOMAIN is unset."""
        self._config = _get_auth0_config()
        logger.info(
            'Auth0TokenVerifier initialized - domain: %s, audience: %s',
            self._config['domain'],
            self._config['audience'],
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """AccessToken for a valid Bearer token, else None on any failure; an unknown
        kid forces one JWKS refetch."""
        try:
            # A credential this server wrapped carries a ledger grant beside
            # the Auth0 token; everything below verifies the Auth0 token alone.
            grant: LedgerGrant | None = None
            if is_wrapped_access_token(token):
                unwrapped = unwrap_access_token(ledger_grant_key(), token)
                if unwrapped is None:
                    logger.warning('Rejected a wrapped access token that did not open')
                    return None
                token, grant = unwrapped

            # Fetch JWKS and find signing key
            jwks = await _fetch_jwks(self._config['jwks_url'])
            public_key = _get_signing_key(jwks, token, quiet_miss=True)
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
                'JWT verified - sub: %s, workspaces: %s',
                escape_for_log(claims.get('sub')),
                ws_names,
            )

            sub = claims.get('sub', 'unknown')
            scope = claims.get('scope', '')
            exp = claims.get('exp')
            # Refused rather than coerced: a wrong type here failed AccessToken before.
            if not (
                isinstance(sub, str)
                and isinstance(scope, str)
                and (exp is None or isinstance(exp, int))
            ):
                logger.warning('JWT sub, scope or exp claim has an unexpected type')
                return None
            if grant is not None and not grant.is_failure and grant.subject != sub:
                # Wrapped together at sign-in, so a mismatch is not this
                # server's doing; the session goes on without the ledger.
                logger.warning(
                    'Dropped a ledger grant whose subject is not the session'
                )
                grant = None
            return AccessToken(
                token=token,
                client_id=sub,
                scopes=scope.split(),
                expires_at=exp,
                claims=ledger_claims(grant) if grant is not None else None,
            )

        except ValueError as e:
            logger.error('Auth0 configuration error: %s', e)
            return None
        except httpx.HTTPError as e:
            logger.error('Failed to fetch JWKS: %s', e)
            return None
        except Exception as e:
            logger.error('Unexpected error during token verification: %s', e)
            return None
