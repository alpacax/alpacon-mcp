"""Auth settings this deployment pins deliberately."""

import pytest
from mcp.server.apps import EXTENSION_ID
from mcp.server.request_state import AESGCMRequestStateCodec, RequestStateBoundary

import server
from utils.client_surfaces import bind_tool_call_round


@pytest.fixture
def remote_env(monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'true')
    monkeypatch.setenv('AUTH0_ALPACON_DOMAIN', 'example.us.auth0.com')
    monkeypatch.setenv('ALPACON_MCP_RESOURCE_URL', 'https://mcp.example.com')


def test_token_resource_validation_is_explicitly_disabled(remote_env):
    """Given remote mode, When the server is built, Then validate_token_resource is
    False: Auth0TokenVerifier checks the audience, and SDK 3.0 will default it to True.
    """

    server_instance = server._create_mcp_server()
    settings = server_instance.settings.auth

    assert settings is not None
    assert settings.validate_token_resource is False


def test_remote_server_seals_request_state_for_every_replica(remote_env):

    middleware = server._create_mcp_server()._lowlevel_server.middleware

    boundary = next(m for m in middleware if isinstance(m, RequestStateBoundary))
    assert isinstance(boundary._security.codec, AESGCMRequestStateCodec)


def test_round_is_bound_inside_the_request_state_boundary(remote_env):
    """The round must read the requestState the boundary already verified and opened."""

    middleware = server._create_mcp_server()._lowlevel_server.middleware

    boundary = next(
        i for i, m in enumerate(middleware) if isinstance(m, RequestStateBoundary)
    )
    assert boundary < middleware.index(bind_tool_call_round)


def _advertised_extensions(server_instance):
    options = server_instance._lowlevel_server.create_initialization_options()
    return options.capabilities.extensions or {}


def test_remote_mode_advertises_mcp_apps(remote_env):
    server_instance = server._create_mcp_server()

    assert EXTENSION_ID in _advertised_extensions(server_instance)


def test_local_mode_does_not_advertise_mcp_apps(monkeypatch):
    monkeypatch.delenv('ALPACON_MCP_AUTH_ENABLED', raising=False)

    server_instance = server._create_mcp_server()

    assert EXTENSION_ID not in _advertised_extensions(server_instance)
