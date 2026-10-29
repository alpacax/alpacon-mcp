"""The stdio installation's device id and the ledger device flow that sends it."""

from unittest.mock import AsyncMock, patch

import pytest

from utils.device_id import (
    DEVICE_ID_FILE,
    installation_device_id,
    is_device_id,
    mint_device_id,
)
from utils.ledger_auth import LedgerAuthorizer, LedgerTarget


class TestInstallationDeviceId:
    def test_minted_once_and_kept(self, tmp_path):
        first = installation_device_id(tmp_path)
        assert is_device_id(first)
        assert (tmp_path / DEVICE_ID_FILE).read_text().strip() == first
        assert installation_device_id(tmp_path) == first

    def test_the_file_is_private(self, tmp_path):
        installation_device_id(tmp_path)
        assert (tmp_path / DEVICE_ID_FILE).stat().st_mode & 0o777 == 0o600

    @pytest.mark.parametrize(
        'stored', ['', 'short', 'has space in it', 'x' * 65, 'a/b' * 4]
    )
    def test_an_invalid_stored_id_is_replaced(self, tmp_path, stored):
        (tmp_path / DEVICE_ID_FILE).write_text(stored)
        replaced = installation_device_id(tmp_path)
        assert is_device_id(replaced)
        assert replaced != stored
        assert (tmp_path / DEVICE_ID_FILE).read_text().strip() == replaced

    def test_a_valid_stored_id_is_kept_as_is(self, tmp_path):
        (tmp_path / DEVICE_ID_FILE).write_text('cli-style-id-1234\n')
        assert installation_device_id(tmp_path) == 'cli-style-id-1234'

    def test_an_unwritable_directory_still_yields_an_id(self, tmp_path):
        blocked = tmp_path / 'file-not-dir'
        blocked.write_text('')
        assert is_device_id(installation_device_id(blocked))

    def test_defaults_to_the_token_config_directory(self, isolated_device_id_dir):
        device_id = installation_device_id()
        stored = (isolated_device_id_dir / DEVICE_ID_FILE).read_text().strip()
        assert stored == device_id

    def test_minted_ids_are_random(self):
        assert mint_device_id() != mint_device_id()


@pytest.mark.asyncio
async def test_the_stdio_ledger_device_flow_sends_the_installation_id(
    isolated_device_id_dir,
):
    target = LedgerTarget(
        domain='auth.example.com', client_id='cli', org_name='acme', workspace_id='w'
    )
    post = AsyncMock(
        return_value=(
            200,
            {
                'device_code': 'd',
                'user_code': 'U',
                'verification_uri': 'https://auth.example.com/activate',
                'interval': 5,
                'expires_in': 900,
            },
        )
    )
    with patch('utils.ledger_auth._post_form', post):
        await LedgerAuthorizer().token_for(target)
        await LedgerAuthorizer().token_for(target)

    scopes = [call.args[1]['scope'].split() for call in post.call_args_list]
    stored = (isolated_device_id_dir / DEVICE_ID_FILE).read_text().strip()
    for scope in scopes:
        assert scope[:4] == ['openid', 'profile', 'email', 'org:acme']
        assert [p for p in scope if p.startswith('device:')] == [f'device:{stored}']
