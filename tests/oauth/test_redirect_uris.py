"""Tests for the redirect_uri allowlist."""

from unittest.mock import patch

from tests.oauth._support import (
    CONNECTOR_REDIRECT_URI,
    EXEMPT_REDIRECT_URI,
    LISTED_REDIRECT_URI,
    REPORT_ONLY,
    UNLISTED_PATH_URI,
    MockMCPServer,
)
from utils.oauth import register_oauth_routes
from utils.oauth._redirect_uris import (
    _get_allowed_redirect_uris,
    _is_allowed_redirect_uri,
    _is_exact_allowed_redirect_uri,
    _is_pkce_exempt_redirect_uri,
)


class TestAllowedRedirectUris:
    """Tests for the endpoint-level redirect_uri allowlist configuration."""

    def test_defaults_cover_known_remote_clients(self):
        uris = _get_allowed_redirect_uris()
        assert 'https://claude.ai/api/mcp/auth_callback' in uris
        assert 'https://claude.com/api/mcp/auth_callback' in uris
        assert 'https://chatgpt.com/connector_platform_oauth_redirect' in uris
        assert 'https://www.cursor.com/agents/mcp/oauth/callback' in uris
        assert 'https://vscode.dev/redirect/' in uris
        assert 'https://antigravity.google/oauth-callback' in uris
        assert 'https://global.consent.azure-apim.net/redirect' in uris

    def test_env_override_replaces_defaults(self):
        with patch.dict(
            'os.environ',
            {'ALLOWED_REDIRECT_URIS': 'https://a.example/cb, https://b.example/cb'},
        ):
            assert _get_allowed_redirect_uris() == (
                'https://a.example/cb',
                'https://b.example/cb',
            )

    def test_warns_when_only_legacy_domain_var_is_set(self, caplog):
        with patch.dict(
            'os.environ', {'ALLOWED_REDIRECT_DOMAINS': 'custom.example.com'}
        ):
            with caplog.at_level('WARNING'):
                register_oauth_routes(MockMCPServer())

        assert 'ALLOWED_REDIRECT_URIS' in caplog.text

    def test_blank_domain_var_does_not_warn(self, caplog):
        """A whitespace-only value is unset to _get_allowed_redirect_domains."""
        with patch.dict('os.environ', {'ALLOWED_REDIRECT_DOMAINS': '  '}):
            with caplog.at_level('WARNING'):
                register_oauth_routes(MockMCPServer())

        assert 'ALLOWED_REDIRECT_URIS' not in caplog.text

    def test_domain_var_with_report_only_does_not_warn(self, caplog):
        """Report-only mode is what makes the domain list usable on its own."""
        with patch.dict(
            'os.environ',
            {'ALLOWED_REDIRECT_DOMAINS': 'custom.example.com', **REPORT_ONLY},
        ):
            with caplog.at_level('WARNING'):
                register_oauth_routes(MockMCPServer())

        assert 'ALLOWED_REDIRECT_URIS' not in caplog.text


class TestExactRedirectUriMatch:
    """Tests for endpoint-level redirect_uri matching."""

    def test_listed_uri_matches(self):
        assert _is_exact_allowed_redirect_uri(LISTED_REDIRECT_URI)
        assert _is_exact_allowed_redirect_uri(
            'https://antigravity.google/oauth-callback'
        )

    def test_other_path_on_trusted_domain_is_rejected(self):
        assert not _is_exact_allowed_redirect_uri(UNLISTED_PATH_URI)
        assert not _is_exact_allowed_redirect_uri('https://claude.ai/')

    def test_query_or_fragment_is_rejected(self):
        base = LISTED_REDIRECT_URI
        assert not _is_exact_allowed_redirect_uri(f'{base}?x=1')
        assert not _is_exact_allowed_redirect_uri(f'{base}#frag')

    def test_chatgpt_connector_id_segment_matches(self):
        assert _is_exact_allowed_redirect_uri(
            'https://chatgpt.com/connector/oauth/abc123_-XYZ'
        )

    def test_chatgpt_connector_extra_segment_is_rejected(self):
        assert not _is_exact_allowed_redirect_uri(
            'https://chatgpt.com/connector/oauth/abc/evil'
        )
        assert not _is_exact_allowed_redirect_uri(
            'https://chatgpt.com/connector/oauth/'
        )

    def test_chatgpt_connector_trailing_newline_is_rejected(self):
        """$ would match before a trailing newline; the pattern uses \\Z."""

        assert not _is_exact_allowed_redirect_uri(f'{CONNECTOR_REDIRECT_URI}\n')

    def test_env_override_is_honoured(self):
        with patch.dict(
            'os.environ', {'ALLOWED_REDIRECT_URIS': 'https://a.example/cb'}
        ):
            assert _is_exact_allowed_redirect_uri('https://a.example/cb')
            assert not _is_exact_allowed_redirect_uri(LISTED_REDIRECT_URI)
            # The built-in patterns are part of the built-in list, so an
            # override drops them too.
            assert not _is_exact_allowed_redirect_uri(CONNECTOR_REDIRECT_URI)

    def test_plaintext_uri_is_rejected(self):
        with patch.dict('os.environ', {'ALLOWED_REDIRECT_URIS': 'http://a.example/cb'}):
            assert not _is_exact_allowed_redirect_uri('http://a.example/cb')


class TestPkceExemption:
    """Tests for the one redirect_uri that may skip PKCE."""

    def test_pkce_exempt_uri_is_the_copilot_studio_callback(self):
        assert _is_pkce_exempt_redirect_uri(EXEMPT_REDIRECT_URI)

    def test_pkce_exemption_needs_the_whole_string(self):
        assert not _is_pkce_exempt_redirect_uri(
            'https://global.consent.azure-apim.net/redirect/deeper'
        )
        assert not _is_pkce_exempt_redirect_uri(
            'https://global.consent.azure-apim.net/'
        )
        assert not _is_pkce_exempt_redirect_uri(
            'https://global.consent.azure-apim.net/redirect?x=1'
        )

    def test_pkce_exemption_does_not_extend_to_other_allowlisted_uris(self):
        assert not _is_pkce_exempt_redirect_uri(LISTED_REDIRECT_URI)
        assert not _is_pkce_exempt_redirect_uri('http://localhost:52048/callback')

    def test_pkce_exemption_is_not_widened_by_report_only_mode(self):
        with patch.dict('os.environ', REPORT_ONLY):
            assert not _is_pkce_exempt_redirect_uri(
                'https://global.consent.azure-apim.net/redirect/deeper'
            )

    def test_pkce_exemption_dies_with_the_allowlist_entry(self):
        with patch.dict('os.environ', {'ALLOWED_REDIRECT_URIS': LISTED_REDIRECT_URI}):
            assert not _is_pkce_exempt_redirect_uri(EXEMPT_REDIRECT_URI)


class TestRedirectUriGate:
    """Tests for the redirect_uri endpoint gate."""

    def test_rejects_untracked_path_by_default(self):
        assert not _is_allowed_redirect_uri(UNLISTED_PATH_URI)

    def test_allows_listed_endpoint(self):
        assert _is_allowed_redirect_uri(LISTED_REDIRECT_URI)

    def test_every_default_endpoint_passes_the_gate(self):
        """A listed endpoint must not be blocked by the legacy host allowlist."""

        for uri in _get_allowed_redirect_uris():
            assert _is_allowed_redirect_uri(uri), uri
        assert _is_allowed_redirect_uri(CONNECTOR_REDIRECT_URI)

    def test_keeps_every_loopback_path(self):
        assert _is_allowed_redirect_uri('http://localhost:1234/callback')
        assert _is_allowed_redirect_uri('http://localhost:1234/oauth/callback')
        assert _is_allowed_redirect_uri('http://127.0.0.1:33418/')

    def test_untrusted_domain_is_rejected_in_either_mode(self):
        assert not _is_allowed_redirect_uri('https://evil.com/cb')
        with patch.dict('os.environ', REPORT_ONLY):
            assert not _is_allowed_redirect_uri('https://evil.com/cb')

    def test_report_only_covers_every_built_in_client_host(self):
        """The escape hatch is useless on a host whose endpoint it cannot reach."""

        with patch.dict('os.environ', REPORT_ONLY):
            for uri in _get_allowed_redirect_uris():
                moved = uri.rstrip('/') + '/moved'
                assert _is_allowed_redirect_uri(moved), moved

    def test_report_only_allows_untracked_path_with_a_warning(self, caplog):
        with patch.dict('os.environ', REPORT_ONLY):
            with caplog.at_level('WARNING'):
                assert _is_allowed_redirect_uri(UNLISTED_PATH_URI)
        assert 'report-only' in caplog.text
