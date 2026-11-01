"""TokenManager token and base-URL resolution: the legacy string form, the object form
{"token", "url"} (pins an API host across a slug change, ADR 0027), and env overrides.
"""

import json
import logging
import os
import stat

import pytest

from utils.token_manager import TokenManager


@pytest.fixture
def token_file(tmp_path):
    """Return a path factory that writes token.json content and builds a TokenManager."""

    def _make(config: dict[str, object]) -> TokenManager:
        path = tmp_path / 'token.json'
        path.write_text(json.dumps(config))
        return TokenManager(config_file=str(path))

    return _make


class TestLoadTokens:
    """A config file that is not a JSON object must not reach the callers."""

    def test_non_object_json_loads_as_empty(self, tmp_path):
        """A top-level JSON array parses cleanly, so only a type check stops it."""
        path = tmp_path / 'token.json'
        path.write_text('["ap1", "us1"]')

        tm = TokenManager(config_file=str(path))

        assert tm.get_all_tokens() == {}

    def test_scalar_json_loads_as_empty(self, tmp_path):
        """A bare JSON string is the same mistake with a different shape."""
        path = tmp_path / 'token.json'
        path.write_text('"not-a-config"')

        tm = TokenManager(config_file=str(path))

        assert tm.get_all_tokens() == {}

    @pytest.mark.parametrize(
        ('content', 'cause'),
        [
            ('["ap1", "us1"]', 'must hold a JSON object of regions'),
            ('{oops', 'JSON decode error'),
        ],
    )
    def test_an_unusable_file_is_reported_once_by_its_own_cause(
        self, tmp_path, caplog, content, cause
    ):
        """A file that was found and read must not also be reported as missing."""
        path = tmp_path / 'token.json'
        path.write_text(content)

        with caplog.at_level(logging.WARNING):
            TokenManager(config_file=str(path))

        assert cause in caplog.text
        assert len(caplog.records) == 1


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


class TestNonObjectRegionValue:
    """A top-level value that is not an object holds no tokens and is kept on save."""

    def test_a_non_object_value_is_not_a_region(self, token_file):
        tm = token_file({'ap1': {'production': 't'}, '_comment': 'edited by hand'})

        assert tm.get_available_regions() == ['ap1']
        assert tm.get_default_region() == 'ap1'
        assert tm.get_all_tokens() == {'ap1': {'production': 't'}}

    def test_a_non_object_region_has_no_token(self, token_file):
        tm = token_file({'ap1': 'production'})

        assert tm.get_token('ap1', 'production') is None
        assert tm.remove_token('ap1', 'production')['status'] == 'error'

    def test_saving_a_token_keeps_a_non_object_value(self, token_file, tmp_path):
        tm = token_file({'_comment': 'edited by hand'})

        tm.set_token('ap1', 'production', 't')

        saved = json.loads((tmp_path / 'token.json').read_text())
        assert saved == {'_comment': 'edited by hand', 'ap1': {'production': 't'}}


class TestSecurePersistence:
    """Credential persistence should be atomic and private on POSIX."""

    def test_serialization_failure_preserves_existing_file(self, tmp_path, monkeypatch):
        import utils.credential_store as store

        path = tmp_path / 'token.json'
        original = '{"ap1": {"prod": "old-token"}}'
        path.write_text(original)

        def fail_serialization(*args, **kwargs):
            raise TypeError('simulated serialization failure')

        monkeypatch.setattr(store.json, 'dumps', fail_serialization)
        with pytest.raises(TypeError, match='simulated serialization failure'):
            store.save_json_securely({'ap1': {'prod': 'new-token'}}, path)

        assert path.read_text() == original
        assert list(tmp_path.iterdir()) == [path]

    def test_write_failure_preserves_existing_file(self, tmp_path, monkeypatch):
        import utils.credential_store as store

        path = tmp_path / 'token.json'
        original = '{"ap1": {"prod": "old-token"}}'
        path.write_text(original)
        real_fdopen = store.os.fdopen

        class BrokenWriter:
            def __init__(self, fd, *args, **kwargs):
                self.stream = real_fdopen(fd, *args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()
                return False

            def write(self, value):
                self.stream.write(value[:8])
                self.stream.flush()
                raise OSError('simulated disk write failure')

        def broken_fdopen(fd, *args, **kwargs):
            return BrokenWriter(fd, *args, **kwargs)

        monkeypatch.setattr(store.os, 'fdopen', broken_fdopen)
        with pytest.raises(OSError, match='simulated disk write failure'):
            store.save_json_securely({'ap1': {'prod': 'new-token'}}, path)

        assert path.read_text() == original
        assert list(tmp_path.iterdir()) == [path]

    @pytest.mark.skipif(os.name != 'posix', reason='requires POSIX file modes')
    def test_new_credentials_file_is_0600_under_umask_022(self, tmp_path):
        path = tmp_path / 'token.json'
        previous_umask = os.umask(0o022)
        try:
            manager = TokenManager(config_file=str(path))
            manager.set_token('ap1', 'prod', 'secret')
        finally:
            os.umask(previous_umask)

        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    @pytest.mark.skipif(os.name != 'posix', reason='requires POSIX directory modes')
    def test_default_application_config_directory_is_0700(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        TokenManager()

        directory = tmp_path / '.alpacon-mcp'
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
