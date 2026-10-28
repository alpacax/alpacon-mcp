"""Tests for alpacon:// MCP resources."""

import inspect
import re

import pytest
from mcp.shared.uri_template import UriTemplate

import tools.resources as res
from server import ALL_TOOL_MODULES, ALWAYS_ON_MODULES, mcp
from tests.conftest import http_client_fixture, tool_descriptions

mock_metrics_http_client = http_client_fixture('tools.metrics_tools')


@pytest.fixture(scope='module', autouse=True)
def _register_all_resources():
    """Register every resource once for this module."""
    res.register_resources(set(ALL_TOOL_MODULES) | ALWAYS_ON_MODULES)


async def _registered_uris():
    """All registered alpacon:// URIs: templated (with {params}) and static."""
    templates = {t.uri_template for t in await mcp.list_resource_templates()}
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
    async def test_every_resource_publishes_its_tool_description(self):
        """A resource reads the text its tool publishes in tools/list, never the
        tool's docstring, so the two cannot drift apart."""
        tools = await tool_descriptions()
        published = {
            t.uri_template: t.description for t in await mcp.list_resource_templates()
        }
        published |= {str(r.uri): r.description for r in await mcp.list_resources()}

        drifted = []
        for name, ref, uri, extra in res.REGISTRATIONS:
            want = tools[ref.split('.', 1)[1]]
            if extra:
                pinned = ', '.join(f'{k}={v!r}' for k, v in extra.items())
                want = f'{want}\n\nThis resource pins: {pinned}.'
            if published[uri] != want:
                drifted.append(name)

        assert not drifted, f'drifted from their tool description: {drifted}'

    @pytest.mark.asyncio
    async def test_resource_over_a_non_tool_is_described_by_its_name(self):
        """A callable no tool registration knows falls back to the resource name,
        not to its docstring."""

        async def untracked_fn(region, workspace):
            """Developer-only docstring."""
            return {'ok': True}

        res.register_resource(
            'alpacon://test-untracked/{region}/{workspace}',
            untracked_fn,
            'untracked_probe',
        )

        template = next(
            t
            for t in await mcp.list_resource_templates()
            if t.uri_template == 'alpacon://test-untracked/{region}/{workspace}'
        )
        assert template.description == 'untracked_probe'

    @pytest.mark.asyncio
    async def test_resource_over_a_namesake_of_a_tool_is_described_by_its_name(self):
        """A callable that only shares a registered tool's name does not borrow
        that tool's description."""

        async def list_servers(region, workspace):
            return {'ok': True}

        res.register_resource(
            'alpacon://test-namesake/{region}/{workspace}',
            list_servers,
            'namesake_probe',
        )

        template = next(
            t
            for t in await mcp.list_resource_templates()
            if t.uri_template == 'alpacon://test-namesake/{region}/{workspace}'
        )
        assert template.description == 'namesake_probe'

    @pytest.mark.asyncio
    async def test_filtered_resource_describes_its_pin(self):
        """A resource registered with extra kwargs must surface the pinned
        filter in its description, not just inherit the tool description."""
        active = next(
            t
            for t in await mcp.list_resource_templates()
            if t.uri_template == 'alpacon://alerts/active/{region}/{workspace}'
        )
        assert active.description is not None
        assert 'acknowledged=False' in active.description

    @pytest.mark.asyncio
    async def test_metrics_latest_stale_registered_and_describes_its_pin(self):
        """alpacon://.../latest/stale is registered apart from .../latest, and its
        description names the state='stale' pin instead of inheriting the tool's.
        """
        uris = await _registered_uris()
        assert 'alpacon://metrics/{region}/{workspace}/latest' in uris
        assert 'alpacon://metrics/{region}/{workspace}/latest/stale' in uris

        stale = next(
            t
            for t in await mcp.list_resource_templates()
            if t.uri_template == 'alpacon://metrics/{region}/{workspace}/latest/stale'
        )
        assert stale.description is not None
        assert "state='stale'" in stale.description

    @pytest.mark.asyncio
    async def test_metrics_latest_stale_pins_state_on_the_real_request(
        self, mock_metrics_http_client, mock_token_manager
    ):
        """Reading the resource must reach list_latest_metrics with state='stale'
        actually forwarded to the HTTP request, not just documented."""
        mock_metrics_http_client.get.return_value = {'count': 0, 'results': []}

        await mcp.read_resource('alpacon://metrics/ap1/testworkspace/latest/stale')

        mock_metrics_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/latest/',
            token='test-token',
            params={'state': 'stale'},
        )

    def test_wrapper_named_after_resource(self):
        """The exec'd wrapper must adopt the resource name and this module, not
        '_wrapper'. Built directly: the SDK's ResourceTemplate keeps no callable.
        """

        async def fake_fn(region, workspace):
            return {'ok': True}

        fn = res.build_resource_wrapper(
            'alpacon://test-named/{region}/{workspace}', fake_fn, 'named_probe', None
        )

        assert fn.__name__ == 'named_probe'
        assert fn.__qualname__ == 'named_probe'
        assert fn.__module__ == 'tools.resources'
        assert fn.__code__.co_filename == res.__file__

    def test_uri_params_match_function_signatures(self):
        """Every URI {param} and extra kwarg must be a real parameter of its
        backing function: a typo breaks at read time, not import; catch it here."""
        for name, ref, uri, extra in res.REGISTRATIONS:
            fn = res._resolve(ref)
            wanted = set(re.findall(r'\{(\w+)\}', uri)) | set(extra or {})
            sig = inspect.signature(fn).parameters
            missing = wanted - set(sig)
            assert not missing, f'{name}: {missing} not accepted by {ref}'

            # Inverse: every required (no-default) param must be filled by the URI
            # or an extra kwarg, else the read fails at runtime, not import.
            required = {
                p
                for p, v in sig.items()
                if v.default is v.empty and v.kind is not v.VAR_POSITIONAL
            }
            unfilled = required - wanted
            # A catch-all carries no default, so `kwargs` showing up here means the
            # signature @mcp_tool_handler publishes regressed, not the URI table.
            assert not unfilled, f'{name}: {unfilled} required but not in URI/extra'

    @pytest.mark.asyncio
    async def test_no_resource_is_shadowed(self):
        """Every registered template, filled with concrete values, must resolve to its
        own handler, so a future literal/{id} sibling pair cannot shadow one another.
        """
        templates = await mcp.list_resource_templates()
        statics = await mcp.list_resources()

        def concrete(uri: str) -> str:
            # Sentinel placeholders never collide with a literal segment.
            return re.sub(r'\{(\w+)\}', lambda m: f'_{m.group(1)}_', uri)

        for name, _ref, uri, _extra in res.REGISTRATIONS:
            target = concrete(uri)
            static_match = next((r for r in statics if str(r.uri) == target), None)
            if static_match is not None:
                resolved_name = static_match.name
            else:
                # Same precedence the SDK itself uses: first template whose
                # pattern matches the concrete URI wins.
                template_match = next(
                    t
                    for t in templates
                    if UriTemplate.parse(t.uri_template).match(target) is not None
                )
                resolved_name = template_match.name
            assert resolved_name == name, (
                f'{uri} -> {resolved_name}, want {name} (shadowed)'
            )
