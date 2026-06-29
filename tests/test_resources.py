"""Tests for alpacon:// MCP resources."""

import pytest

from server import mcp


async def _registered_uris():
    """All registered alpacon:// URIs — templated (with {params}) and static."""
    templates = {t.uriTemplate for t in await mcp.list_resource_templates()}
    static = {str(r.uri) for r in await mcp.list_resources()}
    return templates | static


class TestResourceRegistration:
    @pytest.mark.asyncio
    async def test_helper_registers_and_reads(self):
        """register_resource builds a real-signature wrapper that reads through."""
        import tools.resources as res

        captured = {}

        async def fake_fn(region, workspace, alert_id):
            captured['args'] = (region, workspace, alert_id)
            return {'ok': True}

        res.register_resource(
            'alpacon://test/{region}/{workspace}/{alert_id}', fake_fn, 'test_probe'
        )

        contents = await mcp.read_resource('alpacon://test/ap1/ws/abc')
        assert captured['args'] == ('ap1', 'ws', 'abc')
        assert contents  # non-empty content list

    @pytest.mark.asyncio
    async def test_helper_passes_extra_kwargs(self):
        """extra kwargs are forwarded to the backing function."""
        import tools.resources as res

        captured = {}

        async def fake_fn(region, workspace, acknowledged=None):
            captured['ack'] = acknowledged
            return {'ok': True}

        res.register_resource(
            'alpacon://test-extra/{region}/{workspace}',
            fake_fn,
            'test_extra_probe',
            {'acknowledged': False},
        )

        await mcp.read_resource('alpacon://test-extra/ap1/ws')
        assert captured['ack'] is False

    @pytest.mark.asyncio
    async def test_extra_kwargs_without_path_params(self):
        """No path params + extra must not emit a leading-comma SyntaxError."""
        import tools.resources as res

        captured = {}

        async def fake_fn(flag=None):
            captured['flag'] = flag
            return {'ok': True}

        res.register_resource(
            'alpacon://test-noparam', fake_fn, 'test_noparam_probe', {'flag': True}
        )

        await mcp.read_resource('alpacon://test-noparam')
        assert captured['flag'] is True

    @pytest.mark.asyncio
    async def test_all_resources_registered(self):
        """Every RESOURCES entry is registered, no dup, no legacy scheme."""
        import tools.resources as res

        uris = await _registered_uris()
        table_uris = {uri for _n, _f, uri in res.RESOURCES}

        assert table_uris <= uris
        assert 'alpacon://alerts/active/{region}/{workspace}' in uris  # extra-kwarg one
        assert not any(u.startswith(('webftp://', 'iam://')) for u in uris)
        assert 'alpacon://webftp/sessions/{region}/{workspace}' in uris
        assert 'alpacon://iam/users/{region}/{workspace}' in uris
        assert len(table_uris) == len(res.RESOURCES)

    @pytest.mark.asyncio
    async def test_literal_subresources_not_shadowed(self):
        """A literal sub-path (e.g. /active/) must not be captured by a sibling
        {id} wildcard — resolve to the right tool, not the detail route."""
        import tools.resources  # noqa: F401  # registers resources on import

        mgr = mcp._resource_manager
        cases = {
            'alpacon://alerts/active/ap1/ws': 'alerts_active',
            'alpacon://certs/revoke-requests/ap1/ws': 'cert_revoke_requests_list',
            'alpacon://tokens/scopes/ap1/ws': 'token_scopes',
            'alpacon://tokens/presets/ap1/ws': 'token_presets',
            'alpacon://alerts/ap1/ws/some-id': 'alert_detail',  # detail still works
        }
        for uri, want in cases.items():
            resource = await mgr.get_resource(uri)
            assert resource.name == want, f'{uri} -> {resource.name}, want {want}'
