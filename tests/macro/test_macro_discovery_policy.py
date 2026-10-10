"""Discovery policy for the retired macro syntax aliases.

Covers the consolidated plugin discovery contract (canonical
``sase_macros`` group first, with the retired group always accepted as an
alias, deduplicated by entry-point value), the public env collision
rules, unconditional legacy filesystem-directory inclusion, and the LSP
command/resource-path propagation.
"""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _make_plugin_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    *,
    macros_body: str | None = None,
    legacy_body: str | None = None,
) -> ModuleType:
    """Create an importable fake plugin package with macro resources."""
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    if macros_body is not None:
        resource = package / "macros"
        resource.mkdir()
        (resource / "shared.md").write_text(macros_body, encoding="utf-8")
    if legacy_body is not None:
        resource = package / "xprompts"
        resource.mkdir()
        (resource / "shared.md").write_text(legacy_body, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for module_name in list(sys.modules):
        if module_name == name or module_name.startswith(name + "."):
            del sys.modules[module_name]
    __import__(name)
    return sys.modules[name]


def _patch_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    entries: list[tuple[str, str, str]],
) -> None:
    """Serve fake ``(name, value, group)`` entry points to discovery."""

    def fake_entry_points(*, group: str = "") -> tuple:
        return tuple(
            importlib.metadata.EntryPoint(name=name, value=value, group=group)
            for (name, value, entry_group) in entries
            if entry_group == group
        )

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)


class TestMacroPluginsDisabled:
    def test_both_public_env_names_collide(self) -> None:
        from sase.main.plugin_discovery import macro_plugins_disabled

        with pytest.raises(ValueError, match="SASE_DISABLE_PLUGIN_MACROS"):
            macro_plugins_disabled(
                environ={
                    "SASE_DISABLE_PLUGIN_MACROS": "",
                    "SASE_DISABLE_PLUGIN_XPROMPTS": "",
                }
            )

    def test_both_names_collide(self) -> None:
        from sase.main.plugin_discovery import macro_plugins_disabled

        with pytest.raises(ValueError, match="is retired; use"):
            macro_plugins_disabled(
                environ={
                    "SASE_DISABLE_PLUGIN_MACROS": "1",
                    "SASE_DISABLE_PLUGIN_XPROMPTS": "1",
                }
            )

    def test_retired_name_is_always_honored_as_alias(self) -> None:
        from sase.main.plugin_discovery import macro_plugins_disabled

        assert (
            macro_plugins_disabled(environ={"SASE_DISABLE_PLUGIN_XPROMPTS": "1"})
            is True
        )
        assert (
            macro_plugins_disabled(environ={"SASE_DISABLE_PLUGIN_XPROMPTS": ""})
            is False
        )

    def test_canonical_name_decides(self) -> None:
        from sase.main.plugin_discovery import macro_plugins_disabled

        assert (
            macro_plugins_disabled(environ={"SASE_DISABLE_PLUGIN_MACROS": "1"}) is True
        )
        assert macro_plugins_disabled(environ={}) is False


class TestMacroPluginDiscovery:
    def test_canonical_group_wins_and_dedupes_dual_registration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.main.plugin_discovery import (
            _discover_macro_plugin_entry_points,
            discover_macro_plugin_modules,
            macro_plugin_definition_dirname,
        )

        module = _make_plugin_package(
            tmp_path,
            monkeypatch,
            "fake_dual_plugin",
            macros_body="# new\n\nNew body.\n",
            legacy_body="# old\n\nOld body.\n",
        )
        _patch_entry_points(
            monkeypatch,
            [
                ("dual", module.__name__, "sase_macros"),
                ("dual", module.__name__, "sase_xprompts"),
            ],
        )
        assert macro_plugin_definition_dirname(module) == "macros"
        modules = discover_macro_plugin_modules()
        assert [mod.__name__ for mod in modules].count(module.__name__) == 1
        entry_points = _discover_macro_plugin_entry_points()
        assert len(entry_points) == 1
        assert entry_points[0].group == "sase_macros"

    def test_retired_group_is_always_discovered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.main.plugin_discovery import discover_macro_plugin_modules

        module = _make_plugin_package(
            tmp_path,
            monkeypatch,
            "fake_legacy_plugin",
            legacy_body="# old\n\nOld body.\n",
        )
        _patch_entry_points(
            monkeypatch,
            [("legacy", module.__name__, "sase_xprompts")],
        )
        assert [mod.__name__ for mod in discover_macro_plugin_modules()] == [
            module.__name__
        ]

    def test_legacy_only_resource_dir_is_always_supported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.main.plugin_discovery import macro_plugin_definition_dirname

        module = _make_plugin_package(
            tmp_path,
            monkeypatch,
            "fake_legacy_only_plugin",
            legacy_body="# old\n\nOld body.\n",
        )
        assert macro_plugin_definition_dirname(module) == "xprompts"


class TestPluginMacroLoading:
    def test_canonical_body_wins_over_legacy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.macro.loader_sources import load_macros_from_plugins

        module = _make_plugin_package(
            tmp_path,
            monkeypatch,
            "fake_load_plugin",
            macros_body="# new\n\nNew body.\n",
            legacy_body="# old\n\nOld body.\n",
        )
        _patch_entry_points(
            monkeypatch,
            [
                ("dual", module.__name__, "sase_macros"),
                ("dual", module.__name__, "sase_xprompts"),
            ],
        )
        macros = load_macros_from_plugins()
        assert "New body." in macros["shared"].content

    def test_legacy_only_plugin_is_always_loaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.macro.loader_sources import load_macros_from_plugins

        module = _make_plugin_package(
            tmp_path,
            monkeypatch,
            "fake_legacy_load_plugin",
            legacy_body="# legacy-one\n\nLegacy body.\n",
        )
        _patch_entry_points(
            monkeypatch,
            [("legacy", module.__name__, "sase_xprompts")],
        )
        assert "shared" in load_macros_from_plugins()


class TestLegacyDirectoryGating:
    def test_role_legacy_sources_are_always_included(self) -> None:
        from sase.content_layout import resolve_macro_file_sources

        # The retired switch is accepted and ignored: both values return
        # the same sources, with retired roles included unconditionally.
        denied = resolve_macro_file_sources(accept_legacy=False)
        accepted = resolve_macro_file_sources(accept_legacy=True)
        assert {source.path for source in denied} == {
            source.path for source in accepted
        }

    def test_snippet_source_path_always_includes_legacy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.completion.candidates.catalog_snippets import snippet_source_path

        legacy_dir = tmp_path / "sase" / "xprompts"
        legacy_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        assert snippet_source_path(None) == legacy_dir


class TestLspDiscoveryPolicy:
    def test_canonical_command_override_wins(self, tmp_path: Path) -> None:
        from sase.integrations.macro_lsp import _resolve_macro_lsp_command

        command = _resolve_macro_lsp_command(
            environ={
                "SASE_MACRO_LSP_CMD": "macro-server --flag",
                "SASE_XPROMPT_LSP_CMD": "legacy-server",
            },
            which=lambda name: None,
            repo_root=tmp_path,
        )
        assert command == ("macro-server", "--flag")

    def test_legacy_command_override_is_always_accepted(self, tmp_path: Path) -> None:
        from sase.integrations.macro_lsp import _resolve_macro_lsp_command

        command = _resolve_macro_lsp_command(
            environ={"SASE_XPROMPT_LSP_CMD": "legacy-server --flag"},
            which=lambda name: None,
            repo_root=tmp_path,
        )
        assert command == ("legacy-server", "--flag")

    def test_canonical_binary_preferred_over_newer_legacy(self, tmp_path: Path) -> None:
        from sase.integrations.macro_lsp import _newest_existing_macro_lsp_binary

        bindir = tmp_path / "bin"
        bindir.mkdir()
        canonical = bindir / "sase-macro-lsp"
        legacy = bindir / "sase-xprompt-lsp"
        canonical.write_text("", encoding="utf-8")
        legacy.write_text("", encoding="utf-8")
        import os
        import time

        old_mtime = time.time() - 100
        os.utime(canonical, (old_mtime, old_mtime))
        assert (
            _newest_existing_macro_lsp_binary([bindir], accept_legacy=True) == canonical
        )
        assert (
            _newest_existing_macro_lsp_binary([bindir], accept_legacy=False)
            == canonical
        )
        canonical.unlink()
        assert _newest_existing_macro_lsp_binary([bindir], accept_legacy=True) == legacy
        # The retired switch is accepted and ignored: denied lookups still
        # find the legacy binary.
        assert (
            _newest_existing_macro_lsp_binary([bindir], accept_legacy=False) == legacy
        )

    def test_exec_wrapper_exports_no_policy_transport(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.integrations.macro_lsp import _prepare_macro_lsp_environment

        monkeypatch.setattr(
            "sase.integrations.macro_lsp._default_vcs_project_catalog_path",
            lambda: tmp_path / "vcs.json",
        )
        monkeypatch.setattr(
            "sase.integrations.macro_lsp._default_model_catalog_path",
            lambda: tmp_path / "model.json",
        )
        monkeypatch.setattr(
            "sase.integrations.macro_lsp._default_machine_catalog_path",
            lambda: tmp_path / "machine.json",
        )
        monkeypatch.setattr(
            "sase.integrations.macro_lsp._default_artifact_ref_catalog_path",
            lambda: tmp_path / "artifact_ref.json",
        )
        monkeypatch.setattr(
            "sase.integrations.macro_lsp._default_glossary_catalog_path",
            lambda: tmp_path / "glossary.json",
        )
        package_dir = tmp_path / "pkg"
        (package_dir / "macros").mkdir(parents=True)
        (package_dir / "default_macros").mkdir(parents=True)
        (package_dir / "default_config.yml").write_text("{}\n", encoding="utf-8")
        env: dict[str, str] = {}
        _prepare_macro_lsp_environment(env, package_dir=package_dir)
        # No retired policy transport is exported now that the switch retired.
        assert all("ACCEPT_LEGACY" not in key for key in env)
        from sase.integrations.macro_lsp import SASE_MACRO_PACKAGE_DIR_ENV

        assert env[SASE_MACRO_PACKAGE_DIR_ENV] == str(package_dir)


class TestRustCatalogPolicy:
    def test_skill_definition_options_use_canonical_dirs_and_policy(self) -> None:
        from sase.core.macro_skill_definition_facade import _catalog_options

        # The retired switch is always accepted: options carry True.
        options = _catalog_options(None)
        assert options["accept_legacy_xprompt_names"] is True
        assert str(options["package_macros_dir"]).endswith("macros")
        assert str(options["default_macros_dir"]).endswith("default_macros")
        assert "xprompts" not in str(options["package_macros_dir"])
