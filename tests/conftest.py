"""Shared fixtures and helpers for all tests.

Provides autouse fixtures that keep tests off the real TokenManager, so no test
reads ~/.alpacon-mcp/token.json or depends on it existing.
"""

from contextlib import contextmanager
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.http_client import HTTP_VERBS

# Canonical http_client error envelope (the shape utils/http_client returns on
# 4xx/5xx). Shared across error-path tests so the envelope is defined once.
HTTP_ERROR_ENVELOPE = {
    'error': 'HTTP Error',
    'status_code': HTTPStatus.NOT_FOUND,
    'message': 'Not found',
}


def http_client_fixture(module_name: str):
    """Build a `mock_http_client` fixture patching the tool module's `http_client`."""

    @pytest.fixture
    def _mock_http_client():
        with patch(f'{module_name}.http_client') as mock_client:
            for verb in HTTP_VERBS:  # patch() alone leaves these un-awaitable
                setattr(mock_client, verb, AsyncMock())
            yield mock_client

    return _mock_http_client


@contextmanager
def patched_token_manager(token: str | None):
    """Make validate_token() return `token`.

    utils.common resolves its TokenManager per call, so the getter is the patch
    target—there is no module-level instance to replace.
    """
    manager = MagicMock()
    manager.get_token.return_value = token
    with patch('utils.common.get_token_manager', return_value=manager):
        yield manager


@pytest.fixture
def mock_token_manager():
    """Mock token manager so tests never read a real ~/.alpacon-mcp/token.json."""
    with patched_token_manager('test-token') as manager:
        yield manager


@pytest.fixture(autouse=True)
def mock_region_auto_detect():
    """Prevent _resolve_region from accessing real token.json in all tests.

    The with_token_validation decorator calls get_token_manager() when region
    is empty to auto-detect it. Without this fixture, tests that omit region
    fail in CI where no token.json exists.

    Tests that need custom get_token_manager behavior (e.g. TestRegionAutoDetection)
    apply their own @patch which takes precedence over this fixture.
    """
    mock_tm = MagicMock()
    mock_tm.find_region_for_workspace.return_value = 'ap1'
    mock_tm.get_default_region.return_value = 'ap1'
    mock_tm.get_available_regions.return_value = ['ap1']
    # No pinned host override by default: http_client.get_base_url derives the
    # default Alpacon Cloud host. (get_base_url also type-guards this, but being
    # explicit keeps the mock's behavior obvious.)
    mock_tm.get_base_url_override.return_value = None

    # patch() rebinds one name at a time, so every module that imported
    # get_token_manager at its own top level needs its own entry here.
    with (
        patch('utils.token_manager.get_token_manager', return_value=mock_tm),
        patch('utils.health.get_token_manager', return_value=mock_tm),
        patch('tools.workspace_tools.get_token_manager', return_value=mock_tm),
    ):
        yield mock_tm
