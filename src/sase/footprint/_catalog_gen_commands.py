"""CLI parser tree and TUI keymap catalog generation."""

from __future__ import annotations

import argparse
from dataclasses import fields as dataclass_fields
from typing import Any

from sase.footprint._catalog_gen_shared import (
    Entry,
    first_line,
    humanize,
    load_bundled_config,
)
from sase.footprint.ids import (
    NAVIGATION_ACTIONS,
    cli_id,
    cli_option_id,
    sanitize,
    tui_id,
)


def _registrar_src(top_word: str) -> str | None:
    from sase.main.parser_registry import _COMMAND_REGISTRARS

    spec = _COMMAND_REGISTRARS.get(top_word)
    if spec is None:
        return None
    module, func = spec
    return f"{module.replace('.', '/')}.py:{func}"


def _choice_help(sub_action: argparse._SubParsersAction, name: str) -> str | None:
    for choice_action in sub_action._choices_actions:
        if choice_action.dest == name:
            return choice_action.help
    return None


def _primary_name(
    names: list[str], parser: argparse.ArgumentParser
) -> tuple[str, list[str]]:
    """Return the canonical name and alias names for one parser object.

    Names sharing one parser object are argparse aliases of the same command.
    The canonical name is the first insertion-order name the completion compat
    layer does not mark legacy; the rest are legacy aliases that resolve to
    it (mirrored in ``CLI_ALIASES`` for the recorder).
    """
    from sase.completion.compat import get_completion_compat_aliases

    compat = get_completion_compat_aliases(parser)
    for name in names:
        if name not in compat:
            return name, [other for other in names if other != name]
    return names[0], names[1:]


def _walk_parser(
    parser: argparse.ArgumentParser,
    words: tuple[str, ...],
    help_text: str | None,
    seen: set[int],
    out: list[Entry],
) -> None:
    cmd_id = cli_id(words)
    top_src = _registrar_src(words[0]) if words else None
    if words:
        area = f"cli.{words[0]}"
    else:
        area = "cli"
    if not help_text or help_text == argparse.SUPPRESS:
        label = f"sase {' '.join(words)}" if words else "sase"
    else:
        label = help_text
    out.append(
        Entry(
            id=cmd_id,
            ns="cli",
            area=area,
            kind="command",
            label=first_line(label),
            src=top_src,
        )
    )
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
                primary, _aliases = _primary_name(names, child)
                _walk_parser(
                    child,
                    (*words, primary),
                    _choice_help(action, primary),
                    seen,
                    out,
                )
        elif action.option_strings:
            dest = action.dest
            if dest in ("help", argparse.SUPPRESS):
                continue
            if dest in seen_dests:
                continue
            seen_dests.add(dest)
            out.append(
                Entry(
                    id=cli_option_id(cmd_id, dest),
                    ns="cli",
                    area=area,
                    kind="option",
                    label=f"Option --{dest} of {cmd_id}",
                    parent=cmd_id,
                    src=top_src,
                )
            )


def gen_cli() -> list[Entry]:
    """Generate entries for every parser node and option dest."""
    from sase.main.parser import create_parser

    out: list[Entry] = []
    _walk_parser(create_parser(only=None), (), None, set(), out)
    return out


def _scope_label_map() -> dict[tuple[str, str], str]:
    from sase.ace.tui.keymaps import metadata as md

    labels: dict[tuple[str, str], str] = {}
    for scope, pair_table in (
        ("statistics", md._STATISTICS_BINDING_META),
        ("config", md._CONFIG_HUB_BINDING_META),
        ("gate", md._GATE_BINDING_META),
        ("gate", md._GATE_INPUT_PANEL_BINDING_META),
        ("command_line", md._COMMAND_LINE_BINDING_META),
        ("memory", md._MEMORY_BINDING_META),
        ("snippets", md._SNIPPET_BINDING_META),
    ):
        for action, label in pair_table:
            labels[(scope, action)] = label
    for scope, triple_table in (
        ("projects", md._PROJECTS_BINDING_META),
        ("tool_runs", md._TOOL_RUNS_BINDING_META),
        ("machines", md._MACHINES_BINDING_META),
    ):
        for action, _key, label in triple_table:
            labels[(scope, action)] = label
    return labels


def _flatten_mode_keys(prefix: str, keys: dict[str, Any], out: dict[str, None]) -> None:
    for key, value in keys.items():
        if isinstance(value, dict):
            _flatten_mode_keys(f"{prefix}.{key}", value, out)
        else:
            out[f"{prefix}.{key}"] = None


def _mode_parent(mode_name: str) -> str | None:
    from sase.ace.tui.keymaps.metadata import _MODE_PREFIX_ACTIONS

    starter = _MODE_PREFIX_ACTIONS.get(mode_name)
    if starter is None:
        return None
    return tui_id("app", starter)


def gen_tui(registry: Any | None = None) -> list[Entry]:
    """Generate TUI entries from the bundled keymap registry.

    Covers ``build_command_catalog`` (built-in IDs only), every scope
    dataclass field, and every built-in mode keymap class, deduplicated.
    Pass a registry explicitly in tests; the default loads bundled config.
    """
    from sase.ace.tui.artifact_tabs import FIXED_ARTIFACTS_SUBTAB_ORDER
    from sase.ace.tui.commands.catalog import build_command_catalog
    from sase.ace.tui.keymaps.mode_keymaps import _BUILTIN_MODE_CLASSES
    from sase.ace.tui.keymaps.registry import load_keymap_registry
    from sase.ace.tui.keymaps.types import KeymapRegistry

    fixed_subtabs = frozenset(FIXED_ARTIFACTS_SUBTAB_ORDER)

    if registry is None:
        cfg = load_bundled_config()
        ace_cfg = cfg.get("ace", {})
        if not isinstance(ace_cfg, dict):
            ace_cfg = {}
        registry = load_keymap_registry(ace_cfg)

    by_id: dict[str, Entry] = {}
    mode_scopes = {"fold", "copy", "leader", "bang", "bead_issue"}

    for spec in build_command_catalog(registry):
        if spec.id.startswith("custom."):
            continue
        if spec.id.startswith("artifacts."):
            # Provider-discovered artifact tabs (for example ref:plan from a
            # document provider) resolve differently per install and per test
            # isolation. The catalog keeps only the fixed bundled subtabs so
            # generation stays hermetic; provider tabs are recorded against
            # their view:tab.* entries instead.
            subtab = spec.id.split(".", 1)[1]
            if subtab not in fixed_subtabs:
                continue
        feature_id = f"tui:{sanitize(spec.id)}"
        if feature_id in NAVIGATION_ACTIONS:
            continue
        scope = spec.id.split(".")[0]
        kind = "mode_key" if scope in mode_scopes else "action"
        parent = None
        if kind == "mode_key":
            mode_name = f"{scope}_mode"
            if scope == "bead_issue":
                mode_name = "bead_issue_mode"
            parent = _mode_parent(mode_name)
        by_id[feature_id] = Entry(
            id=feature_id,
            ns="tui",
            area=f"tui.{scope}",
            kind=kind,
            label=spec.label,
            parent=parent,
            src=f"ace/action:{spec.executor.action}"
            if spec.executor.kind == "app_action"
            else None,
        )

    labels = _scope_label_map()
    scope_names = [
        f.name
        for f in dataclass_fields(KeymapRegistry)
        if f.name not in ("modes", "legacy_card_block_brackets")
    ]
    for scope_name in sorted(scope_names):
        scope_obj = getattr(registry, scope_name)
        try:
            scope_fields = dataclass_fields(scope_obj)
        except TypeError:
            continue
        for f in scope_fields:
            feature_id = tui_id(scope_name, f.name)
            if feature_id in NAVIGATION_ACTIONS or feature_id in by_id:
                continue
            by_id[feature_id] = Entry(
                id=feature_id,
                ns="tui",
                area=f"tui.{scope_name}",
                kind="action",
                label=labels.get((scope_name, f.name), humanize(f.name)),
            )

    for mode_name in sorted(_BUILTIN_MODE_CLASSES):
        cls = _BUILTIN_MODE_CLASSES[mode_name]
        short = mode_name[: -len("_mode")] if mode_name.endswith("_mode") else mode_name
        instance = registry.modes.get(mode_name) or cls()
        flat: dict[str, None] = {}
        _flatten_mode_keys(short, dict(instance.keys), flat)
        for dotted in sorted(flat):
            feature_id = f"tui:{dotted}"
            if feature_id in NAVIGATION_ACTIONS or feature_id in by_id:
                continue
            by_id[feature_id] = Entry(
                id=feature_id,
                ns="tui",
                area=f"tui.{short}",
                kind="mode_key",
                label=humanize(dotted.split(".")[-1]),
                parent=_mode_parent(mode_name),
            )

    return sorted(by_id.values(), key=lambda e: e.id)
