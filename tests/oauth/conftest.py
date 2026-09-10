"""Fixtures for the OAuth tests."""

from unittest.mock import patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from tests.oauth._support import OAUTH_ENV, TEST_NONCE, MockMCPServer
from utils.oauth import register_oauth_routes
from utils.oauth._sealing import _NONCE_COOKIE_NAME


@pytest.fixture(autouse=True)
def _set_oauth_env():
    """Ensure OAuth env vars are set for all tests."""
    with patch.dict('os.environ', OAUTH_ENV):
        yield


@pytest.fixture
def oauth_app():
    """Create a minimal Starlette app with OAuth routes registered.

    The client carries the nonce cookie a real browser would have, so callback
    tests exercise the success path; use oauth_app_no_cookie for the negative.
    """
    mock_server = MockMCPServer()
    register_oauth_routes(mock_server)
    return TestClient(
        Starlette(routes=mock_server.routes),
        raise_server_exceptions=False,
        cookies={_NONCE_COOKIE_NAME: TEST_NONCE},
    )


@pytest.fixture
def oauth_app_no_cookie():
    """A client with no nonce cookie, standing in for a browser that never
    started the flow."""
    mock_server = MockMCPServer()
    register_oauth_routes(mock_server)
    return TestClient(
        Starlette(routes=mock_server.routes), raise_server_exceptions=False
    )
