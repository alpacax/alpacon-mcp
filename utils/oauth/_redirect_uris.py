"""The redirect_uri allowlist and the PKCE exemption for known connectors."""

import os
import re
from typing import TypeGuard
from urllib.parse import ParseResult, urlparse

from utils.logger import escape_for_log
from utils.oauth._http import logger

_ENV_ALLOWED_REDIRECT_DOMAINS = 'ALLOWED_REDIRECT_DOMAINS'
_ENV_ALLOWED_REDIRECT_URIS = 'ALLOWED_REDIRECT_URIS'
_ENV_REDIRECT_URI_REPORT_ONLY = 'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY'

_ALLOWED_LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')

# Trusting a whole domain lets an authorization code land on any path an
# attacker can influence there, so each entry pins one callback endpoint.
_DEFAULT_REDIRECT_URIS = (
    # Anthropic—hosted surfaces (web, Desktop, mobile, Cowork)
    'https://claude.ai/api/mcp/auth_callback',
    'https://claude.com/api/mcp/auth_callback',
    # OpenAI—legacy connector callback, still served for published apps
    'https://chatgpt.com/connector_platform_oauth_redirect',
    # Cursor—web and Cursor Agents
    'https://www.cursor.com/agents/mcp/oauth/callback',
    # VS Code / GitHub Copilot—web
    'https://vscode.dev/redirect/',
    'https://antigravity.google/oauth-callback',
    # Microsoft Copilot Studio, via the Power Platform connector gateway
    'https://global.consent.azure-apim.net/redirect',
)

# OpenAI issues one opaque callback id per connector. No "/" in the class, so no
# deeper path matches; \Z rather than $, so a trailing newline cannot ride along.
_DEFAULT_REDIRECT_URI_PATTERNS = (
    re.compile(r'^https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,64}\Z'),
)

# Copilot Studio's connector cannot send a challenge. Redundant with the allowlist
# today; kept so dropping the callback there cannot leave an exempt destination.
_PKCE_EXEMPT_REDIRECT_URIS = frozenset(
    {'https://global.consent.azure-apim.net/redirect'}
)

# Report-only fallback hosts, derived from the endpoints so a moved one stays covered;
# chat.openai.com is the legacy OpenAI host. ALLOWED_REDIRECT_DOMAINS overrides.
_DEFAULT_REDIRECT_DOMAINS = tuple(
    sorted(
        {host for uri in _DEFAULT_REDIRECT_URIS if (host := urlparse(uri).hostname)}
        | {'chat.openai.com'}
    )
)

# A real client registers one or two callbacks; the cap bounds the checks, and the
# report-only warnings, that one unauthenticated registration can drive.
_MAX_REGISTERED_REDIRECT_URIS = 20


def _get_allowed_redirect_domains() -> tuple[str, ...]:
    """Return the legacy redirect host allowlist: ALLOWED_REDIRECT_DOMAINS
    (comma-separated) when set, else the defaults."""
    env_domains = os.getenv(_ENV_ALLOWED_REDIRECT_DOMAINS, '').strip()
    if env_domains:
        return tuple(d.strip().lower() for d in env_domains.split(',') if d.strip())
    return _DEFAULT_REDIRECT_DOMAINS


def _get_allowed_redirect_uris() -> tuple[str, ...]:
    """Return the allowed non-loopback callback endpoints: ALLOWED_REDIRECT_URIS
    (comma-separated full URIs) when set, else the defaults."""
    env_uris = os.getenv(_ENV_ALLOWED_REDIRECT_URIS, '').strip()
    if env_uris:
        return tuple(u.strip() for u in env_uris.split(',') if u.strip())
    return _DEFAULT_REDIRECT_URIS


def _has_redirect_uri_override() -> bool:
    return bool(os.getenv(_ENV_ALLOWED_REDIRECT_URIS, '').strip())


def _is_redirect_uri_report_only() -> bool:
    """Escape hatch: recover from a missing allowlist entry without a code change."""
    return os.getenv(_ENV_REDIRECT_URI_REPORT_ONLY, '').lower() == 'true'


def _parse_redirect_uri(url: str) -> ParseResult | None:
    """Parse a client-supplied URI; None when urlparse refuses it (an unbalanced
    IPv6 bracket), so every predicate rejects it instead of raising."""
    try:
        return urlparse(url)
    except ValueError:
        return None


def _is_allowed_redirect_host(url: str) -> bool:
    """Whether the URL is https on an allowlisted host; not sufficient alone, see
    _is_allowed_redirect_uri."""
    parsed = _parse_redirect_uri(url)
    if parsed is None or parsed.scheme != 'https':
        return False

    return (parsed.hostname or '') in _get_allowed_redirect_domains()


def _is_exact_allowed_redirect_uri(url: str) -> bool:
    """Whether the URL is a pinned https callback endpoint without query or fragment;
    it bypasses the host allowlist, so the https check lives here too."""
    parsed = _parse_redirect_uri(url)
    if parsed is None or parsed.scheme != 'https' or parsed.query or parsed.fragment:
        return False

    if url in _get_allowed_redirect_uris():
        return True

    # An override is the whole allowlist: the built-in patterns go out with the
    # built-in URIs, so narrowing the list cannot leave one behind.
    if _has_redirect_uri_override():
        return False

    return any(pattern.match(url) for pattern in _DEFAULT_REDIRECT_URI_PATTERNS)


def _is_pkce_exempt_redirect_uri(url: str) -> bool:
    """Whether a destination may start a flow with no PKCE. Not
    _is_allowed_redirect_uri: its report-only mode accepts any allowlisted host path."""
    return url in _PKCE_EXEMPT_REDIRECT_URIS and _is_exact_allowed_redirect_uri(url)


def _is_allowed_redirect_uri(url: str) -> bool:
    """Whether a client redirect_uri may receive an authorization code. Loopback is
    exempt: paths differ per client, and browser-session binding covers that risk."""
    # A pinned endpoint is stricter than a host match, so it stands on its own;
    # otherwise every listed host would also have to be in the domain list.
    if _is_exact_allowed_redirect_uri(url):
        return True

    parsed = _parse_redirect_uri(url)
    if parsed is None:
        return False
    if (parsed.hostname or '') in _ALLOWED_LOOPBACK_HOSTS:
        return parsed.scheme in ('http', 'https')

    if not _is_allowed_redirect_host(url):
        return False

    if _is_redirect_uri_report_only():
        logger.warning(
            'redirect_uri is outside the endpoint allowlist and is allowed only '
            'because report-only mode is on: %s',
            escape_for_log(url),
        )
        return True

    logger.warning(
        'Rejected redirect_uri outside the endpoint allowlist: %s',
        escape_for_log(url),
    )
    return False


def _is_registrable_uri_list(value: object) -> TypeGuard[list[str]]:
    """Whether redirect_uris has the shape RFC 7591 asks for, at a length we accept."""
    return (
        isinstance(value, list)
        and 1 <= len(value) <= _MAX_REGISTERED_REDIRECT_URIS
        and all(isinstance(uri, str) and uri for uri in value)
    )
