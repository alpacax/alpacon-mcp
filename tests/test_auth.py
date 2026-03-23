"""
Unit tests for Auth0 JWT verification.

Tests Auth0TokenVerifier including JWKS fetching, signing key selection,
and token verification (valid, expired, invalid kid, audience mismatch).
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest

AUTH_ENV = {
    'AUTH0_DOMAIN': 'test.us.auth0.com',
    'AUTH0_AUDIENCE': 'https://alpacon.io/',
}


def _generate_rsa_keypair():
    """Generate an RSA key pair for testing."""
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod

    private_key = rsa_mod.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key


def _make_jwk(private_key, kid='test-kid-1'):
    """Create a JWK dict from an RSA key pair (public key only, as in real JWKS)."""
    from jwt.algorithms import RSAAlgorithm

    # JWKS endpoints only expose public keys
    public_key = private_key.public_key()
    jwk_json = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk_json['kid'] = kid
    jwk_json['use'] = 'sig'
    jwk_json['alg'] = 'RS256'
    return jwk_json


def _make_token(private_key, kid='test-kid-1', claims=None, expired=False):
    """Create a signed JWT for testing."""
    now = int(time.time())
    default_claims = {
        'sub': 'auth0|test-user',
        'aud': 'https://alpacon.io/',
        'iss': 'https://test.us.auth0.com/',
        'iat': now,
        'exp': now - 3600 if expired else now + 3600,
        'scope': 'openid profile',
        'https://alpacon.io/workspaces': [
            {'schema_name': 'test-ws', 'region': 'ap1', 'auth0_id': 'org_123'},
        ],
    }
    if claims:
        default_claims.update(claims)

    return pyjwt.encode(
        default_claims,
        private_key,
        algorithm='RS256',
        headers={'kid': kid},
    )


@pytest.fixture
def rsa_keypair():
    """Generate a fresh RSA key pair."""
    return _generate_rsa_keypair()


@pytest.fixture
def jwks_response(rsa_keypair):
    """Create a JWKS response containing the test key."""
    jwk = _make_jwk(rsa_keypair)
    return {'keys': [jwk]}


@pytest.fixture(autouse=True)
def _reset_jwks_cache():
    """Reset JWKS cache between tests."""
    import utils.auth as auth_mod

    auth_mod._jwks_cache = {}
    auth_mod._jwks_cache_expiry = 0
    auth_mod._jwks_lock = None
    yield
    auth_mod._jwks_cache = {}
    auth_mod._jwks_cache_expiry = 0
    auth_mod._jwks_lock = None


class TestGetSigningKey:
    """Tests for _get_signing_key function."""

    def test_returns_key_for_matching_kid(self, rsa_keypair, jwks_response):
        from utils.auth import _get_signing_key

        token = _make_token(rsa_keypair, kid='test-kid-1')
        key = _get_signing_key(jwks_response, token)
        assert key is not None

    def test_returns_none_for_missing_kid(self, rsa_keypair, jwks_response):
        from utils.auth import _get_signing_key

        token = _make_token(rsa_keypair, kid='nonexistent-kid')
        key = _get_signing_key(jwks_response, token)
        assert key is None

    def test_returns_none_for_invalid_token(self, jwks_response):
        from utils.auth import _get_signing_key

        key = _get_signing_key(jwks_response, 'not-a-jwt')
        assert key is None


class TestDecodeJwt:
    """Tests for decode_jwt function."""

    def test_decodes_valid_token(self, rsa_keypair, jwks_response):
        from utils.auth import _get_signing_key, decode_jwt

        token = _make_token(rsa_keypair)
        public_key = _get_signing_key(jwks_response, token)
        config = {
            'audience': ['https://alpacon.io/', 'https://alpacon.io/access/'],
            'issuer': 'https://test.us.auth0.com/',
        }
        claims = decode_jwt(token, public_key, config)
        assert claims is not None
        assert claims['sub'] == 'auth0|test-user'

    def test_decodes_token_with_old_audience(self, rsa_keypair, jwks_response):
        """Tokens with the old audience should still be accepted."""
        from utils.auth import _get_signing_key, decode_jwt

        token = _make_token(
            rsa_keypair, claims={'aud': 'https://alpacon.io/access/'}
        )
        public_key = _get_signing_key(jwks_response, token)
        config = {
            'audience': ['https://alpacon.io/', 'https://alpacon.io/access/'],
            'issuer': 'https://test.us.auth0.com/',
        }
        claims = decode_jwt(token, public_key, config)
        assert claims is not None
        assert claims['sub'] == 'auth0|test-user'

    def test_returns_none_for_expired_token(self, rsa_keypair, jwks_response):
        from utils.auth import _get_signing_key, decode_jwt

        token = _make_token(rsa_keypair, expired=True)
        public_key = _get_signing_key(jwks_response, token)
        config = {
            'audience': ['https://alpacon.io/', 'https://alpacon.io/access/'],
            'issuer': 'https://test.us.auth0.com/',
        }
        claims = decode_jwt(token, public_key, config)
        assert claims is None

    def test_returns_none_for_wrong_audience(self, rsa_keypair, jwks_response):
        from utils.auth import _get_signing_key, decode_jwt

        token = _make_token(rsa_keypair)
        public_key = _get_signing_key(jwks_response, token)
        config = {
            'audience': 'https://wrong-audience.com/',
            'issuer': 'https://test.us.auth0.com/',
        }
        claims = decode_jwt(token, public_key, config)
        assert claims is None

    def test_returns_none_for_wrong_issuer(self, rsa_keypair, jwks_response):
        from utils.auth import _get_signing_key, decode_jwt

        token = _make_token(rsa_keypair)
        public_key = _get_signing_key(jwks_response, token)
        config = {
            'audience': ['https://alpacon.io/', 'https://alpacon.io/access/'],
            'issuer': 'https://wrong-issuer.com/',
        }
        claims = decode_jwt(token, public_key, config)
        assert claims is None


class TestExtractWorkspaces:
    """Tests for extract_workspaces function."""

    def test_extracts_workspaces(self):
        from utils.auth import extract_workspaces

        claims = {
            'https://alpacon.io/workspaces': [
                {'schema_name': 'ws1', 'region': 'ap1'},
            ]
        }
        result = extract_workspaces(claims, 'https://alpacon.io/')
        assert len(result) == 1
        assert result[0]['schema_name'] == 'ws1'

    def test_normalizes_namespace_without_trailing_slash(self):
        from utils.auth import extract_workspaces

        claims = {
            'https://alpacon.io/workspaces': [
                {'schema_name': 'ws1', 'region': 'ap1'},
            ]
        }
        result = extract_workspaces(claims, 'https://alpacon.io')
        assert len(result) == 1

    def test_returns_empty_for_missing_claim(self):
        from utils.auth import extract_workspaces

        result = extract_workspaces({}, 'https://alpacon.io/')
        assert result == []


class TestMatchWorkspace:
    """Tests for match_workspace function."""

    def test_matches_valid_workspace(self):
        from utils.auth import match_workspace

        workspaces = [{'schema_name': 'prod', 'region': 'ap1'}]
        assert match_workspace(workspaces, 'ap1', 'prod') is True

    def test_rejects_wrong_workspace(self):
        from utils.auth import match_workspace

        workspaces = [{'schema_name': 'prod', 'region': 'ap1'}]
        assert match_workspace(workspaces, 'ap1', 'staging') is False

    def test_rejects_wrong_region(self):
        from utils.auth import match_workspace

        workspaces = [{'schema_name': 'prod', 'region': 'ap1'}]
        assert match_workspace(workspaces, 'us1', 'prod') is False


class TestAuth0TokenVerifier:
    """Tests for Auth0TokenVerifier.verify_token."""

    @pytest.mark.asyncio
    async def test_verify_valid_token(self, rsa_keypair, jwks_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = jwks_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        token = _make_token(rsa_keypair)

        with patch.dict('os.environ', AUTH_ENV):
            with patch('utils.auth.httpx.AsyncClient', return_value=mock_client):
                from utils.auth import Auth0TokenVerifier

                verifier = Auth0TokenVerifier()
                result = await verifier.verify_token(token)

        assert result is not None
        assert result.client_id == 'auth0|test-user'
        assert result.token == token

    @pytest.mark.asyncio
    async def test_verify_expired_token_returns_none(self, rsa_keypair, jwks_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = jwks_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        token = _make_token(rsa_keypair, expired=True)

        with patch.dict('os.environ', AUTH_ENV):
            with patch('utils.auth.httpx.AsyncClient', return_value=mock_client):
                from utils.auth import Auth0TokenVerifier

                verifier = Auth0TokenVerifier()
                result = await verifier.verify_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_verify_invalid_kid_returns_none(self, rsa_keypair, jwks_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = jwks_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Sign with a kid that doesn't exist in JWKS
        token = _make_token(rsa_keypair, kid='wrong-kid')

        with patch.dict('os.environ', AUTH_ENV):
            with patch('utils.auth.httpx.AsyncClient', return_value=mock_client):
                from utils.auth import Auth0TokenVerifier

                verifier = Auth0TokenVerifier()
                result = await verifier.verify_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_verify_wrong_audience_returns_none(self, rsa_keypair, jwks_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = jwks_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Token with wrong audience
        token = _make_token(rsa_keypair, claims={'aud': 'https://wrong-audience.com/'})

        with patch.dict('os.environ', AUTH_ENV):
            with patch('utils.auth.httpx.AsyncClient', return_value=mock_client):
                from utils.auth import Auth0TokenVerifier

                verifier = Auth0TokenVerifier()
                result = await verifier.verify_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_verify_jwks_fetch_failure_returns_none(self, rsa_keypair):
        import httpx

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError('Connection refused')
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        token = _make_token(rsa_keypair)

        with patch.dict('os.environ', AUTH_ENV):
            with patch('utils.auth.httpx.AsyncClient', return_value=mock_client):
                from utils.auth import Auth0TokenVerifier

                verifier = Auth0TokenVerifier()
                result = await verifier.verify_token(token)

        assert result is None


class TestJwksCaching:
    """Tests for JWKS caching behavior."""

    @pytest.mark.asyncio
    async def test_caches_jwks_response(self, jwks_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = jwks_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('utils.auth.httpx.AsyncClient', return_value=mock_client):
            from utils.auth import _fetch_jwks

            # First call fetches
            result1 = await _fetch_jwks(
                'https://test.us.auth0.com/.well-known/jwks.json'
            )
            # Second call uses cache
            result2 = await _fetch_jwks(
                'https://test.us.auth0.com/.well-known/jwks.json'
            )

        assert result1 == result2
        # Only one HTTP call should have been made
        assert mock_client.get.call_count == 1
