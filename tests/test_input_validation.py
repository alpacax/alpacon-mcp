"""Tests for input validation wired into MCP tool functions."""

from unittest.mock import patch

import pytest

from utils.decorators import with_token_validation

# --- Helper: create a dummy async function decorated with with_token_validation ---


def _make_decorated_func(extra_params=None):
    """Build a minimal async function wrapped by with_token_validation.

    Args:
        extra_params: list of extra keyword arg names the inner function accepts
                      (e.g. ["server_id", "server_ids"])
    """
    extra_params = extra_params or []

    # Dynamically build the function signature string
    param_parts = ['workspace: str', "region: str = 'ap1'"]
    for p in extra_params:
        if p == 'server_ids':
            param_parts.append(f'{p}: list = None')
        else:
            param_parts.append(f'{p}: str = None')
    param_parts.append('**kwargs')
    sig = ', '.join(param_parts)

    func_code = f"async def _inner({sig}):\n    return {{'status': 'success', 'token': kwargs.get('token')}}"
    namespace: dict = {}
    exec(func_code, namespace)  # noqa: S102
    return with_token_validation(namespace['_inner'])


# ---------------------------------------------------------------------------
# Region validation
# ---------------------------------------------------------------------------


class TestRegionValidation:
    """Tests that invalid region values are rejected early."""

    @pytest.mark.asyncio
    async def test_invalid_region_rejected(self):
        func = _make_decorated_func()
        result = await func(workspace='demo', region='invalid-region')
        assert result['status'] == 'error'
        assert result['field'] == 'region'

    @pytest.mark.asyncio
    async def test_empty_region_rejected(self):
        func = _make_decorated_func()
        result = await func(workspace='demo', region='')
        assert result['status'] == 'error'
        assert result['field'] == 'region'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_valid_region_passes(self, mock_token):
        func = _make_decorated_func()
        result = await func(workspace='demo', region='ap1')
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_all_valid_regions_pass(self, mock_token):
        func = _make_decorated_func()
        for region in ('ap1', 'us1', 'eu1', 'dev'):
            result = await func(workspace='demo', region=region)
            assert result['status'] == 'success', f"Region '{region}' should be valid"


# ---------------------------------------------------------------------------
# Workspace validation
# ---------------------------------------------------------------------------


class TestWorkspaceValidation:
    """Tests that invalid workspace values are rejected early."""

    @pytest.mark.asyncio
    async def test_missing_workspace_rejected(self):
        func = _make_decorated_func()
        result = await func(workspace='', region='ap1')
        # Empty workspace fails region first? No—region is valid, workspace
        # empty string passes region check but fails workspace required check
        # Actually empty string is falsy, so "workspace is required" fires first
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_workspace_with_spaces_rejected(self):
        func = _make_decorated_func()
        result = await func(workspace='my workspace', region='ap1')
        assert result['status'] == 'error'
        assert result['field'] == 'workspace'

    @pytest.mark.asyncio
    async def test_workspace_with_special_chars_rejected(self):
        func = _make_decorated_func()
        result = await func(workspace='ws@#$!', region='ap1')
        assert result['status'] == 'error'
        assert result['field'] == 'workspace'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_valid_workspace_passes(self, mock_token):
        func = _make_decorated_func()
        result = await func(workspace='my-workspace', region='ap1')
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_single_char_workspace_passes(self, mock_token):
        func = _make_decorated_func()
        result = await func(workspace='a', region='ap1')
        assert result['status'] == 'success'


# ---------------------------------------------------------------------------
# Server ID validation
# ---------------------------------------------------------------------------


class TestServerIdValidation:
    """Tests that invalid server_id values are rejected early."""

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_invalid_server_id_rejected(self, mock_token):
        func = _make_decorated_func(extra_params=['server_id'])
        result = await func(workspace='demo', region='ap1', server_id='not-a-uuid')
        assert result['status'] == 'error'
        assert result['field'] == 'server_id'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_valid_server_id_passes(self, mock_token):
        func = _make_decorated_func(extra_params=['server_id'])
        result = await func(
            workspace='demo',
            region='ap1',
            server_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_none_server_id_passes(self, mock_token):
        """server_id=None should be skipped (optional parameter)."""
        func = _make_decorated_func(extra_params=['server_id'])
        result = await func(workspace='demo', region='ap1', server_id=None)
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_absent_server_id_passes(self, mock_token):
        """Not providing server_id at all should pass."""
        func = _make_decorated_func(extra_params=['server_id'])
        result = await func(workspace='demo', region='ap1')
        assert result['status'] == 'success'


# ---------------------------------------------------------------------------
# Server IDs list validation
# ---------------------------------------------------------------------------


class TestServerIdsValidation:
    """Tests that invalid server_ids list values are rejected early."""

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_invalid_server_ids_rejected(self, mock_token):
        func = _make_decorated_func(extra_params=['server_ids'])
        result = await func(
            workspace='demo',
            region='ap1',
            server_ids=['not-a-uuid', 'also-bad'],
        )
        assert result['status'] == 'error'
        assert result['field'] == 'server_ids'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_mixed_server_ids_rejected(self, mock_token):
        func = _make_decorated_func(extra_params=['server_ids'])
        result = await func(
            workspace='demo',
            region='ap1',
            server_ids=[
                '550e8400-e29b-41d4-a716-446655440000',
                'not-a-uuid',
            ],
        )
        assert result['status'] == 'error'
        assert result['field'] == 'server_ids'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_valid_server_ids_passes(self, mock_token):
        func = _make_decorated_func(extra_params=['server_ids'])
        result = await func(
            workspace='demo',
            region='ap1',
            server_ids=[
                '550e8400-e29b-41d4-a716-446655440000',
                '660e8400-e29b-41d4-a716-446655440001',
            ],
        )
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_none_server_ids_passes(self, mock_token):
        func = _make_decorated_func(extra_params=['server_ids'])
        result = await func(workspace='demo', region='ap1', server_ids=None)
        assert result['status'] == 'success'


# ---------------------------------------------------------------------------
# File path validation (webftp_tools inline validation)
# ---------------------------------------------------------------------------


class TestFilePathValidation:
    """Tests that invalid file paths are rejected in webftp upload/download."""

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_upload_rejects_relative_local_path(self, mock_token):
        from tools.webftp_tools import webftp_upload_file

        result = await webftp_upload_file(
            server_id='550e8400-e29b-41d4-a716-446655440000',
            local_file_path='relative/path.txt',
            remote_file_path='/home/user/file.txt',
            workspace='demo',
            region='ap1',
        )
        assert result['status'] == 'error'
        assert result['field'] == 'local_file_path'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_upload_rejects_traversal_in_remote_path(self, mock_token):
        from tools.webftp_tools import webftp_upload_file

        result = await webftp_upload_file(
            server_id='550e8400-e29b-41d4-a716-446655440000',
            local_file_path='/tmp/safe.txt',
            remote_file_path='/home/user/../../../etc/passwd',
            workspace='demo',
            region='ap1',
        )
        assert result['status'] == 'error'
        assert result['field'] == 'remote_file_path'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_download_rejects_relative_remote_path(self, mock_token):
        from tools.webftp_tools import webftp_download_file

        result = await webftp_download_file(
            server_id='550e8400-e29b-41d4-a716-446655440000',
            remote_file_path='relative/path.log',
            local_file_path='/tmp/download.log',
            workspace='demo',
            region='ap1',
        )
        assert result['status'] == 'error'
        assert result['field'] == 'remote_file_path'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_download_rejects_traversal_in_local_path(self, mock_token):
        from tools.webftp_tools import webftp_download_file

        result = await webftp_download_file(
            server_id='550e8400-e29b-41d4-a716-446655440000',
            remote_file_path='/var/log/app.log',
            local_file_path='/tmp/../../../etc/evil',
            workspace='demo',
            region='ap1',
        )
        assert result['status'] == 'error'
        assert result['field'] == 'local_file_path'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_upload_rejects_null_byte_path(self, mock_token):
        from tools.webftp_tools import webftp_upload_file

        result = await webftp_upload_file(
            server_id='550e8400-e29b-41d4-a716-446655440000',
            local_file_path='/tmp/file\x00.txt',
            remote_file_path='/home/user/file.txt',
            workspace='demo',
            region='ap1',
        )
        assert result['status'] == 'error'
        assert result['field'] == 'local_file_path'


# ---------------------------------------------------------------------------
# Validation order: region → workspace → token → server_id
# ---------------------------------------------------------------------------


class TestValidationOrder:
    """Verify that validation fires in the correct order."""

    @pytest.mark.asyncio
    async def test_region_checked_before_workspace(self):
        """Both region and workspace are invalid; region error should come first."""
        func = _make_decorated_func()
        result = await func(workspace='bad workspace!', region='zzz')
        assert result['field'] == 'region'

    @pytest.mark.asyncio
    async def test_workspace_checked_before_server_id(self):
        """Workspace is invalid, server_id is also invalid; workspace error first."""
        func = _make_decorated_func(extra_params=['server_id'])
        result = await func(
            workspace='bad workspace!',
            region='ap1',
            server_id='not-a-uuid',
        )
        assert result['field'] == 'workspace'
