"""Views, modals, macros, skills, config, automation, and plugin entries."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.footprint._catalog_gen_shared import (
    Entry,
    first_line,
    humanize,
    load_bundled_config,
    package_resource,
)
from sase.footprint.ids import (
    FIRST_PARTY_PLUGIN_COMMANDS,
    admin_view_id,
    modal_id,
    sanitize,
    stats_view_id,
    tab_view_id,
)


def gen_views() -> list[Entry]:
    """Generate entries for tabs, subtabs, center tabs, and stats views."""
    from typing import get_args

    from sase.ace.tui.artifact_tabs import FIXED_ARTIFACTS_SUBTAB_ORDER
    from sase.ace.tui.modals.config_center_catalog import CenterTab
    from sase.ace.tui.tab_order import TabName
    from sase.stats.registry import STATISTICS_VIEW_SPECS

    out: list[Entry] = []
    seen: set[str] = set()
    for name in sorted(set(get_args(TabName)) | set(FIXED_ARTIFACTS_SUBTAB_ORDER)):
        feature_id = tab_view_id(name)
        if feature_id in seen:
            continue
        seen.add(feature_id)
        out.append(
            Entry(
                id=feature_id,
                ns="view",
                area="views",
                kind="view",
                label=f"{humanize(name)} tab",
            )
        )
    for name in sorted(set(get_args(CenterTab))):
        out.append(
            Entry(
                id=admin_view_id(name),
                ns="view",
                area="views",
                kind="view",
                label=f"Config center {name}",
            )
        )
    for spec in STATISTICS_VIEW_SPECS:
        out.append(
            Entry(
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


def gen_modals() -> list[Entry]:
    """Generate entries for every TUI modal (AST scan, transitive)."""
    tui_root = package_resource("ace", "tui")
    out: list[Entry] = []
    for class_name, src in _iter_modal_classes(tui_root):
        feature_id = modal_id(class_name)
        label_base = feature_id.split("view:modal.", 1)[1]
        out.append(
            Entry(
                id=feature_id,
                ns="view",
                area="modals",
                kind="modal",
                label=f"{humanize(label_base)} dialog",
                src=src,
            )
        )
    return out


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
            return first_line(desc)
    return None


def gen_macros() -> list[Entry]:
    """Generate entries for bundled macros (filename stems)."""
    macros_dir = package_resource("macros")
    out: list[Entry] = []
    if not macros_dir.is_dir():
        return out
    paths = sorted(macros_dir.glob("*.md")) + sorted(macros_dir.glob("*.yml"))
    for path in paths:
        name = sanitize(path.stem)
        label = _frontmatter_description(path) or f"Macro {name}"
        out.append(
            Entry(
                id=f"macro:{name}",
                ns="macro",
                area="macros",
                kind="macro",
                label=label,
                src=f"sase/macros/{path.name}",
            )
        )
    return out


def gen_skills() -> list[Entry]:
    """Generate entries for generated skill sources (filename stems)."""
    from sase.macro.loader_skills import SKILL_FRAME_TEMPLATE_FILENAME

    skills_dir = package_resource("macros", "skills")
    out: list[Entry] = []
    if not skills_dir.is_dir():
        return out
    for path in sorted(skills_dir.glob("*.md")):
        if path.name == SKILL_FRAME_TEMPLATE_FILENAME:
            continue
        name = sanitize(path.stem)
        label = _frontmatter_description(path) or f"Skill {name}"
        out.append(
            Entry(
                id=f"skill:{name}",
                ns="skill",
                area="skills",
                kind="skill",
                label=label,
                src=f"sase/macros/skills/{path.name}",
            )
        )
    return out


def _walk_config(node: Any, prefix: str, out: list[Entry]) -> None:
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
            Entry(
                id=f"config:{path}",
                ns="config",
                area=f"config.{top}",
                kind="config",
                label=humanize(path.split(".")[-1]),
                src="sase/default_config.yml",
            )
        )


def gen_config(cfg: dict[str, Any] | None = None) -> list[Entry]:
    """Generate entries for bundled config leaves (lists count as one)."""
    if cfg is None:
        cfg = load_bundled_config()
    out: list[Entry] = []
    _walk_config(cfg, "", out)
    return out


def gen_auto(cfg: dict[str, Any] | None = None) -> list[Entry]:
    """Generate entries for AXE routines and jobs."""
    if cfg is None:
        cfg = load_bundled_config()
    out: list[Entry] = []
    routines = (cfg.get("axe") or {}).get("routines") or {}
    if not isinstance(routines, dict):
        return out
    for routine in sorted(routines):
        info = routines[routine] or {}
        routine_id = f"auto:axe.{sanitize(str(routine))}"
        routine_label = info.get("description") if isinstance(info, dict) else None
        out.append(
            Entry(
                id=routine_id,
                ns="auto",
                area="automation",
                kind="auto",
                label=first_line(routine_label)
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
                Entry(
                    id=f"{routine_id}.{job_name}",
                    ns="auto",
                    area="automation",
                    kind="auto",
                    label=first_line(job_label)
                    if isinstance(job_label, str)
                    else humanize(job_name),
                    parent=routine_id,
                    src="sase/default_config.yml",
                )
            )
    return out


def gen_plugins() -> list[Entry]:
    """Generate entries for first-party plugin command words."""
    return [
        Entry(
            id=f"plugin:{word}",
            ns="plugin",
            area="plugins",
            kind="plugin",
            label=f"Plugin command {word}",
        )
        for word in FIRST_PARTY_PLUGIN_COMMANDS
    ]
