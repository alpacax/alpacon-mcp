"""Tests for the setup wizard's region validation."""

import json
import os
import stat
from unittest.mock import AsyncMock, patch

import pytest

from utils.setup_wizard import add_workspace, run_setup_wizard, save_config
from utils.setup_wizard import test_connection as run_test_connection
from utils.setup_wizard import test_credentials as run_test_credentials


class TestWizardRegionValidation:
    """An unserved region must be rejected before it is written to token.json."""

    @patch('utils.setup_wizard.print_mcp_config')
    @patch('utils.setup_wizard.test_connection', return_value=True)
    @patch('utils.setup_wizard.save_config')
    @patch('utils.setup_wizard.load_existing_config', return_value={})
    @patch('utils.setup_wizard.get_global_config_path')
    @patch('utils.setup_wizard.getpass', return_value='tok')
    @patch('builtins.input', return_value='eu1')
    def test_setup_rejects_unserved_region(
        self,
        mock_input,
        mock_getpass,
        mock_path,
        mock_load,
        mock_save,
        mock_conn,
        mock_cfg,
    ):
        with pytest.raises(SystemExit):
            run_setup_wizard()
        mock_save.assert_not_called()

    @patch('utils.setup_wizard.test_connection', return_value=True)
    @patch('utils.setup_wizard.save_config')
    @patch('utils.setup_wizard.load_existing_config', return_value={})
    @patch('utils.setup_wizard.get_global_config_path')
    @patch('utils.setup_wizard.getpass', return_value='tok')
    @patch('builtins.input', side_effect=['1', 'eu1', 'myws'])
    def test_add_workspace_rejects_unserved_region(
        self, mock_input, mock_getpass, mock_path, mock_load, mock_save, mock_conn
    ):
        add_workspace()
        mock_save.assert_not_called()

    @patch('utils.setup_wizard.test_connection', return_value=True)
    @patch('utils.setup_wizard.TokenManager')
    @patch('builtins.input', return_value='eu1')
    def test_test_credentials_rejects_unserved_region(
        self, mock_input, mock_tm, mock_conn
    ):
        run_test_credentials()
        mock_tm.assert_not_called()

    @patch('utils.setup_wizard.print_mcp_config')
    @patch('utils.setup_wizard.test_connection', return_value=True)
    @patch('utils.setup_wizard.save_config')
    @patch('utils.setup_wizard.load_existing_config', return_value={})
    @patch('utils.setup_wizard.get_global_config_path')
    @patch('utils.setup_wizard.getpass', return_value='tok')
    @patch('builtins.input', side_effect=['ap1', 'myws'])
    def test_setup_accepts_served_region(
        self,
        mock_input,
        mock_getpass,
        mock_path,
        mock_load,
        mock_save,
        mock_conn,
        mock_cfg,
    ):
        run_setup_wizard()
        mock_save.assert_called_once()


class TestConnectionResponseShape:
    """None and dicts carrying `error` fail the connection test; other shapes pass."""

    def test_connection_result_follows_response_shape(self, subtests):
        cases = [
            ({'error': 'unauthorized'}, False),
            ({'results': []}, True),
            ([{'id': 'srv'}], True),
            (None, False),
            (0, True),  # a scalar once raised TypeError on `in` and read as failure
        ]
        for response, expected in cases:
            with (
                subtests.test(response=response),
                patch(
                    'utils.setup_wizard.AlpaconHTTPClient.get',
                    new=AsyncMock(return_value=response),
                ),
            ):
                assert run_test_connection('ap1', 'myws', 'tok') is expected


def test_save_config_uses_atomic_private_writer(tmp_path):
    path = tmp_path / 'token.json'
    save_config({'ap1': {'prod': 'secret'}}, path)

    assert json.loads(path.read_text()) == {'ap1': {'prod': 'secret'}}
    if os.name == 'posix':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
