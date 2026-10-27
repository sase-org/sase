"""Generator for the checked-in Footprint feature catalog.

Walks every sase registry into a deterministic ``catalog.jsonl``:

- the full argparse tree (commands and option dests)
- ``build_command_catalog`` over the bundled keymap registry
- every ``KeymapRegistry`` scope field and every built-in mode keymap class
- top-level tabs, artifacts subtabs, config-center tabs, statistics views
- ``ModalScreen`` subclasses under ``src/sase/ace/tui/`` (AST scan)
- bundled macros, generated skill sources, config leaves, AXE jobs
- first-party plugin command words

Hot paths never import this module. The generator uses bundled defaults
only: it never reads the user's config, keymap overrides, saved queries, or
custom modes.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.resources
import json
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.footprint.ids import (
    CATALOG_SCHEMA,
    FIRST_PARTY_PLUGIN_COMMANDS,
    NAVIGATION_ACTIONS,
    admin_view_id,
    cli_id,
    cli_option_id,
    is_valid_feature_id,
    modal_id,
    sanitize,
    stats_view_id,
    tab_view_id,
    tui_id,
)

ENTRY_KEYS = ("id", "ns", "area", "kind", "label", "parent", "src")


@dataclass
class _Entry:
    id: str
    ns: str
    area: str
    kind: str
    label: str
    parent: str | None = None
    src: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ns": self.ns,
            "area": self.area,
            "kind": self.kind,
            "label": self.label,
            "parent": self.parent,
            "src": self.src,
        }


def _package_resource(*parts: str) -> Path:
    """Return a path under the installed ``sase`` package."""
    return Path(str(importlib.resources.files("sase").joinpath("/".join(parts))))


def _load_bundled_config() -> dict[str, Any]:
    """Load the bundled ``default_config.yml``."""
    return yaml.safe_load(_package_resource("default_config.yml").read_text())


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize() or name


def _first_line(text: str, limit: int = 160) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line[:limit] if len(line) <= limit else line[:limit].rstrip() + "…"


# ---------------------------------------------------------------------------
# CLI parser tree
# ---------------------------------------------------------------------------


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
    out: list[_Entry],
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
        _Entry(
            id=cmd_id,
            ns="cli",
            area=area,
            kind="command",
            label=_first_line(label),
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
                _Entry(
                    id=cli_option_id(cmd_id, dest),
                    ns="cli",
                    area=area,
                    kind="option",
                    label=f"Option --{dest} of {cmd_id}",
                    parent=cmd_id,
                    src=top_src,
                )
            )


def _gen_cli() -> list[_Entry]:
    """Generate entries for every parser node and option dest."""
    from sase.main.parser import create_parser

    out: list[_Entry] = []
    _walk_parser(create_parser(only=None), (), None, set(), out)
    return out


# ---------------------------------------------------------------------------
# TUI command catalog, scopes, and modes
# ---------------------------------------------------------------------------


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


def _gen_tui(registry: Any | None = None) -> list[_Entry]:
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
        cfg = _load_bundled_config()
        ace_cfg = cfg.get("ace", {})
        if not isinstance(ace_cfg, dict):
            ace_cfg = {}
        registry = load_keymap_registry(ace_cfg)

    by_id: dict[str, _Entry] = {}
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
        by_id[feature_id] = _Entry(
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
            by_id[feature_id] = _Entry(
                id=feature_id,
                ns="tui",
                area=f"tui.{scope_name}",
                kind="action",
                label=labels.get((scope_name, f.name), _humanize(f.name)),
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
            by_id[feature_id] = _Entry(
                id=feature_id,
                ns="tui",
                area=f"tui.{short}",
                kind="mode_key",
                label=_humanize(dotted.split(".")[-1]),
                parent=_mode_parent(mode_name),
            )

    return sorted(by_id.values(), key=lambda e: e.id)


# ---------------------------------------------------------------------------
# Views and modals
# ---------------------------------------------------------------------------


def _gen_views() -> list[_Entry]:
    """Generate entries for tabs, subtabs, center tabs, and stats views."""
    from typing import get_args

    from sase.ace.tui.tab_order import TabName
    from sase.ace.tui.modals.config_center_catalog import CenterTab
    from sase.ace.tui.artifact_tabs import FIXED_ARTIFACTS_SUBTAB_ORDER
    from sase.stats.registry import STATISTICS_VIEW_SPECS

    out: list[_Entry] = []
    seen: set[str] = set()
    for name in sorted(set(get_args(TabName)) | set(FIXED_ARTIFACTS_SUBTAB_ORDER)):
        feature_id = tab_view_id(name)
        if feature_id in seen:
            continue
        seen.add(feature_id)
        out.append(
            _Entry(
                id=feature_id,
                ns="view",
                area="views",
                kind="view",
                label=f"{_humanize(name)} tab",
            )
        )
    for name in sorted(set(get_args(CenterTab))):
        out.append(
            _Entry(
                id=admin_view_id(name),
                ns="view",
                area="views",
                kind="view",
                label=f"Config center {name}",
            )
        )
    for spec in STATISTICS_VIEW_SPECS:
        out.append(
            _Entry(
                id=stats_view_id(spec.id),
                ns="view",
                area="views",
                kind="view",
                label=spec.label,
                src="sase/stats/registry.py:STATISTICS_VIEW_SPECS",
            )
        )
    return out


def _iter_modal_classes(tui_root: Path) -> list[tuple[str, str]]:
    """Scan for ``ModalScreen``/``Screen`` subclasses; return (name, src)."""
    found: dict[str, str] = {}
    for path in sorted(tui_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = path.relative_to(tui_root.parent.parent).as_posix()
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
                elif isinstance(base, ast.Subscript) and isinstance(
                    base.value, ast.Name
                ):
                    bases.append(base.value.id)
            if (
                "ModalScreen" in bases
                or "Screen" in bases
                or any(b in found for b in bases)
            ):
                found[node.name] = f"{rel}:{node.name}"
    return sorted(found.items())


def _gen_modals() -> list[_Entry]:
    """Generate entries for every TUI modal (AST scan, transitive)."""
    tui_root = _package_resource("ace", "tui")
    out: list[_Entry] = []
    for class_name, src in _iter_modal_classes(tui_root):
        feature_id = modal_id(class_name)
        label_base = feature_id.split("view:modal.", 1)[1]
        out.append(
            _Entry(
                id=feature_id,
                ns="view",
                area="modals",
                kind="modal",
                label=f"{_humanize(label_base)} dialog",
                src=src,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Macros, skills, config, automation, plugins
# ---------------------------------------------------------------------------


def _frontmatter_description(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    lines = text.splitlines()[1:]
    front: list[str] = []
    for line in lines:
        if line.strip() in ("---", "..."):
            break
        front.append(line)
    try:
        data = yaml.safe_load("\n".join(front)) or {}
    except yaml.YAMLError:
        return None
    if isinstance(data, dict):
        desc = data.get("description")
        if isinstance(desc, str) and desc.strip():
            return _first_line(desc)
    return None


def _gen_macros() -> list[_Entry]:
    """Generate entries for bundled macros (filename stems)."""
    macros_dir = _package_resource("macros")
    out: list[_Entry] = []
    if not macros_dir.is_dir():
        return out
    paths = sorted(macros_dir.glob("*.md")) + sorted(macros_dir.glob("*.yml"))
    for path in paths:
        name = sanitize(path.stem)
        label = _frontmatter_description(path) or f"Macro {name}"
        out.append(
            _Entry(
                id=f"macro:{name}",
                ns="macro",
                area="macros",
                kind="macro",
                label=label,
                src=f"sase/macros/{path.name}",
            )
        )
    return out


def _gen_skills() -> list[_Entry]:
    """Generate entries for generated skill sources (filename stems)."""
    from sase.macro.loader_skills import SKILL_FRAME_TEMPLATE_FILENAME

    skills_dir = _package_resource("macros", "skills")
    out: list[_Entry] = []
    if not skills_dir.is_dir():
        return out
    for path in sorted(skills_dir.glob("*.md")):
        if path.name == SKILL_FRAME_TEMPLATE_FILENAME:
            continue
        name = sanitize(path.stem)
        label = _frontmatter_description(path) or f"Skill {name}"
        out.append(
            _Entry(
                id=f"skill:{name}",
                ns="skill",
                area="skills",
                kind="skill",
                label=label,
                src=f"sase/macros/skills/{path.name}",
            )
        )
    return out


def _walk_config(node: Any, prefix: str, out: list[_Entry]) -> None:
    if not isinstance(node, dict):
        return
    for key in sorted(node):
        if prefix == "" and key == "footprint":
            continue
        segment = sanitize(str(key))
        path = f"{prefix}.{segment}" if prefix else segment
        value = node[key]
        if isinstance(value, dict):
            _walk_config(value, path, out)
            continue
        top = path.split(".")[0]
        out.append(
            _Entry(
                id=f"config:{path}",
                ns="config",
                area=f"config.{top}",
                kind="config",
                label=_humanize(path.split(".")[-1]),
                src="sase/default_config.yml",
            )
        )


def _gen_config(cfg: dict[str, Any] | None = None) -> list[_Entry]:
    """Generate entries for bundled config leaves (lists count as one)."""
    if cfg is None:
        cfg = _load_bundled_config()
    out: list[_Entry] = []
    _walk_config(cfg, "", out)
    return out


def _gen_auto(cfg: dict[str, Any] | None = None) -> list[_Entry]:
    """Generate entries for AXE routines and jobs."""
    if cfg is None:
        cfg = _load_bundled_config()
    out: list[_Entry] = []
    routines = (cfg.get("axe") or {}).get("routines") or {}
    if not isinstance(routines, dict):
        return out
    for routine in sorted(routines):
        info = routines[routine] or {}
        routine_id = f"auto:axe.{sanitize(str(routine))}"
        routine_label = info.get("description") if isinstance(info, dict) else None
        out.append(
            _Entry(
                id=routine_id,
                ns="auto",
                area="automation",
                kind="auto",
                label=_first_line(routine_label)
                if isinstance(routine_label, str)
                else f"Axe {routine} routine",
                src="sase/default_config.yml",
            )
        )
        jobs = info.get("jobs", []) if isinstance(info, dict) else []
        for job in jobs:
            if not isinstance(job, dict) or "name" not in job:
                continue
            job_name = sanitize(str(job["name"]))
            job_label = job.get("description")
            out.append(
                _Entry(
                    id=f"{routine_id}.{job_name}",
                    ns="auto",
                    area="automation",
                    kind="auto",
                    label=_first_line(job_label)
                    if isinstance(job_label, str)
                    else _humanize(job_name),
                    parent=routine_id,
                    src="sase/default_config.yml",
                )
            )
    return out


def _gen_plugins() -> list[_Entry]:
    """Generate entries for first-party plugin command words."""
    return [
        _Entry(
            id=f"plugin:{word}",
            ns="plugin",
            area="plugins",
            kind="plugin",
            label=f"Plugin command {word}",
        )
        for word in FIRST_PARTY_PLUGIN_COMMANDS
    ]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


# symvision: tools/sync_footprint_catalog
def generate_entries() -> list[dict[str, Any]]:
    """Generate the full catalog as sorted entry dicts."""
    cfg = _load_bundled_config()
    entries: list[_Entry] = []
    entries.extend(_gen_cli())
    entries.extend(_gen_tui())
    entries.extend(_gen_views())
    entries.extend(_gen_modals())
    entries.extend(_gen_macros())
    entries.extend(_gen_skills())
    entries.extend(_gen_config(cfg))
    entries.extend(_gen_auto(cfg))
    entries.extend(_gen_plugins())
    by_id: dict[str, _Entry] = {}
    for entry in entries:
        if not is_valid_feature_id(entry.id):
            raise ValueError(f"generated invalid feature ID {entry.id!r}")
        by_id.setdefault(entry.id, entry)
    if len(by_id) != len(entries):
        seen: set[str] = set()
        dupes: set[str] = set()
        for entry in entries:
            if entry.id in seen:
                dupes.add(entry.id)
            seen.add(entry.id)
        raise ValueError(f"duplicate feature IDs: {sorted(dupes)}")
    ordered = [by_id[key] for key in sorted(by_id)]
    return [entry.to_dict() for entry in ordered]


def _compute_rev(entry_lines: list[str]) -> str:
    """Return the 12-hex rev for canonical entry lines."""
    digest = hashlib.sha256(("\n".join(entry_lines) + "\n").encode("utf-8"))
    return digest.hexdigest()[:12]


# symvision: tools/sync_footprint_catalog
def render_catalog(entries: list[dict[str, Any]]) -> str:
    """Render entries to ``catalog.jsonl`` text with a header line."""
    entry_lines = [
        json.dumps(entry, sort_keys=True, ensure_ascii=False) for entry in entries
    ]
    header = {
        "schema": CATALOG_SCHEMA,
        "rev": _compute_rev(entry_lines),
        "count": len(entry_lines),
    }
    return (
        json.dumps(header, sort_keys=True)
        + "\n"
        + "".join(line + "\n" for line in entry_lines)
    )


__all__ = [
    "generate_entries",
    "render_catalog",
]
