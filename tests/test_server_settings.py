"""Auth settings this deployment pins deliberately."""

import importlib
import os

import pytest


@pytest.fixture
def auth_server(monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'true')
    monkeypatch.setenv('AUTH0_DOMAIN', 'example.us.auth0.com')
    monkeypatch.setenv('ALPACON_MCP_RESOURCE_URL', 'https://mcp.example.com')
    import server

    importlib.reload(server)
    yield server
    for key in ('ALPACON_MCP_AUTH_ENABLED', 'AUTH0_DOMAIN', 'ALPACON_MCP_RESOURCE_URL'):
        os.environ.pop(key, None)
    importlib.reload(server)


def test_token_resource_validation_is_explicitly_disabled(auth_server):
    """Given remote mode, When the server is built, Then validate_token_resource
    is False rather than unset, because Auth0TokenVerifier checks the audience
    itself and SDK 3.0 will default this to True."""
    settings = auth_server.mcp.settings.auth

    assert settings is not None
    assert settings.validate_token_resource is False
