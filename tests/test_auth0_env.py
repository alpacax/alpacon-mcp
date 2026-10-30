"""Auth0 environment names and their compatibility behavior."""

import hashlib
import hmac
import logging
from unittest.mock import patch

import pytest

from utils import auth0_env
from utils.auth import _get_auth0_config, get_token_workspaces_with_dropped
from utils.auth0_env import get_auth0_env
from utils.oauth import (
    _GRANT_SECRET_INFO,
    _STATE_SECRET_INFO,
    _get_grant_secret,
    _get_oauth_config,
    _get_state_secret,
)

ENV_NAMES = [
    ('AUTH0_ALPACON_DOMAIN', 'AUTH0_DOMAIN'),
    ('AUTH0_ALPACON_LOGIN_CLIENT_ID', 'AUTH0_CLIENT_ID'),
    ('AUTH0_ALPACON_LOGIN_CLIENT_SECRET', 'AUTH0_CLIENT_SECRET'),
    ('AUTH0_ALPACON_USER_AUDIENCE', 'AUTH0_AUDIENCE'),
    ('AUTH0_ALPACON_MFA_AUDIENCE', 'AUTH0_MFA_AUDIENCE'),
    ('AUTH0_ALPACON_NAMESPACE', 'AUTH0_NAMESPACE'),
]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    monkeypatch.setattr(auth0_env, '_warned_legacy_names', set())
    with patch.dict('os.environ', {}, clear=True):
        yield


@pytest.mark.parametrize('target,legacy', ENV_NAMES)
@pytest.mark.parametrize(
    'target_value,legacy_value,expected',
    [
        ('target-value', None, 'target-value'),
        (None, 'legacy-value', 'legacy-value'),
        ('target-value', 'legacy-value', 'target-value'),
        (None, None, 'default-value'),
        ('', 'legacy-value', 'legacy-value'),
        ('', None, ''),
        (None, '', ''),
    ],
)
def test_env_matrix(
    monkeypatch, caplog, target, legacy, target_value, legacy_value, expected
):
    if target_value is not None:
        monkeypatch.setenv(target, target_value)
    if legacy_value is not None:
        monkeypatch.setenv(legacy, legacy_value)

    with caplog.at_level(logging.WARNING):
        assert get_auth0_env(target, 'default-value') == expected

    assert len(caplog.records) == int(not target_value and bool(legacy_value))


def test_legacy_warnings_are_once_per_variable_and_exclude_values(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        for target, legacy in ENV_NAMES:
            monkeypatch.setenv(legacy, 'dummy-sensitive-value')
            assert get_auth0_env(target) == 'dummy-sensitive-value'
            assert get_auth0_env(target) == 'dummy-sensitive-value'
            monkeypatch.delenv(legacy)
            assert get_auth0_env(target) == ''
            monkeypatch.setenv(legacy, 'changed-dummy-value')
            assert get_auth0_env(target) == 'changed-dummy-value'

    assert len(caplog.records) == len(ENV_NAMES)
    for record, (target, legacy) in zip(caplog.records, ENV_NAMES, strict=True):
        assert record.levelno == logging.WARNING
        assert legacy in record.getMessage()
        assert target in record.getMessage()
        assert 'deprecated' in record.getMessage()
        assert 'dummy-sensitive-value' not in str(record.__dict__)
        assert 'changed-dummy-value' not in str(record.__dict__)


def test_jwt_config_reads_target_domain():
    with patch.dict(
        'os.environ', {'AUTH0_ALPACON_DOMAIN': 'tenant.auth0.com'}, clear=True
    ):
        assert _get_auth0_config()['domain'] == 'tenant.auth0.com'


@pytest.mark.parametrize('use_legacy', [False, True])
@pytest.mark.parametrize('audience', [None, '', 'https://example.com/access/'])
def test_config_defaults_and_seal_keys(monkeypatch, use_legacy, audience):
    values = ['tenant.auth0.com', 'dummy-id', 'dummy-secret', audience, '', None]
    for (target, legacy), value in zip(ENV_NAMES, values, strict=True):
        if value is not None:
            monkeypatch.setenv(legacy if use_legacy else target, value)

    expected_audience = 'https://alpacon.io/access/' if audience is None else audience
    jwt_config = _get_auth0_config()
    oauth_config = _get_oauth_config()
    assert jwt_config['audience'] == oauth_config['audience'] == expected_audience
    assert jwt_config['namespace'] == 'https://alpacon.io/'
    assert oauth_config['domain'] == 'tenant.auth0.com'
    assert oauth_config['client_id'] == 'dummy-id'
    assert oauth_config['client_secret'] == 'dummy-secret'
    assert oauth_config['mfa_audience'] == 'https://tenant.auth0.com/mfa/'
    for read_key, info in [
        (_get_state_secret, _STATE_SECRET_INFO),
        (_get_grant_secret, _GRANT_SECRET_INFO),
    ]:
        assert read_key() == hmac.new(b'dummy-secret', info, hashlib.sha256).digest()


@pytest.mark.parametrize('use_legacy', [False, True])
@pytest.mark.parametrize(
    'namespace', ['', 'https://example.com', 'https://example.com///']
)
def test_namespace_normalization_at_all_consumers(monkeypatch, use_legacy, namespace):
    target, legacy = ENV_NAMES[-1]
    monkeypatch.setenv(legacy if use_legacy else target, namespace)
    monkeypatch.setenv('AUTH0_ALPACON_DOMAIN', 'tenant.auth0.com')
    expected = namespace.rstrip('/') + '/'
    assert _get_auth0_config()['namespace'] == expected

    claims = {f'{expected}workspaces': [None]}
    with patch('utils.auth.decode_claims_unverified', return_value=claims):
        assert get_token_workspaces_with_dropped('dummy-jwt') == ([], 1)
