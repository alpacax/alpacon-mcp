"""Tests for keys, signed state, device ids, sealed grants, and the nonce."""

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest

from tests.oauth._support import (
    DEVICE_ID,
    EVIL_REDIRECT_URI,
    OTHER_DEVICE_ID,
    TEST_CLIENT_SECRET,
    TRUSTED_REDIRECT_URI,
    MockMCPServer,
    _forge_state_under_valid_signature,
)
from utils.oauth import register_oauth_routes
from utils.oauth._sealing import (
    _GRANT_SECRET_ENV,
    _GRANT_SECRET_INFO,
    _NONCE_COOKIE_NAME,
    _STATE_SECRET_ENV,
    _STATE_SECRET_INFO,
    _STATE_TTL_SECONDS,
    _build_state,
    _get_grant_secret,
    _get_state_secret,
    _hash_nonce,
    _mint_device_id,
    _mint_nonce,
    _seal_code,
    _seal_refresh_token,
    _sign_state,
    _unseal_code,
    _unseal_refresh_token,
    _verify_state,
)


class TestStateSecret:
    """Tests for state signing key derivation."""

    def test_explicit_env_secret_wins(self):
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'a1' * 32}):
            assert _get_state_secret() == b'\xa1' * 32

    def test_rejects_non_hex_explicit_secret(self):
        # A typed passphrase is the weak key this check exists to keep out.
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'correct-horse-battery'}):
            with pytest.raises(ValueError, match='must be hex'):
                _get_state_secret()

    def test_rejects_short_explicit_secret(self):
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'a1' * 31}):
            with pytest.raises(ValueError, match='at least 32 bytes'):
                _get_state_secret()

    def test_derives_from_client_secret_when_env_unset(self):
        expected = hmac.new(
            TEST_CLIENT_SECRET.encode(), _STATE_SECRET_INFO, hashlib.sha256
        ).digest()
        assert _get_state_secret() == expected

    def test_derived_secret_is_deterministic(self):
        assert _get_state_secret() == _get_state_secret()

    def test_registration_logs_state_secret_source(self, caplog):
        with caplog.at_level('INFO'):
            register_oauth_routes(MockMCPServer())

        assert 'derived from client secret' in caplog.text

    def test_registration_rejects_malformed_explicit_secret(self):
        """A bad key fails the boot rather than the first user's OAuth request."""
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'correct-horse-battery'}):
            with pytest.raises(ValueError, match='must be hex'):
                register_oauth_routes(MockMCPServer())

    def test_registration_survives_incomplete_oauth_config(self):
        """Without an explicit key the check stays off, so a deployment that
        starts with OAuth unconfigured keeps starting."""
        with patch.dict(
            'os.environ', {_STATE_SECRET_ENV: '', 'AUTH0_CLIENT_SECRET': ''}
        ):
            register_oauth_routes(MockMCPServer())


class TestGrantSecret:
    """The key under which codes and refresh tokens are sealed."""

    def test_explicit_env_secret_wins(self):
        with patch.dict('os.environ', {_GRANT_SECRET_ENV: 'b2' * 32}):
            assert _get_grant_secret() == b'\xb2' * 32

    def test_rejects_non_hex_explicit_secret(self):
        with patch.dict('os.environ', {_GRANT_SECRET_ENV: 'correct-horse-battery'}):
            with pytest.raises(ValueError, match='must be hex'):
                _get_grant_secret()

    def test_rejects_short_explicit_secret(self):
        with patch.dict('os.environ', {_GRANT_SECRET_ENV: 'b2' * 31}):
            with pytest.raises(ValueError, match='at least 32 bytes'):
                _get_grant_secret()

    def test_derives_from_client_secret_when_env_unset(self):
        expected = hmac.new(
            TEST_CLIENT_SECRET.encode(), _GRANT_SECRET_INFO, hashlib.sha256
        ).digest()
        assert _get_grant_secret() == expected

    def test_differs_from_the_state_secret(self):
        """A state key that leaks must not also mint refresh tokens."""
        assert _get_grant_secret() != _get_state_secret()

    def test_registration_rejects_malformed_explicit_secret(self):
        with patch.dict('os.environ', {_GRANT_SECRET_ENV: 'correct-horse-battery'}):
            with pytest.raises(ValueError, match='must be hex'):
                register_oauth_routes(MockMCPServer())


class TestMintedDeviceId:
    def test_mint_is_unpredictable(self):
        """The per-grant property rests on the CSPRNG, not on a call count.

        Every other minting test patches `_mint_device_id`, so this is the one
        that would fail if its body became a constant.
        """
        assert _mint_device_id() != _mint_device_id()


class TestSealedGrants:
    """Codes and refresh tokens carry their device id under this server's seal."""

    def test_code_round_trips(self):
        assert _unseal_code(_seal_code('auth-code', DEVICE_ID)) == (
            'auth-code',
            DEVICE_ID,
        )

    def test_refresh_token_round_trips(self):
        sealed = _seal_refresh_token('v1.refresh', DEVICE_ID)
        assert _unseal_refresh_token(sealed) == ('v1.refresh', DEVICE_ID)

    def test_a_sealed_code_is_not_a_refresh_token(self):
        assert _unseal_refresh_token(_seal_code('auth-code', DEVICE_ID)) is None

    def test_a_sealed_refresh_token_is_not_a_code(self):
        assert _unseal_code(_seal_refresh_token('v1.refresh', DEVICE_ID)) is None

    def test_tampered_device_id_is_rejected(self):
        sealed = _seal_refresh_token('v1.refresh', DEVICE_ID)
        prefix, _, signature = sealed.split('.')
        forged = base64.urlsafe_b64encode(
            json.dumps(
                {'k': 'refresh', 'v': 'v1.refresh', 'd': OTHER_DEVICE_ID}
            ).encode()
        ).decode()
        assert _unseal_refresh_token(f'{prefix}.{forged}.{signature}') is None

    def test_state_key_cannot_mint_a_grant(self):
        """Sealing must not verify under the state key, or the two keys are one."""
        sealed = _seal_refresh_token('v1.refresh', DEVICE_ID)
        prefix, encoded, _ = sealed.split('.')
        under_state_key = base64.urlsafe_b64encode(
            hmac.new(
                _get_state_secret(), f'{prefix}.{encoded}'.encode(), hashlib.sha256
            ).digest()
        ).decode()
        assert _unseal_refresh_token(f'{prefix}.{encoded}.{under_state_key}') is None

    def test_bare_values_are_not_sealed(self):
        assert _unseal_refresh_token('v1.Mc-plain-auth0-token') is None
        assert _unseal_code('plain-auth0-code') is None

    def test_non_string_values_are_not_sealed(self):
        """A JSON body can carry any type; none of them is a seal."""
        assert _unseal_code(123) is None
        assert _unseal_refresh_token(None) is None
        assert _unseal_refresh_token(['v1.refresh']) is None


class TestNonceHelpers:
    """Tests for the per-flow nonce that binds a state to one browser."""

    def test_mint_nonce_differs_every_call(self):
        assert _mint_nonce() != _mint_nonce()

    def test_mint_nonce_is_long_enough_to_resist_guessing(self):
        assert len(_mint_nonce()) >= 32

    def test_hash_nonce_is_stable_for_the_same_input(self):
        assert _hash_nonce('abc') == _hash_nonce('abc')

    def test_hash_nonce_differs_for_different_input(self):
        assert _hash_nonce('abc') != _hash_nonce('abd')

    def test_hash_nonce_is_base64url_sha256(self):
        expected = base64.urlsafe_b64encode(hashlib.sha256(b'abc').digest()).decode()
        assert _hash_nonce('abc') == expected

    def test_nonce_cookie_name_carries_the_host_prefix(self):
        assert _NONCE_COOKIE_NAME == '__Host-alpacon_oauth_nonce'


class TestStateEnvelope:
    """Tests for state signing and verification."""

    def test_round_trip_preserves_payload(self):
        signed = _sign_state({'redirect_uri': TRUSTED_REDIRECT_URI, 'state': 'xyz'})
        payload = _verify_state(signed)
        assert payload['redirect_uri'] == TRUSTED_REDIRECT_URI
        assert payload['state'] == 'xyz'

    def test_sign_adds_expiry(self):
        payload = _verify_state(_sign_state({'state': 'xyz'}))
        assert payload['exp'] <= int(time.time()) + _STATE_TTL_SECONDS

    def test_tampered_payload_is_rejected(self):
        assert _verify_state(_forge_state_under_valid_signature()) is None

    def test_unsigned_state_is_rejected(self):
        unsigned = base64.urlsafe_b64encode(
            json.dumps({'redirect_uri': EVIL_REDIRECT_URI}).encode()
        ).decode()
        assert _verify_state(unsigned) is None

    def test_wrong_signature_is_rejected(self):
        encoded, _, _ = _sign_state({'state': 'xyz'}).rpartition('.')
        assert _verify_state(f'{encoded}.bm90LWEtc2ln') is None

    def test_expired_state_is_rejected(self):
        with patch('utils.oauth._sealing.time.time', return_value=1000):
            signed = _sign_state({'state': 'xyz'})
        with patch('utils.oauth._sealing.time.time', return_value=99999999):
            assert _verify_state(signed) is None

    def test_malformed_state_is_rejected(self):
        assert _verify_state('not-a-state') is None
        assert _verify_state('') is None

    def test_non_ascii_state_is_rejected(self):
        """hmac.compare_digest raises TypeError on non-ASCII str, so compare bytes."""
        assert _verify_state('payload.서명') is None


class TestBuildState:
    """Tests for state payload assembly."""

    def test_carries_redirect_uri_and_client_state(self):
        decoded = _verify_state(_build_state(TRUSTED_REDIRECT_URI, 'xyz'))
        assert decoded['redirect_uri'] == TRUSTED_REDIRECT_URI
        assert decoded['state'] == 'xyz'

    def test_carries_extra_flow_fields(self):
        decoded = _verify_state(
            _build_state('', '', stage='mfa', original_scope='openid')
        )
        assert decoded['stage'] == 'mfa'
        assert decoded['original_scope'] == 'openid'
