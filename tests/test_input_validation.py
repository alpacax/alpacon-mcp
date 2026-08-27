"""Tests for input validation wired into MCP tool functions."""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tools.alert_tools import update_alert_rule
from tools.cert_tools import (
    delete_certificate_authority,
    get_certificate_authority,
)
from tools.webftp_tools import webftp_download_file, webftp_upload_file
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
    param_parts = ['workspace: str', "region: str = ''"]
    for p in extra_params:
        if p in ('server_ids', 'servers'):
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
    async def test_empty_region_triggers_auto_detection(self):
        """Empty region triggers auto-detection from token.json or JWT instead of rejection."""
        func = _make_decorated_func()
        result = await func(workspace='demo', region='')
        # Empty region no longer causes a validation error on the 'region' field.
        # Instead, it triggers auto-detection which either resolves a region
        # or returns an error about missing tokens/regions.
        assert result['status'] == 'error'
        assert 'field' not in result or result.get('field') != 'region'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_valid_region_passes(self, mock_token):
        func = _make_decorated_func()
        result = await func(workspace='demo', region='ap1')
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_eu1_rejected(self):
        """eu1 is not a served region, so it fails validation instead of DNS.

        No token patch: rejection must happen before the token lookup.
        """
        func = _make_decorated_func()
        result = await func(workspace='demo', region='eu1')
        assert result['status'] == 'error'
        assert result['field'] == 'region'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_all_valid_regions_pass(self, mock_token):
        func = _make_decorated_func()
        for region in ('ap1', 'us1', 'dev'):
            result = await func(workspace='demo', region=region)
            assert result['status'] == 'success', f"Region '{region}' should be valid"


# ---------------------------------------------------------------------------
# Region auto-detection success paths
# ---------------------------------------------------------------------------


class TestRegionAutoDetection:
    """Tests that region auto-detection resolves correctly from token.json and JWT."""

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    @patch('utils.decorators._get_jwt_token', return_value=None)
    @patch('utils.token_manager.get_token_manager')
    async def test_single_region_auto_detected(self, mock_tm, mock_jwt, mock_token):
        """When token.json has exactly one region and workspace not found, falls back to default."""
        mock_manager = mock_tm.return_value
        mock_manager.find_region_for_workspace.return_value = None
        mock_manager.get_default_region.return_value = 'dev'

        func = _make_decorated_func()
        result = await func(workspace='demo', region='')
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    @patch('utils.decorators._get_jwt_token', return_value=None)
    @patch('utils.token_manager.get_token_manager')
    async def test_workspace_lookup_resolves_region(
        self, mock_tm, mock_jwt, mock_token
    ):
        """When workspace exists in exactly one region, auto-detection finds it."""
        mock_manager = mock_tm.return_value
        mock_manager.find_region_for_workspace.return_value = 'ap1'

        func = _make_decorated_func()
        result = await func(workspace='demo', region='')
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators._validate_jwt_workspace', return_value=True)
    @patch('utils.decorators._get_jwt_token')
    @patch('utils.decorators._resolve_region_from_jwt', return_value='dev')
    @patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'true'})
    async def test_jwt_mode_resolves_region(
        self, mock_resolve, mock_jwt, mock_validate
    ):
        """In JWT mode, region is resolved from JWT claims."""
        mock_jwt.return_value = 'header.payload.signature'

        func = _make_decorated_func()
        result = await func(workspace='demo', region='')
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators._get_jwt_token', return_value=None)
    @patch('utils.token_manager.get_token_manager')
    async def test_ambiguous_region_returns_error(self, mock_tm, mock_jwt):
        """When workspace exists in multiple regions and no default, auto-detection fails."""
        mock_manager = mock_tm.return_value
        mock_manager.find_region_for_workspace.return_value = None
        mock_manager.get_default_region.return_value = None
        mock_manager.get_available_regions.return_value = ['ap1', 'dev']

        func = _make_decorated_func()
        result = await func(workspace='demo', region='')
        assert result['status'] == 'error'
        # Should not be a 'region' field validation error, but a resolution error
        assert result.get('field') != 'region'


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

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_string_server_ids_rejected(self, mock_token):
        """A single string must fail fast, not be iterated character-by-character."""
        func = _make_decorated_func(extra_params=['server_ids'])
        result = await func(
            workspace='demo',
            region='ap1',
            server_ids='550e8400-e29b-41d4-a716-446655440000',
        )
        assert result['status'] == 'error'
        assert result['field'] == 'server_ids'
        # The whole string is reported, not a confusing list of single characters.
        assert result['value'] == '550e8400-e29b-41d4-a716-446655440000'


# ---------------------------------------------------------------------------
# servers list validation
# ---------------------------------------------------------------------------


class TestServersValidation:
    """Tests that invalid servers list values (server UUIDs) are rejected early."""

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_invalid_servers_rejected(self, mock_token):
        func = _make_decorated_func(extra_params=['servers'])
        result = await func(
            workspace='demo',
            region='ap1',
            servers=['not-a-uuid', 'also-bad'],
        )
        assert result['status'] == 'error'
        assert result['field'] == 'servers'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_mixed_servers_rejected(self, mock_token):
        func = _make_decorated_func(extra_params=['servers'])
        result = await func(
            workspace='demo',
            region='ap1',
            servers=[
                '550e8400-e29b-41d4-a716-446655440000',
                'not-a-uuid',
            ],
        )
        assert result['status'] == 'error'
        assert result['field'] == 'servers'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_valid_servers_passes(self, mock_token):
        func = _make_decorated_func(extra_params=['servers'])
        result = await func(
            workspace='demo',
            region='ap1',
            servers=[
                '550e8400-e29b-41d4-a716-446655440000',
                '660e8400-e29b-41d4-a716-446655440001',
            ],
        )
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_none_servers_passes(self, mock_token):
        func = _make_decorated_func(extra_params=['servers'])
        result = await func(workspace='demo', region='ap1', servers=None)
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_string_servers_rejected(self, mock_token):
        """A single string must fail fast, not be iterated character-by-character."""
        func = _make_decorated_func(extra_params=['servers'])
        result = await func(
            workspace='demo',
            region='ap1',
            servers='550e8400-e29b-41d4-a716-446655440000',
        )
        assert result['status'] == 'error'
        assert result['field'] == 'servers'
        # The whole string is reported, not a confusing list of single characters.
        assert result['value'] == '550e8400-e29b-41d4-a716-446655440000'


# ---------------------------------------------------------------------------
# Session ID validation
# ---------------------------------------------------------------------------


class TestSessionIdValidation:
    """Tests that invalid session_id values are rejected early.

    session_id is interpolated into URL paths (work_session_tools), so a
    non-UUID value (e.g. containing ``../`` or ``?``) must be rejected
    before any HTTP request is built.
    """

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_invalid_session_id_rejected(self, mock_token):
        func = _make_decorated_func(extra_params=['session_id'])
        result = await func(workspace='demo', region='ap1', session_id='not-a-uuid')
        assert result['status'] == 'error'
        assert result['field'] == 'session_id'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_path_traversal_session_id_rejected(self, mock_token):
        func = _make_decorated_func(extra_params=['session_id'])
        result = await func(
            workspace='demo', region='ap1', session_id='../other-endpoint'
        )
        assert result['status'] == 'error'
        assert result['field'] == 'session_id'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_valid_session_id_passes(self, mock_token):
        func = _make_decorated_func(extra_params=['session_id'])
        result = await func(
            workspace='demo',
            region='ap1',
            session_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_absent_session_id_passes(self, mock_token):
        """Not providing session_id at all should pass (other tools)."""
        func = _make_decorated_func(extra_params=['session_id'])
        result = await func(workspace='demo', region='ap1')
        assert result['status'] == 'success'


# ---------------------------------------------------------------------------
# Path-interpolated identifier validation
# ---------------------------------------------------------------------------


class TestPathIdentifierValidation:
    """Tests that identifiers interpolated into URL paths cannot retarget a request.

    ``http_client`` resolves endpoints with ``urljoin``, which treats ``..`` as a
    path climb, so an unvalidated value rewrites the endpoint the request reaches.
    """

    # server_id and session_id are absent: the decorator already validates them.
    PATH_IDENTIFIERS = [
        'acl_id',
        'alert_id',
        'analysis_id',
        'app_id',
        'ca_id',
        'certificate_id',
        'command_id',
        'csr_id',
        'entry_id',
        'event_id',
        'file_id',
        'group_id',
        'log_id',
        'membership_id',
        'note_id',
        'request_id',
        'revoke_id',
        'rule_id',
        'subscription_id',
        'token_id',
        'user_id',
        'webhook_id',
    ]

    TRAVERSAL_ID = '../../servers/servers/550e8400-e29b-41d4-a716-446655440000'

    # Each was observed rewriting the outgoing URL: bare '..' climbs a level and
    # '#' truncates the path, so rejecting only '../' leaves both open.
    RETARGETING_VALUES = [
        TRAVERSAL_ID,
        '..',
        '../certificates/abc',
        'a/b',
        'x?admin=true',
        'x#frag',
    ]

    # urljoin leaves these encoded, so the climb happens only once something
    # upstream decodes the path; rejecting them here keeps that off the wire.
    ENCODED_RETARGETING_VALUES = [
        '%2e%2e%2f%2e%2e%2fiam%2fusers',
        '%2E%2E%2Fiam%2Fusers',
        '%252e%252e%252fiam',
        'x%3Fadmin=true',
        'x%23frag',
    ]

    # Not a UUID on purpose: upstream routes detail endpoints with DRF's default
    # '[^/.]+' lookup, so the gate must not tighten these to a UUID.
    SAFE_ID = 'ca-1'

    # 'a..b' is not a dot-segment, so the gate must not reject it for holding '..'.
    SAFE_VALUES = [SAFE_ID, '550e8400-e29b-41d4-a716-446655440000', 'a..b', '~x']

    # Everything outside the unreserved set, plus the two dot-segments. The
    # trailing newlines are here because '$' also matches before a final one,
    # so an anchored search would let them through and httpx would raise
    # InvalidURL instead of the gate returning a validation error.
    UNRESERVED_VIOLATIONS = [
        '.',
        '..',
        'x:y',
        'a b',
        'x@y',
        '',
        'x+y',
        'abc\n',
        '..\n',
    ]

    # Not a str, so the pattern never runs—but the f-string that builds the
    # endpoint stringifies it anyway, putting the separators back in the path.
    NON_STRING_VALUES = [
        ['../../iam/users'],
        {'id': '../../iam/users'},
        ('../../iam/users',),
        123,
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize('field', PATH_IDENTIFIERS)
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_path_traversal_identifier_rejected(self, mock_token, field):
        func = _make_decorated_func(extra_params=[field])
        result = await func(
            workspace='demo', region='ap1', **{field: self.TRAVERSAL_ID}
        )
        assert result['status'] == 'error'
        assert result['field'] == field

    @pytest.mark.asyncio
    @pytest.mark.parametrize('value', RETARGETING_VALUES)
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_every_retargeting_shape_rejected(self, mock_token, value):
        func = _make_decorated_func(extra_params=['ca_id'])
        result = await func(workspace='demo', region='ap1', ca_id=value)
        assert result['status'] == 'error'
        assert result['field'] == 'ca_id'

    @pytest.mark.asyncio
    @pytest.mark.parametrize('value', ENCODED_RETARGETING_VALUES)
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_percent_encoded_retargeting_rejected(self, mock_token, value):
        func = _make_decorated_func(extra_params=['ca_id'])
        result = await func(workspace='demo', region='ap1', ca_id=value)
        assert result['status'] == 'error'
        assert result['field'] == 'ca_id'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_percent_encoded_traversal_never_reaches_http_client(
        self, mock_token
    ):
        with patch('tools.cert_tools.http_client') as mock_client:
            mock_client.get = AsyncMock(return_value={})

            result = await get_certificate_authority(
                ca_id='%2e%2e%2f%2e%2e%2fiam%2fusers',
                workspace='demo',
                region='ap1',
            )

        assert result['status'] == 'error'
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize('value', UNRESERVED_VIOLATIONS)
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_non_unreserved_identifier_rejected(self, mock_token, value):
        func = _make_decorated_func(extra_params=['ca_id'])
        result = await func(workspace='demo', region='ap1', ca_id=value)
        assert result['status'] == 'error'
        assert result['field'] == 'ca_id'

    @pytest.mark.asyncio
    @pytest.mark.parametrize('value', NON_STRING_VALUES)
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_non_string_identifier_rejected(self, mock_token, value):
        func = _make_decorated_func(extra_params=['ca_id'])
        result = await func(workspace='demo', region='ap1', ca_id=value)
        assert result['status'] == 'error'
        assert result['field'] == 'ca_id'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_non_string_traversal_never_reaches_http_client(self, mock_token):
        with patch('tools.cert_tools.http_client') as mock_client:
            mock_client.get = AsyncMock(return_value={})

            result = await get_certificate_authority(
                ca_id=['../../iam/users'],
                workspace='demo',
                region='ap1',
            )

        assert result['status'] == 'error'
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_omitted_identifier_still_accepted(self, mock_token):
        # An optional identifier defaults to None, which means the argument was
        # never sent—the gate must let it through rather than read it as a type
        # violation.
        func = _make_decorated_func(extra_params=['ca_id'])
        result = await func(workspace='demo', region='ap1')
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @pytest.mark.parametrize('value', SAFE_VALUES)
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_safe_non_uuid_identifier_still_accepted(self, mock_token, value):
        func = _make_decorated_func(extra_params=['ca_id'])
        result = await func(workspace='demo', region='ap1', ca_id=value)
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_padded_work_session_id_still_accepted(self, mock_token):
        # Never in a path: it is sent in the request body after
        # resolve_work_session_id strips it, and the same padded value through
        # ALPACON_WORK_SESSION never meets the gate, so rejecting it here
        # would make the argument stricter than the env var route.
        func = _make_decorated_func(extra_params=['work_session_id'])
        result = await func(
            workspace='demo',
            region='ap1',
            work_session_id=' 550e8400-e29b-41d4-a716-446655440000\n',
        )
        assert result['status'] == 'success'

    # 'result' holds an API response, not an argument the client sends.
    NON_ARGUMENT_NAMES = frozenset({'result'})

    # Each picks a whole endpoint out of a fixed set of constants, so nothing the
    # client sends is interpolated into the path. Matched by source text, so a
    # rename lands here as a failure: re-read the site before re-adding it, and
    # never grow this set just to turn the test green.
    ENDPOINT_CHOICES = frozenset(
        {
            'metrics_tools.py: metric_endpoints[metric]',
            'security_tools.py: endpoint',
            'webftp_tools.py: endpoint_map[transfer_type]',
        }
    )

    def test_every_interpolated_endpoint_name_ends_in_id(self):
        """The gate matches on an ``_id`` suffix, so a path parameter named
        otherwise would reach the URL unchecked.

        Walks the syntax tree rather than the text, so a path built any other
        way—``.format()``, a template constant used bare—is caught too. A way of
        building an endpoint that this does not recognize fails as well: it has
        to be read before it can be trusted.

        What this holds is the naming convention at the interpolation site:
        the name read there ends in ``_id``. It does not trace where the value
        came from, so a client value rebound to a local ``_id`` name, or one
        smuggled into a constant behind an ``ENDPOINT_CHOICES`` entry, passes
        unseen. That provenance is what review is for.
        """

        def root_name(node):
            """The leftmost name an expression reads, or None."""
            while isinstance(node, ast.Attribute | ast.Subscript):
                node = node.value
            if isinstance(node, ast.Call):
                return root_name(node.func)
            return node.id if isinstance(node, ast.Name) else None

        def fold(node, table):
            """The string a module-level expression resolves to, or None."""
            if isinstance(node, ast.Constant):
                return node.value if isinstance(node.value, str) else None
            if isinstance(node, ast.Name):
                return table.get(node.id)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                left, right = fold(node.left, table), fold(node.right, table)
                return None if left is None or right is None else left + right
            if isinstance(node, ast.JoinedStr):
                pieces = [
                    fold(
                        part.value if isinstance(part, ast.FormattedValue) else part,
                        table,
                    )
                    for part in node.values
                ]
                return None if None in pieces else ''.join(pieces)
            return None

        tools_dir = Path(__file__).resolve().parent.parent / 'tools'
        unchecked = set()

        for module in sorted(tools_dir.glob('*.py')):
            tree = ast.parse(module.read_text(encoding='utf-8'), str(module))

            # Anything assigned at module level is fixed at import, so it is
            # never a value the client sent. Only the strings can be resolved.
            module_names, constants = set(), {}
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                resolved = fold(node.value, constants)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_names.add(target.id)
                        if resolved is not None:
                            constants[target.id] = resolved

            def report(what, module=module, unchecked=unchecked):
                unchecked.add(f'{module.name}: {what}')

            def check_name(node, report=report, module_names=module_names):
                name = root_name(node)
                exempt = module_names | self.NON_ARGUMENT_NAMES
                if name is None:
                    report(f'{ast.unparse(node)} (reads no name)')
                elif not name.endswith('_id') and name not in exempt:
                    report(name)

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != 'endpoint':
                        continue
                    value = keyword.value
                    resolved = fold(value, constants)
                    if resolved is not None:
                        # A '{}' left in a resolved path is a template, so the
                        # value filling it never passed through this check.
                        if '{' in resolved:
                            report(f'{ast.unparse(value)} (template used bare)')
                    elif isinstance(value, ast.JoinedStr):
                        for part in value.values:
                            if isinstance(part, ast.FormattedValue):
                                check_name(part.value)
                    elif (
                        isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Attribute)
                        and value.func.attr == 'format'
                    ):
                        for arg in value.args:
                            check_name(arg)
                    elif (
                        f'{module.name}: {ast.unparse(value)}' in self.ENDPOINT_CHOICES
                    ):
                        continue
                    else:
                        report(f'{ast.unparse(value)} (unrecognized endpoint shape)')

        assert not unchecked, (
            'These reach an endpoint path but skip the _id gate in '
            f'with_token_validation: {sorted(unchecked)}'
        )

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_absent_identifier_accepted(self, mock_token):
        func = _make_decorated_func(extra_params=['ca_id'])
        result = await func(workspace='demo', region='ap1')
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_traversal_ca_id_never_reaches_http_client(self, mock_token):
        with patch('tools.cert_tools.http_client') as mock_client:
            mock_client.delete = AsyncMock(return_value={})

            result = await delete_certificate_authority(
                ca_id=self.TRAVERSAL_ID,
                workspace='demo',
                region='ap1',
            )

        assert result['status'] == 'error'
        mock_client.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_traversal_ca_id_cannot_read_another_endpoint(self, mock_token):
        with patch('tools.cert_tools.http_client') as mock_client:
            mock_client.get = AsyncMock(return_value={})

            result = await get_certificate_authority(
                ca_id='../../iam/users',
                workspace='demo',
                region='ap1',
            )

        assert result['status'] == 'error'
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_traversal_rule_id_cannot_retarget_update(self, mock_token):
        """An update tool retargets only once a body field is supplied."""
        with patch('tools.alert_tools.http_client') as mock_client:
            mock_client.patch = AsyncMock(return_value={})

            result = await update_alert_rule(
                rule_id=self.TRAVERSAL_ID,
                workspace='demo',
                region='ap1',
                name='renamed',
            )

        assert result['status'] == 'error'
        mock_client.patch.assert_not_called()


# ---------------------------------------------------------------------------
# File path validation (webftp_tools inline validation)
# ---------------------------------------------------------------------------


class TestFilePathValidation:
    """Tests that invalid file paths are rejected in webftp upload/download."""

    @pytest.mark.asyncio
    @patch('utils.decorators.validate_token', return_value='fake-token')
    async def test_upload_rejects_relative_local_path(self, mock_token):
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
    async def test_workspace_checked_before_region(self):
        """Both region and workspace are invalid; workspace error comes first
        because workspace is needed for region auto-detection."""
        func = _make_decorated_func()
        result = await func(workspace='bad workspace!', region='zzz')
        assert result['field'] == 'workspace'

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
