"""Shared fixtures for all tests.

Provides autouse fixtures that prevent tests from hitting the real
TokenManager (which requires ~/.alpacon-mcp/token.json to exist).
"""

from unittest.mock import MagicMock, patch

import pytest

# Canonical http_client error envelope (the shape utils/http_client returns on
# 4xx/5xx). Shared across error-path tests so the envelope is defined once.
HTTP_ERROR_ENVELOPE = {
    'error': 'HTTP Error',
    'status_code': 404,
    'message': 'Not found',
}


@pytest.fixture
def mock_token_manager():
    """Mock token manager so tests never read a real ~/.alpacon-mcp/token.json."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


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

    with patch('utils.token_manager.get_token_manager', return_value=mock_tm):
        yield mock_tm
