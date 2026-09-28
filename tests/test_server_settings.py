"""Auth settings this deployment pins deliberately."""

import server


def test_token_resource_validation_is_explicitly_disabled(monkeypatch):
    """Given remote mode, When the server is built, Then validate_token_resource
    is False rather than unset, because Auth0TokenVerifier checks the audience
    itself and SDK 3.0 will default this to True."""
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'true')
    monkeypatch.setenv('AUTH0_DOMAIN', 'example.us.auth0.com')
    monkeypatch.setenv('ALPACON_MCP_RESOURCE_URL', 'https://mcp.example.com')

    server_instance = server._create_mcp_server()
    settings = server_instance.settings.auth

    assert settings is not None
    assert settings.validate_token_resource is False
