"""Fixtures shared by the OAuth proxy tests."""

import sys
from unittest.mock import patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from tests.oauth._support import (
    OAUTH_ENV,
    TEST_NONCE,
    TEST_NONCE_COOKIE,
    MockMCPServer,
)
from utils.oauth import register_oauth_routes


@pytest.fixture(autouse=True)
def _set_oauth_env():
    """Ensure OAuth env vars are set for all tests."""
    with patch.dict('os.environ', OAUTH_ENV):
        yield


@pytest.fixture
def default_int_digit_limit():
    """Pin Python's integer digit limit, which PYTHONINTMAXSTRDIGITS can lift."""
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(sys.int_info.default_max_str_digits)
    yield
    sys.set_int_max_str_digits(previous)


@pytest.fixture
def oauth_app():
    """Minimal Starlette app with the OAuth routes registered. Its client carries the
    nonce cookie a browser would; oauth_app_no_cookie is the negative.
    """
    mock_server = MockMCPServer()
    register_oauth_routes(mock_server)
    return TestClient(
        Starlette(routes=mock_server.routes),
        raise_server_exceptions=False,
        cookies={TEST_NONCE_COOKIE: TEST_NONCE},
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
