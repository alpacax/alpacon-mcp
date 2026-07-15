"""Unit tests for TokenManager token and base-URL resolution.

Covers the legacy bare-string token form, the object form
``{"token": "...", "url": "..."}`` (used to pin a workspace's API host across a
slug change, ADR 0027), and the environment-variable overrides for both token
and base URL.
"""

import json

import pytest

from utils.token_manager import TokenManager


@pytest.fixture
def token_file(tmp_path):
    """Return a path factory that writes token.json content and builds a TokenManager."""

    def _make(config: dict) -> TokenManager:
        path = tmp_path / 'token.json'
        path.write_text(json.dumps(config))
        return TokenManager(config_file=str(path))

    return _make


class TestGetTokenForms:
    """Both the legacy string form and the object form yield the token string."""

    def test_bare_string_token(self, token_file):
        tm = token_file({'ap1': {'production': 'plain-token'}})
        assert tm.get_token('ap1', 'production') == 'plain-token'

    def test_object_form_token(self, token_file):
        tm = token_file(
            {'ap1': {'production': {'token': 'obj-token', 'url': 'https://x'}}}
        )
        assert tm.get_token('ap1', 'production') == 'obj-token'

    def test_object_form_without_token_returns_none(self, token_file):
        tm = token_file({'ap1': {'production': {'url': 'https://x'}}})
        assert tm.get_token('ap1', 'production') is None

    def test_missing_workspace_returns_none(self, token_file):
        tm = token_file({'ap1': {'production': 'plain-token'}})
        assert tm.get_token('ap1', 'staging') is None

    def test_env_var_token_wins(self, token_file, monkeypatch):
        tm = token_file({'ap1': {'production': 'config-token'}})
        monkeypatch.setenv('ALPACON_MCP_AP1_PRODUCTION_TOKEN', 'env-token')
        assert tm.get_token('ap1', 'production') == 'env-token'


class TestGetBaseURLOverride:
    """A pinned base URL is preferred over the derived host."""

    def test_no_override_by_default(self, token_file):
        tm = token_file({'ap1': {'production': 'plain-token'}})
        assert tm.get_base_url_override('ap1', 'production') is None

    def test_object_form_url_override(self, token_file):
        tm = token_file(
            {
                'ap1': {
                    'production': {'token': 't', 'url': 'https://acme.us1.alpacon.io'}
                }
            }
        )
        assert (
            tm.get_base_url_override('ap1', 'production')
            == 'https://acme.us1.alpacon.io'
        )

    def test_url_override_normalizes_scheme_and_trailing_slash(self, token_file):
        tm = token_file(
            {'ap1': {'production': {'token': 't', 'url': 'acme.us1.alpacon.io/'}}}
        )
        assert (
            tm.get_base_url_override('ap1', 'production')
            == 'https://acme.us1.alpacon.io'
        )

    def test_env_var_url_override_wins(self, token_file, monkeypatch):
        tm = token_file(
            {'ap1': {'production': {'token': 't', 'url': 'https://from-config'}}}
        )
        monkeypatch.setenv(
            'ALPACON_MCP_AP1_PRODUCTION_URL', 'https://from-env.us1.alpacon.io'
        )
        assert (
            tm.get_base_url_override('ap1', 'production')
            == 'https://from-env.us1.alpacon.io'
        )

    def test_bare_string_entry_has_no_override(self, token_file):
        tm = token_file({'ap1': {'production': 'plain-token'}})
        assert tm.get_base_url_override('ap1', 'production') is None

    def test_missing_workspace_has_no_override(self, token_file):
        tm = token_file({'ap1': {'production': {'token': 't', 'url': 'https://x'}}})
        assert tm.get_base_url_override('ap1', 'staging') is None
