"""Unit tests for agent action tools in server_tools module."""

import inspect
from http import HTTPStatus

import pytest

from server import mcp
from tests.conftest import HTTP_ERROR_ENVELOPE, http_client_fixture, tool_descriptions
from tools.server_tools import (
    install_pam,
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
        (install_pam, 'install_pam'),
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
    @pytest.mark.asyncio
    async def test_restart_agent_success(self, mock_http_client, mock_token_manager):
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
    @pytest.mark.asyncio
    async def test_upgrade_agent_success(self, mock_http_client, mock_token_manager):
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
        mock_token_manager.get_token.return_value = None

        result = await upgrade_agent(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()


class TestInstallPam:
    @pytest.mark.asyncio
    async def test_install_pam_success(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = {'id': 'cmd-1'}

        result = await install_pam(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/actions/',
            token='test-token',
            data={'action': 'install_pam', 'force': False},
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ('status_code', 'code'),
        [
            (HTTPStatus.BAD_REQUEST, 'server_pam_install_unsupported'),
            (HTTPStatus.BAD_REQUEST, 'server_pam_install_requires_sudo_with_mfa'),
            (HTTPStatus.CONFLICT, 'server_pam_install_in_progress'),
        ],
    )
    async def test_install_pam_refusal_surfaces_error_code(
        self, status_code, code, mock_http_client, mock_token_manager
    ):
        """Each refusal is a plain error carrying its code, as the changelog promises."""
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': status_code,
            'message': f"Client error '{status_code.value} {status_code.phrase}'",
            'response': f'{{"code":"{code}"}}',
        }

        result = await install_pam(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['status_code'] == status_code
        assert result['error_code'] == code

    @pytest.mark.asyncio
    async def test_install_pam_description_names_every_refusal(self):
        """An agent explains a refusal from the description, so each code is in it."""
        descriptions = await tool_descriptions()

        description = descriptions['install_pam']
        for code in (
            'server_pam_install_requires_sudo_with_mfa',
            'server_pam_install_unsupported',
            'server_pam_install_in_progress',
        ):
            assert code in description


class TestUpdateInformation:
    @pytest.mark.asyncio
    async def test_update_information_success(
        self, mock_http_client, mock_token_manager
    ):
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

    def test_install_pam_has_no_force(self):
        """install_pam leaves live sessions alone server-side, so it offers no force."""
        assert 'force' not in inspect.signature(install_pam).parameters

    @pytest.mark.asyncio
    async def test_every_disruptive_description_carries_the_force_note(self):
        """The note lives in one constant; a client must still read it on both tools."""
        descriptions = await tool_descriptions()

        for _, action in self.DISRUPTIVE:
            description = descriptions[action]
            assert (
                'pass force=True to run anyway, which tears that live work down.'
                in description
            )
        update_description = descriptions['update_information']
        pam_description = descriptions['install_pam']
        assert 'force=True' not in update_description
        assert 'force=True' not in pam_description

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
