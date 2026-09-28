"""Unit tests for agent action tools in server_tools module."""

import inspect

import pytest

from server import mcp
from tests.conftest import HTTP_ERROR_ENVELOPE, http_client_fixture
from tools.server_tools import (
    restart_agent,
    update_information,
    upgrade_agent,
)

mock_http_client = http_client_fixture('tools.server_tools')


SERVER_ID = '550e8400-e29b-41d4-a716-446655440123'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('tool', 'action'),
    [
        (restart_agent, 'restart_agent'),
        (upgrade_agent, 'upgrade_agent'),
        (update_information, 'update_information'),
    ],
)
async def test_agent_action_http_error_envelope_returns_error(
    tool, action, mock_http_client, mock_token_manager
):
    mock_http_client.post.return_value = HTTP_ERROR_ENVELOPE

    result = await tool(server_id=SERVER_ID, workspace='testworkspace', region='ap1')

    assert result['status'] == 'error'
    assert result['message'] == HTTP_ERROR_ENVELOPE['message']
    assert result['status_code'] == HTTP_ERROR_ENVELOPE['status_code']
    assert result['server_id'] == SERVER_ID
    assert result['region'] == 'ap1'
    assert result['workspace'] == 'testworkspace'
    mock_http_client.post.assert_called_once_with(
        region='ap1',
        workspace='testworkspace',
        endpoint=f'/api/servers/servers/{SERVER_ID}/actions/',
        token='test-token',
        data={'action': action, 'force': False},
    )


class TestRestartAgent:
    """Test agent restart functionality."""

    @pytest.mark.asyncio
    async def test_restart_agent_success(self, mock_http_client, mock_token_manager):
        """Test successful agent restart."""
        mock_http_client.post.return_value = {'status': 'restarting'}

        result = await restart_agent(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/actions/',
            token='test-token',
            data={'action': 'restart_agent', 'force': False},
        )


class TestUpgradeAgent:
    """Test agent upgrade functionality."""

    @pytest.mark.asyncio
    async def test_upgrade_agent_success(self, mock_http_client, mock_token_manager):
        """Test successful agent upgrade."""
        mock_http_client.post.return_value = {'status': 'upgrading'}

        result = await upgrade_agent(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/actions/',
            token='test-token',
            data={'action': 'upgrade_agent', 'force': False},
        )

    @pytest.mark.asyncio
    async def test_upgrade_agent_no_token(self, mock_http_client, mock_token_manager):
        """Test agent upgrade with no token."""
        mock_token_manager.get_token.return_value = None

        result = await upgrade_agent(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()


class TestUpdateInformation:
    """Test system information update functionality."""

    @pytest.mark.asyncio
    async def test_update_information_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful system information update."""
        mock_http_client.post.return_value = {'status': 'updating'}

        result = await update_information(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/actions/',
            token='test-token',
            data={'action': 'update_information', 'force': False},
        )


class TestDisruptiveActionForce:
    """Tests for the force flag on disruptive server actions."""

    DISRUPTIVE = [
        (restart_agent, 'restart_agent'),
        (upgrade_agent, 'upgrade_agent'),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(('tool', 'action'), DISRUPTIVE)
    async def test_force_defaults_to_false(
        self, tool, action, mock_http_client, mock_token_manager
    ):
        """Every disruptive action sends force, defaulting to False."""
        mock_http_client.post.return_value = {'id': 'cmd-1'}

        result = await tool(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/actions/',
            token='test-token',
            data={
                'action': action,
                'force': False,
            },
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(('tool', 'action'), DISRUPTIVE)
    async def test_force_true_is_forwarded(
        self, tool, action, mock_http_client, mock_token_manager
    ):
        """force=True reaches the server, which is what gets past a busy host."""
        mock_http_client.post.return_value = {'id': 'cmd-1'}

        await tool(
            server_id=SERVER_ID,
            workspace='testworkspace',
            region='ap1',
            force=True,
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/actions/',
            token='test-token',
            data={
                'action': action,
                'force': True,
            },
        )

    def test_update_information_has_no_force(self):
        """update_information is not disruptive server-side, so it offers no force."""
        assert 'force' not in inspect.signature(update_information).parameters

    @pytest.mark.asyncio
    async def test_every_disruptive_description_carries_the_force_note(self):
        """The note lives in one constant; a client must still read it on both tools."""
        descriptions = {t.name: t.description for t in await mcp.list_tools()}

        for _, action in self.DISRUPTIVE:
            assert (
                'pass force=True to run anyway, which tears that live work down.'
                in descriptions[action]
            )
        assert 'force=True' not in descriptions['update_information']

    @pytest.mark.asyncio
    async def test_removed_tools_are_not_registered(self):
        """A future accidental re-registration of a removed tool must fail this test."""
        names = {t.name for t in await mcp.list_tools()}

        for removed in (
            'shutdown_agent',
            'upgrade_system',
            'reboot_system',
            'shutdown_system',
        ):
            assert removed not in names
