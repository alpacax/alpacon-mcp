"""The redirect_uri allowlist."""

import os
import re
from urllib.parse import urlparse

from utils.logger import get_logger
from utils.oauth._http import _escape_for_log

logger = get_logger('oauth')


_ENV_ALLOWED_REDIRECT_DOMAINS = 'ALLOWED_REDIRECT_DOMAINS'


_ENV_ALLOWED_REDIRECT_URIS = 'ALLOWED_REDIRECT_URIS'


_ENV_REDIRECT_URI_REPORT_ONLY = 'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY'


_ALLOWED_LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')


# Trusting a whole domain lets an authorization code land on any path an
# attacker can influence there, so each entry pins one callback endpoint.
_DEFAULT_REDIRECT_URIS = (
    # Anthropic: web, Desktop, mobile, Cowork
    'https://claude.ai/api/mcp/auth_callback',
    'https://claude.com/api/mcp/auth_callback',
    # OpenAI: legacy connector callback, still served for published apps
    'https://chatgpt.com/connector_platform_oauth_redirect',
    # Cursor: web and Cursor Agents
    'https://www.cursor.com/agents/mcp/oauth/callback',
    # VS Code and GitHub Copilot: web
    'https://vscode.dev/redirect/',
    'https://antigravity.google/oauth-callback',
    # Microsoft Copilot Studio: the Power Platform connector gateway
    'https://global.consent.azure-apim.net/redirect',
)


# OpenAI issues one opaque callback id per connector, so the last segment cannot
# be pinned. No "/" in the class, so no deeper path matches; \Z rather than $,
# so a trailing newline cannot ride along.
_DEFAULT_REDIRECT_URI_PATTERNS = (
    re.compile(r'^https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,64}\Z'),
)


# Copilot Studio's Power Platform connector cannot send a challenge, so its
# gateway callback may start a flow without one. Redundant with the allowlist
# today; kept so dropping the callback there cannot leave an exemption behind.
_PKCE_EXEMPT_REDIRECT_URIS = frozenset(
    {'https://global.consent.azure-apim.net/redirect'}
)


# Hosts report-only mode falls back to, derived from the endpoint list so a
# moved endpoint stays covered without a second edit. chat.openai.com has no
# endpoint entry and stays as the legacy OpenAI host. ALLOWED_REDIRECT_DOMAINS
# (comma-separated) overrides the list.
_DEFAULT_REDIRECT_DOMAINS = tuple(
    sorted(
        {host for uri in _DEFAULT_REDIRECT_URIS if (host := urlparse(uri).hostname)}
        | {'chat.openai.com'}
    )
)


# A real client registers one or two callbacks; the cap keeps one unauthenticated
# registration from driving a check, and in report-only mode a warning, per entry.
_MAX_REGISTERED_REDIRECT_URIS = 20


def _get_allowed_redirect_domains() -> tuple[str, ...]:
    """Allowed non-loopback redirect hosts.

    ALLOWED_REDIRECT_DOMAINS (comma-separated) when set, else the built-in list.
    """
    env_domains = os.getenv(_ENV_ALLOWED_REDIRECT_DOMAINS, '').strip()
    if env_domains:
        return tuple(d.strip().lower() for d in env_domains.split(',') if d.strip())
    return _DEFAULT_REDIRECT_DOMAINS


def _get_allowed_redirect_uris() -> tuple[str, ...]:
    """Allowed non-loopback callback endpoints.

    ALLOWED_REDIRECT_URIS (comma-separated full URIs) when set, else the built-in
    list.
    """
    env_uris = os.getenv(_ENV_ALLOWED_REDIRECT_URIS, '').strip()
    if env_uris:
        return tuple(u.strip() for u in env_uris.split(',') if u.strip())
    return _DEFAULT_REDIRECT_URIS


def _has_redirect_uri_override() -> bool:
    return bool(os.getenv(_ENV_ALLOWED_REDIRECT_URIS, '').strip())


def _is_redirect_uri_report_only() -> bool:
    """Escape hatch: recover from a missing allowlist entry without a code change."""
    return os.getenv(_ENV_REDIRECT_URI_REPORT_ONLY, '').lower() == 'true'


def _is_allowed_redirect_host(url: str) -> bool:
    """Whether the URL's host clears the legacy host allowlist.

    https only, so an authorization code never travels over plaintext. Not
    sufficient on its own; see _is_allowed_redirect_uri.
    """
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        return False

    return (parsed.hostname or '') in _get_allowed_redirect_domains()


def _is_exact_allowed_redirect_uri(url: str) -> bool:
    """Return True when the URL is one of the allowed callback endpoints.

    https only: a pinned endpoint bypasses the host allowlist, so the scheme
    check that keeps authorization codes off plaintext lives here too.
    """
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment:
        return False

    if url in _get_allowed_redirect_uris():
        return True

    # An override is the whole allowlist: the built-in patterns go out with the
    # built-in URIs, so narrowing the list cannot leave one behind.
    if _has_redirect_uri_override():
        return False

    return any(pattern.match(url) for pattern in _DEFAULT_REDIRECT_URI_PATTERNS)


def _is_pkce_exempt_redirect_uri(url: str) -> bool:
    """Whether a destination may start an authorization flow with no PKCE.

    Goes through _is_exact_allowed_redirect_uri, not _is_allowed_redirect_uri: the
    latter accepts any path on an allowlisted host in report-only mode, which
    would let an unrelated environment variable widen the exemption.
    """
    return url in _PKCE_EXEMPT_REDIRECT_URIS and _is_exact_allowed_redirect_uri(url)


def _is_allowed_redirect_uri(url: str) -> bool:
    """Decide whether a client redirect_uri may receive an authorization code.

    Loopback is exempt: callback paths differ per client (/callback,
    /oauth/callback, /) and pinning them would break clients without closing
    the local-listener risk, which browser-session binding handles instead.
    """
    # A pinned endpoint is stricter than a host match, so it stands on its own;
    # otherwise every listed host would also have to be in the domain list.
    if _is_exact_allowed_redirect_uri(url):
        return True

    parsed = urlparse(url)
    if (parsed.hostname or '') in _ALLOWED_LOOPBACK_HOSTS:
        return parsed.scheme in ('http', 'https')

    if not _is_allowed_redirect_host(url):
        return False

    if _is_redirect_uri_report_only():
        logger.warning(
            'redirect_uri is outside the endpoint allowlist and is allowed only '
            'because report-only mode is on: %s',
            _escape_for_log(url),
        )
        return True

    logger.warning(
        'Rejected redirect_uri outside the endpoint allowlist: %s',
        _escape_for_log(url),
    )
    return False


def _is_registrable_uri_list(value: object) -> bool:
    """Whether redirect_uris has the shape RFC 7591 asks for, at a length we accept."""
    return (
        isinstance(value, list)
        and 1 <= len(value) <= _MAX_REGISTERED_REDIRECT_URIS
        and all(isinstance(uri, str) and uri for uri in value)
    )
