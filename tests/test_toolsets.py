"""Tests for --toolsets selective tool registration (issues #34, #221)."""

import ast
import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import server
import tools.resources as res
import utils.declared_agent as declared_agent
from utils.common import serves_ledger_tools

ALL_MODULES = set(server.TOOLSET_REGISTRY.values())


@pytest.fixture(autouse=True)
def _no_toolsets_env(monkeypatch):
    monkeypatch.delenv(server.TOOLSETS_ENV_VAR, raising=False)


class TestResolveToolsets:
    def test_default_is_all(self):
        assert server.resolve_toolsets(None) == ALL_MODULES

    def test_empty_string_is_all(self):
        assert server.resolve_toolsets('') == ALL_MODULES

    def test_all_keyword(self):
        assert server.resolve_toolsets('all') == ALL_MODULES

    def test_single_toolset(self):
        assert server.resolve_toolsets('servers') == {'server_tools'}

    def test_multiple_toolsets_with_whitespace(self):
        assert server.resolve_toolsets(' servers, commands , webftp ') == {
            'server_tools',
            'command_tools',
            'webftp_tools',
        }

    def test_env_var_used_when_cli_absent(self, monkeypatch):
        # Pinned literal: renaming the constant must not silently move the contract.
        assert server.TOOLSETS_ENV_VAR == 'ALPACON_MCP_TOOLSETS'
        monkeypatch.setenv(server.TOOLSETS_ENV_VAR, 'metrics')
        assert server.resolve_toolsets(None) == {'metrics_tools'}

    def test_cli_wins_over_env_var(self, monkeypatch):
        monkeypatch.setenv(server.TOOLSETS_ENV_VAR, 'metrics')
        assert server.resolve_toolsets('servers') == {'server_tools'}

    def test_unknown_name_fails_fast_with_valid_names(self):
        # ToolsetError, not a bare ValueError, so entry points catch only this.
        with pytest.raises(server.ToolsetError) as exc:
            server.resolve_toolsets('servers,nope')
        assert 'nope' in str(exc.value)
        assert 'servers' in str(exc.value)  # selectable toolset listed
        assert 'health' in str(exc.value)  # always-on names listed as valid too

    def test_names_are_case_insensitive(self):
        assert server.resolve_toolsets('Servers, METRICS') == {
            'server_tools',
            'metrics_tools',
        }

    def test_always_on_aliases_are_ignored_not_errors(self):
        assert server.resolve_toolsets(
            'servers,workspace,health,work-sessions,prompts'
        ) == {'server_tools'}

    def test_only_always_on_names_warns_and_selects_nothing(self, caplog):
        with caplog.at_level('WARNING'):
            assert server.resolve_toolsets('health,workspace') == set()
        assert any(
            'No functional toolsets selected' in r.message for r in caplog.records
        )

    def test_unknown_name_alongside_all_still_fails(self):
        with pytest.raises(ValueError) as exc:
            server.resolve_toolsets('all,mtrics')
        assert 'mtrics' in str(exc.value)


class TestRegistryConsistency:
    def test_registry_covers_every_tool_module(self):
        """resources.py is the resource registry, not a tool module, hence excluded."""
        tools_dir = Path(server.__file__).parent / server.TOOLS_PACKAGE
        on_disk = {p.stem for p in tools_dir.glob('*.py')} - {'__init__', 'resources'}
        assert on_disk == ALL_MODULES | server.ALWAYS_ON_MODULES

    def test_registry_modules_are_importable(self):
        for module_name in ALL_MODULES | server.ALWAYS_ON_MODULES:
            importlib.import_module(f'{server.TOOLS_PACKAGE}.{module_name}')


class TestResourceRegistrations:
    def test_resources_module_imports_no_tool_module(self):
        """tools/resources.py must not import a tool module, or --toolsets registers
        everything. Checked statically: sys.modules is process-global here.
        """
        tool_modules = server.ALL_TOOL_MODULES | server.ALWAYS_ON_MODULES
        leaked = set()
        # ast.walk, not tree.body: an import nested in a try/if still executes.
        for node in ast.walk(ast.parse(Path(res.__file__).read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                # `from tools import cert_tools` names the module in .names.
                if node.module == server.TOOLS_PACKAGE:
                    leaked |= {a.name for a in node.names} & tool_modules
                elif node.module.split('.')[0] == server.TOOLS_PACKAGE:
                    leaked |= {node.module.split('.')[1]} & tool_modules
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split('.')
                    if parts[0] == server.TOOLS_PACKAGE and len(parts) > 1:
                        leaked |= {parts[1]} & tool_modules

        assert not leaked, f'tools/resources.py eagerly imports: {sorted(leaked)}'

    def test_every_ref_resolves_to_a_real_function(self):
        for name, ref, _uri, _extra in res.REGISTRATIONS:
            module_name, func_name = ref.split('.', 1)
            mod = importlib.import_module(f'{server.TOOLS_PACKAGE}.{module_name}')
            assert hasattr(mod, func_name), f'{name}: tools.{ref} does not exist'

    def test_register_resources_filters_by_module(self, monkeypatch):
        registered: list[str] = []
        monkeypatch.setattr(
            res,
            'register_resource',
            lambda uri, fn, name, extra=None: registered.append(name),
        )
        res.register_resources({'server_tools'})

        expected = {
            name
            for name, ref, _uri, _extra in res.REGISTRATIONS
            if ref.split('.', 1)[0] == 'server_tools'
        }
        assert set(registered) == expected
        assert 'servers_list' in registered
        assert 'alerts_list' not in registered


class TestCliWiring:
    @staticmethod
    def _load(filename):
        # By path: each probe gets its own module, so a monkeypatch never lands on a cached `main`.
        path = Path(server.__file__).parent / filename
        spec = importlib.util.spec_from_file_location(f'_probe_{filename}', path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_stdio_entry_point_forwards_toolsets(self, monkeypatch):
        module = self._load('main.py')
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            module, 'run', lambda transport, **kw: captured.update(kw, t=transport)
        )
        # --config-file keeps main() off the interactive setup-wizard branch.
        monkeypatch.setattr(
            sys, 'argv', ['main.py', '--toolsets', 'servers', '--config-file', 'x.json']
        )
        module.main()

        assert captured['t'] == 'stdio'
        assert captured['toolsets'] == 'servers'

    def test_sse_entry_point_forwards_toolsets(self, monkeypatch):
        module = self._load('main_sse.py')
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            module, 'run', lambda transport, **kw: captured.update(kw, t=transport)
        )
        monkeypatch.setattr(sys, 'argv', ['main_sse.py', '--toolsets', 'metrics'])
        module.main()

        assert captured['t'] == 'sse'
        assert captured['toolsets'] == 'metrics'


class TestRunWiring:
    def test_run_imports_selection_and_hands_it_to_register_resources(
        self, monkeypatch
    ):
        """run() is where the pieces meet; unit tests of the parts miss a
        mismatch here (e.g. handing register_resources the sorted list)."""
        imported: list[str] = []
        real_import = importlib.import_module
        handed: dict[str, object] = {}

        def spy(name, *args, **kwargs):
            imported.append(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, 'import_module', spy)
        monkeypatch.setattr(res, 'register_resources', lambda m: handed.update(m=m))
        monkeypatch.setattr(server.mcp, 'run', lambda transport: None)
        monkeypatch.setenv('ALPACON_MCP_TRANSPORT', 'restored-on-teardown')
        monkeypatch.delenv('ALPACON_MCP_AUTH_ENABLED', raising=False)
        # run('stdio') turns the declared-agent fallback on; restore it after.
        monkeypatch.setattr(declared_agent, '_environment_fallback', False)

        server.run('stdio', toolsets='servers')

        expected = server._modules_to_load('servers')
        prefix = f'{server.TOOLS_PACKAGE}.'
        assert {n for n in imported if n.startswith(prefix)} == {
            prefix + m for m in expected
        }
        assert handed['m'] == expected


class TestModulesToLoad:
    def test_selection_is_subset_plus_always_on(self):
        modules = server._modules_to_load('servers,metrics')
        assert modules == {'server_tools', 'metrics_tools', *server.ALWAYS_ON_MODULES}

    def test_default_loads_everything(self):
        modules = server._modules_to_load(None)
        assert modules == ALL_MODULES | server.ALWAYS_ON_MODULES


class TestRemoteModeSelection:
    """Remote mode reads ALPACON_MCP_TOOLSETS, since main_http.py takes no flag (#221)."""

    @pytest.fixture
    def handed(self, monkeypatch) -> dict[str, set[str]]:
        handed: dict[str, set[str]] = {}
        monkeypatch.setattr(res, 'register_resources', lambda m: handed.update(m=m))
        monkeypatch.setattr(declared_agent, '_environment_fallback', False)
        monkeypatch.setattr(server, 'mcp', MagicMock())
        monkeypatch.setattr(importlib, 'import_module', MagicMock())
        monkeypatch.setenv('ALPACON_MCP_TRANSPORT', 'restored-on-teardown')
        monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'true')
        monkeypatch.setenv('AUTH0_ALPACON_LOGIN_CLIENT_ID', 'client-id')
        monkeypatch.delenv('ALPACON_MCP_REMOTE_LEDGER', raising=False)
        return handed

    def test_remote_mode_registers_only_the_env_selection(self, monkeypatch, handed):
        monkeypatch.setenv(server.TOOLSETS_ENV_VAR, 'metrics,alerts')

        server.prepare(server.TRANSPORT_STREAMABLE_HTTP)

        assert handed['m'] == {
            'metrics_tools',
            'alert_tools',
            *server.ALWAYS_ON_MODULES,
        }

    @pytest.mark.parametrize('selection', [None, ''])
    def test_remote_mode_without_selection_registers_everything(
        self, monkeypatch, handed, caplog, selection
    ):
        if selection is not None:
            monkeypatch.setenv(server.TOOLSETS_ENV_VAR, selection)

        with caplog.at_level(logging.WARNING, logger='alpacon_mcp.server'):
            server.prepare(server.TRANSPORT_STREAMABLE_HTTP)

        assert (
            handed['m']
            == (ALL_MODULES - server.LEDGER_MODULES) | server.ALWAYS_ON_MODULES
        )
        assert not [r for r in caplog.records if r.levelname == 'WARNING']

    @pytest.mark.parametrize(
        ('selection', 'served'), [('security', False), ('security,ledger', True)]
    )
    def test_ledger_hints_follow_the_selection(
        self, monkeypatch, handed, selection, served
    ):
        monkeypatch.setenv('ALPACON_MCP_REMOTE_LEDGER', 'true')
        monkeypatch.setenv(server.TOOLSETS_ENV_VAR, selection)

        server.prepare(server.TRANSPORT_STREAMABLE_HTTP)

        assert ('ledger_tools' in handed['m']) is served
        assert serves_ledger_tools() is served

    def test_remote_mode_rejects_an_unknown_toolset(self, monkeypatch, handed):
        monkeypatch.setenv(server.TOOLSETS_ENV_VAR, 'metrics,bogus')

        with pytest.raises(server.ToolsetError, match='bogus'):
            server.prepare(server.TRANSPORT_STREAMABLE_HTTP)

        assert 'm' not in handed

    def test_selection_that_strands_a_resource_warns_naming_it(
        self, monkeypatch, handed, caplog
    ):
        monkeypatch.setenv(server.TOOLSETS_ENV_VAR, 'servers')

        with caplog.at_level(logging.WARNING, logger='alpacon_mcp.server'):
            server.prepare(server.TRANSPORT_STREAMABLE_HTTP)

        warnings = [r.getMessage() for r in caplog.records if r.levelname == 'WARNING']
        assert any(
            '{server_id}/overview' in w and 'system-info toolset' in w for w in warnings
        )


class TestStrandedResources:
    def test_servers_alone_strands_the_system_info_backed_overview(self):
        stranded = res.stranded_resources({'server_tools'})
        assert stranded == [
            (
                'alpacon://servers/{region}/{workspace}/{server_id}/overview',
                'system_info_tools',
            )
        ]

    def test_alerts_alone_strands_the_metrics_backed_alert_rules(self):
        stranded = res.stranded_resources({'alert_tools'})
        assert {module for _, module in stranded} == {'metrics_tools'}
        assert all(uri.startswith('alpacon://alert-rules/') for uri, _ in stranded)

    def test_system_info_alone_strands_the_server_tools_backed_server_resources(self):
        stranded = res.stranded_resources({'system_info_tools'})
        assert stranded
        assert {module for _, module in stranded} == {'server_tools'}
        assert all(uri.startswith('alpacon://servers/') for uri, _ in stranded)

    def test_metrics_alone_strands_the_alert_tools_backed_recipients(self):
        stranded = res.stranded_resources({'metrics_tools'})
        assert stranded == [
            (
                'alpacon://alert-rules/{region}/{workspace}/{rule_id}/recipients',
                'alert_tools',
            )
        ]

    def test_selecting_both_backing_modules_strands_nothing(self):
        selected = {'server_tools', 'system_info_tools', 'alert_tools', 'metrics_tools'}
        assert res.stranded_resources(selected) == []

    def test_a_wholly_unselected_family_is_not_stranded(self):
        assert res.stranded_resources({'iam_tools'}) == []

    def test_everything_selected_strands_nothing(self):
        modules = ALL_MODULES | server.ALWAYS_ON_MODULES
        assert res.stranded_resources(modules) == []
