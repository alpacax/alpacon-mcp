"""Tests for alpacon:// MCP resources."""

import inspect
import re

import pytest

import tools.resources as res
from server import ALL_TOOL_MODULES, ALWAYS_ON_MODULES, mcp


@pytest.fixture(scope='module', autouse=True)
def _register_all_resources():
    """Resources are no longer registered at import time."""
    res.register_resources(set(ALL_TOOL_MODULES) | ALWAYS_ON_MODULES)


async def _registered_uris():
    """All registered alpacon:// URIs — templated (with {params}) and static."""
    templates = {t.uriTemplate for t in await mcp.list_resource_templates()}
    static = {str(r.uri) for r in await mcp.list_resources()}
    return templates | static


class TestResourceRegistration:
    @pytest.mark.asyncio
    async def test_helper_registers_and_reads(self):
        """register_resource builds a real-signature wrapper that reads through."""
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
        uris = await _registered_uris()
        table_uris = {uri for _n, _ref, uri in res.RESOURCES}

        assert table_uris <= uris
        assert 'alpacon://alerts/active/{region}/{workspace}' in uris  # extra-kwarg one
        assert not any(u.startswith(('webftp://', 'iam://')) for u in uris)
        assert 'alpacon://webftp/sessions/{region}/{workspace}' in uris
        assert 'alpacon://iam/users/{region}/{workspace}' in uris
        assert len(table_uris) == len(res.RESOURCES)

    @pytest.mark.asyncio
    async def test_filtered_resource_describes_its_pin(self):
        """A resource registered with extra kwargs must surface the pinned
        filter in its description, not just inherit the tool docstring."""
        active = next(
            t
            for t in await mcp.list_resource_templates()
            if t.uriTemplate == 'alpacon://alerts/active/{region}/{workspace}'
        )
        assert 'acknowledged=False' in active.description

    def test_wrapper_named_after_resource(self):
        """The exec'd wrapper must adopt the resource name and this module's
        identity, not stay '_wrapper' with a '<string>' traceback frame, so
        stack traces and name-based diagnostics stay legible."""

        async def fake_fn(region, workspace):
            return {'ok': True}

        res.register_resource(
            'alpacon://test-named/{region}/{workspace}', fake_fn, 'named_probe'
        )
        fn = mcp._resource_manager._templates[
            'alpacon://test-named/{region}/{workspace}'
        ].fn
        assert fn.__name__ == 'named_probe'
        assert fn.__qualname__ == 'named_probe'
        assert fn.__module__ == 'tools.resources'
        # co_filename lives on the exec'd wrapper, under validate_call's wrapping.
        while hasattr(fn, '__wrapped__'):
            fn = fn.__wrapped__
        assert fn.__code__.co_filename == res.__file__

    def test_uri_params_match_function_signatures(self):
        """Every URI {param} and extra kwarg must be a real parameter of its
        backing function — a typo breaks at read time, not import; catch it here."""
        for name, ref, uri, extra in res.REGISTRATIONS:
            fn = res._resolve(ref)
            wanted = set(re.findall(r'\{(\w+)\}', uri)) | set(extra or {})
            sig = inspect.signature(fn).parameters
            accepted = {
                p
                for p, v in sig.items()
                if v.kind not in (v.VAR_KEYWORD, v.VAR_POSITIONAL)
            }
            missing = wanted - accepted
            assert not missing, f'{name}: {missing} not accepted by {ref}'

            # Inverse: every required (no-default) param must be filled by the URI
            # or an extra kwarg, else the read fails at runtime, not import.
            required = {
                p
                for p, v in sig.items()
                if v.default is v.empty
                and v.kind not in (v.VAR_KEYWORD, v.VAR_POSITIONAL)
            }
            unfilled = required - wanted
            assert not unfilled, f'{name}: {unfilled} required but not in URI/extra'

    @pytest.mark.asyncio
    async def test_no_resource_is_shadowed(self):
        """Every registered template, filled with concrete values, must resolve to
        its own handler — a general guard so a future literal/{id} sibling pair
        can't silently shadow one another. Subsumes the specific /active/, /scopes/,
        etc. cases without hard-coding them."""
        mgr = mcp._resource_manager

        def concrete(uri: str) -> str:
            # Sentinel placeholders never collide with a literal segment.
            return re.sub(r'\{(\w+)\}', lambda m: f'_{m.group(1)}_', uri)

        for name, _ref, uri, _extra in res.REGISTRATIONS:
            resolved = await mgr.get_resource(concrete(uri))
            assert resolved.name == name, (
                f'{uri} -> {resolved.name}, want {name} (shadowed)'
            )
