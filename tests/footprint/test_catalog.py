"""Tests for the generated Footprint catalog and its loader."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.footprint import catalog_gen, ids
from sase.footprint._catalog_gen_commands import _flatten_mode_keys, gen_tui
from sase.footprint._catalog_gen_shared import load_bundled_config, package_resource
from sase.footprint.catalog import load_catalog, load_overlay


@pytest.fixture(scope="module")
def generated() -> list[dict[str, Any]]:
    return catalog_gen.generate_entries()


@pytest.fixture(scope="module")
def by_id(generated: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in generated}


def test_all_ids_valid_and_unique_and_sorted(
    generated: list[dict[str, Any]],
) -> None:
    seen: set[str] = set()
    previous: str | None = None
    for entry in generated:
        assert ids.is_valid_feature_id(entry["id"]), entry["id"]
        assert entry["id"] not in seen, entry["id"]
        seen.add(entry["id"])
        assert entry["ns"] in ids.NAMESPACES
        if previous is not None:
            assert previous < entry["id"]
        previous = entry["id"]


def test_checked_in_catalog_matches_generator() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    tool = repo_root / "tools" / "sync_footprint_catalog"
    result = subprocess.run(
        [sys.executable, str(tool), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_generator_is_deterministic() -> None:
    assert catalog_gen.render_catalog(
        catalog_gen.generate_entries()
    ) == catalog_gen.render_catalog(catalog_gen.generate_entries())


def _walk_cli_parser() -> tuple[set[str], set[str]]:
    """Independently collect canonical command and option IDs from argparse."""
    from sase.completion.compat import get_completion_compat_aliases
    from sase.main.parser import create_parser

    commands: set[str] = set()
    options: set[str] = set()

    def visit(
        parser: argparse.ArgumentParser, words: tuple[str, ...], seen: set[int]
    ) -> None:
        commands.add(ids.cli_id(words))
        seen_dests: set[str] = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                groups: dict[int, list[str]] = {}
                group_parser: dict[int, argparse.ArgumentParser] = {}
                for name, child in action.choices.items():
                    groups.setdefault(id(child), []).append(name)
                    group_parser.setdefault(id(child), child)
                for child_id, names in groups.items():
                    if child_id in seen:
                        continue
                    seen.add(child_id)
                    child = group_parser[child_id]
                    compat = get_completion_compat_aliases(child)
                    primary = next(
                        (name for name in names if name not in compat), names[0]
                    )
                    visit(child, (*words, primary), seen)
            elif action.option_strings:
                if action.dest in ("help", argparse.SUPPRESS):
                    continue
                if action.dest in seen_dests:
                    continue
                seen_dests.add(action.dest)
                options.add(ids.cli_option_id(ids.cli_id(words), action.dest))

    visit(create_parser(only=None), (), set())
    return commands, options


def test_every_parser_leaf_and_option_has_an_id(
    by_id: dict[str, dict[str, Any]],
) -> None:
    commands, options = _walk_cli_parser()
    assert commands
    assert options
    for command in sorted(commands):
        assert command in by_id, command
    for option in sorted(options):
        assert option in by_id, option
    catalog_cli = {fid for fid in by_id if fid.startswith("cli:")}
    assert catalog_cli == commands | options


def test_every_command_spec_has_an_id(
    by_id: dict[str, dict[str, Any]],
) -> None:
    from sase.ace.tui.commands.catalog import build_command_catalog
    from sase.ace.tui.keymaps.registry import load_keymap_registry

    registry = load_keymap_registry(load_bundled_config()["ace"])
    specs = [
        spec
        for spec in build_command_catalog(registry)
        if not spec.id.startswith("custom.")
    ]
    assert specs
    for spec in specs:
        feature_id = f"tui:{ids.sanitize(spec.id)}"
        assert feature_id in by_id or feature_id in ids.NAVIGATION_ACTIONS, spec.id


def test_every_keymap_scope_field_and_mode_key_has_an_id(
    by_id: dict[str, dict[str, Any]],
) -> None:
    from sase.ace.tui.keymaps.mode_keymaps import _BUILTIN_MODE_CLASSES
    from sase.ace.tui.keymaps.registry import load_keymap_registry
    from sase.ace.tui.keymaps.types import KeymapRegistry

    registry = load_keymap_registry(load_bundled_config()["ace"])
    scopes = [
        f.name
        for f in dataclass_fields(KeymapRegistry)
        if f.name not in ("modes", "legacy_card_block_brackets")
    ]
    assert len(scopes) >= 9
    for scope in scopes:
        for f in dataclass_fields(getattr(registry, scope)):
            feature_id = ids.tui_id(scope, f.name)
            assert feature_id in by_id or feature_id in ids.NAVIGATION_ACTIONS, (
                feature_id
            )
    for mode_name, cls in _BUILTIN_MODE_CLASSES.items():
        short = mode_name[: -len("_mode")] if mode_name.endswith("_mode") else mode_name
        flat: dict[str, None] = {}
        _flatten_mode_keys(short, dict(cls().keys), flat)
        assert flat
        for dotted in flat:
            feature_id = f"tui:{dotted}"
            assert feature_id in by_id or feature_id in ids.NAVIGATION_ACTIONS, (
                feature_id
            )


def test_every_view_and_modal_has_an_id(
    by_id: dict[str, dict[str, Any]],
) -> None:
    from typing import get_args

    from sase.ace.tui.modals.config_center_catalog import CenterTab
    from sase.ace.tui.tab_order import TabName
    from sase.stats.registry import STATISTICS_VIEW_SPECS

    for name in get_args(TabName):
        assert ids.tab_view_id(name) in by_id
    for name in get_args(CenterTab):
        assert ids.admin_view_id(name) in by_id
    assert len(STATISTICS_VIEW_SPECS) >= 8
    for spec in STATISTICS_VIEW_SPECS:
        assert ids.stats_view_id(spec.id) in by_id
    modals = [fid for fid in by_id if fid.startswith("view:modal.")]
    assert len(modals) >= 100
    assert "view:modal.add_macro" in by_id


def test_every_macro_and_skill_has_an_id(
    by_id: dict[str, dict[str, Any]],
) -> None:
    from sase.macro.loader_skills import SKILL_FRAME_TEMPLATE_FILENAME

    macros_dir = package_resource("macros")
    for path in sorted(macros_dir.glob("*.md")) + sorted(macros_dir.glob("*.yml")):
        assert f"macro:{ids.sanitize(path.stem)}" in by_id
    skills_dir = package_resource("macros", "skills")
    for path in sorted(skills_dir.glob("*.md")):
        if path.name == SKILL_FRAME_TEMPLATE_FILENAME:
            continue
        assert f"skill:{ids.sanitize(path.stem)}" in by_id


def test_every_config_leaf_has_an_id(
    by_id: dict[str, dict[str, Any]],
) -> None:
    cfg = load_bundled_config()
    assert "footprint" in cfg
    leaves: set[str] = set()

    def visit(node: Any, prefix: str) -> None:
        assert isinstance(node, dict)
        for key in node:
            if prefix == "" and key == "footprint":
                continue
            segment = ids.sanitize(str(key))
            path = f"{prefix}.{segment}" if prefix else segment
            if isinstance(node[key], dict):
                visit(node[key], path)
            else:
                leaves.add(f"config:{path}")

    visit(cfg, "")
    assert leaves
    for leaf in sorted(leaves):
        assert leaf in by_id, leaf
    assert not [fid for fid in by_id if fid.startswith("config:footprint")]


def test_every_axe_routine_and_job_has_an_id(
    by_id: dict[str, dict[str, Any]],
) -> None:
    cfg = load_bundled_config()
    routines = cfg["axe"]["routines"]
    assert routines
    for routine, info in routines.items():
        routine_id = f"auto:axe.{ids.sanitize(str(routine))}"
        assert routine_id in by_id
        for job in info.get("jobs", []):
            assert f"{routine_id}.{ids.sanitize(str(job['name']))}" in by_id


def test_first_party_plugins_have_ids(
    by_id: dict[str, dict[str, Any]],
) -> None:
    for word in ids.FIRST_PARTY_PLUGIN_COMMANDS:
        assert f"plugin:{word}" in by_id


def test_no_user_config_derived_ids(
    by_id: dict[str, dict[str, Any]],
) -> None:
    for fid in by_id:
        assert "~other" not in fid
        assert "~custom" not in fid


def test_custom_modes_never_enter_the_catalog() -> None:
    from sase.ace.tui.keymaps import KeymapRegistry
    from sase.ace.tui.keymaps.mode_keymaps import ModeKeymaps

    entries = gen_tui()
    default_ids = {entry.id for entry in entries}
    from sase.ace.tui.keymaps.registry import load_keymap_registry

    registry = load_keymap_registry(load_bundled_config()["ace"])
    assert isinstance(registry, KeymapRegistry)
    registry.modes["custom_foo"] = ModeKeymaps(prefix="X", keys={"bar": "b"})
    custom_ids = {entry.id for entry in gen_tui(registry)}
    assert custom_ids == default_ids
    assert "tui:custom_foo.bar" not in custom_ids
    assert not [fid for fid in custom_ids if fid.startswith("tui:custom.")]


def test_provider_discovered_subtabs_never_enter_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.commands import catalog as catalog_module
    from sase.ace.tui.commands.types import CommandExecutor, CommandSpec

    def fake_catalog(registry: object) -> list[CommandSpec]:
        return [
            CommandSpec(
                id="artifacts.stitches",
                label="Stitches",
                key_sequence=(),
                key_display="",
                category="Tabs",
                tabs=("artifacts",),
                executor=CommandExecutor(kind="app_action", action="noop"),
                aliases=(),
            ),
            CommandSpec(
                id="artifacts.ref:plan",
                label="Plans (provider)",
                key_sequence=(),
                key_display="",
                category="Tabs",
                tabs=("artifacts",),
                executor=CommandExecutor(kind="app_action", action="noop"),
                aliases=(),
            ),
        ]

    monkeypatch.setattr(catalog_module, "build_command_catalog", fake_catalog)
    ids_out = {entry.id for entry in gen_tui()}
    assert "tui:artifacts.stitches" in ids_out
    assert "tui:artifacts.ref_plan" not in ids_out


def test_every_overlay_key_matches_the_catalog(
    by_id: dict[str, dict[str, Any]],
) -> None:
    overlay = load_overlay()
    assert overlay.features
    for key in overlay.features:
        if key.endswith("*"):
            assert sum(1 for fid in by_id if fnmatch.fnmatch(fid, key)), key
        else:
            assert key in by_id, key
    for group in overlay.retire_with:
        for fid in group:
            assert fid in by_id, fid


def test_overlay_seed_protects_rare_surfaces() -> None:
    overlay = load_overlay()
    assert overlay.features["cli:doctor*"]["protected"] == "recovery"


def test_footprint_cli_group_exists() -> None:
    from sase.main.parser import create_parser

    parser = create_parser(only="footprint")
    args = parser.parse_args(["footprint", "catalog", "-n", "cli", "-f", "json"])
    assert args.footprint_subcommand == "catalog"
    assert args.namespace == "cli"
    bare = parser.parse_args(["footprint"])
    assert bare.footprint_subcommand == "list"
    assert (bare.lens, bare.actor, bare.range, bare.format) == (
        "map",
        "you",
        "60d",
        "rich",
    )


def test_footprint_catalog_json_lists_filtered_entries(capsys: Any) -> None:
    import argparse

    from sase.main.footprint_handler import handle_footprint_command

    args = argparse.Namespace(
        footprint_subcommand="catalog", area=None, namespace="cli", format="json"
    )
    assert handle_footprint_command(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] > 100
    assert all(entry["ns"] == "cli" for entry in payload["entries"])
    assert any(entry["id"] == "cli:bead.list" for entry in payload["entries"])


def test_footprint_catalog_markdown_groups_by_area(capsys: Any) -> None:
    import argparse

    from sase.main.footprint_handler import handle_footprint_command

    args = argparse.Namespace(
        footprint_subcommand="catalog",
        area="plugins",
        namespace=None,
        format="markdown",
    )
    assert handle_footprint_command(args) == 0
    out = capsys.readouterr().out
    assert "## plugins" in out
    assert "`plugin:listen`" in out


def test_overlay_yaml_parses_with_expected_schema() -> None:
    import importlib.resources

    text = (importlib.resources.files("sase.footprint") / "overlay.yml").read_text()
    data = yaml.safe_load(text)
    assert data["schema"] == ids.OVERLAY_SCHEMA
    assert isinstance(data["features"], dict)
    assert isinstance(data.get("retire_with"), list)
