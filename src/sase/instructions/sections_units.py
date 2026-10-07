"""Memory-unit and frame section builders for bundle assembly."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sase.instructions._sections_shared import git_blob_oid
from sase.instructions.sections_base import (
    DEFAULT_FRAME_TITLE,
    SectionBuilder,
    section_slug,
)


def _unit_source(
    scope: str, kind: str, root: Path, source_path: Path, fallback: str
) -> dict[str, Any]:
    try:
        rel = source_path.relative_to(root).as_posix()
    except ValueError:
        rel = source_path.as_posix()
    source: dict[str, Any] = {
        "scope": scope,
        "kind": kind,
        "path": rel,
        "sha256": hashlib.sha256(fallback.encode("utf-8")).hexdigest(),
    }
    try:
        data = source_path.read_bytes()
    except OSError:
        source["kind"] = "generated"
    else:
        source["sha256"] = hashlib.sha256(data).hexdigest()
        source["blob_oid"] = git_blob_oid(data)
    return source


def _unit_kind_group(unit: Any) -> str:
    text = type(unit).__name__
    if "Reference" in text:
        return "ref"
    if "Web" in text:
        return "web"
    return "core"


def _section_source_for_unit(scope: str, unit: Any, root: Path) -> dict[str, Any]:
    kind = {"core": "memory_note", "ref": "memory_note", "web": "memory_web"}[
        _unit_kind_group(unit)
    ]
    if kind == "memory_web":
        return _unit_source(scope, kind, root, unit.descriptor_source, unit.block)
    if _unit_kind_group(unit) == "ref":
        return _unit_source(scope, kind, root, unit.source_path, unit.source_bytes)
    return _unit_source(scope, kind, root, unit.source_path, unit.source_bytes)


def superseded_section(
    scope: str, unit: Any, root: Path, project: str | None
) -> SectionBuilder:
    """Return the superseded-input section for a generated-contract unit."""
    del project
    prefix = "home" if scope == "home" else "proj"
    return SectionBuilder(
        id=f"{prefix}.core.{section_slug(unit.stem)}",
        layer="home" if scope == "home" else "project",
        reason="superseded_input",
        sources=[
            _unit_source(
                scope, "memory_note", root, unit.source_path, unit.source_bytes
            )
        ],
    )


def shadowed_section(scope: str, unit: Any, root: Path) -> SectionBuilder:
    """Return the shadowed section when the other scope wins the unit."""
    kind_group = _unit_kind_group(unit)
    prefix = "home" if scope == "home" else "proj"
    counterpart = "proj" if scope == "home" else "home"
    return SectionBuilder(
        id=f"{prefix}.{kind_group}.{section_slug(unit.stem)}",
        layer="home" if scope == "home" else "project",
        reason="shadowed",
        shadowed_by=f"{counterpart}.{kind_group}.{section_slug(unit.stem)}",
        sources=[_section_source_for_unit(scope, unit, root)],
    )


def core_section(scope: str, unit: Any, root: Path) -> SectionBuilder:
    """Return the included section for a core memory unit."""
    prefix = "home" if scope == "home" else "proj"
    return SectionBuilder(
        id=f"{prefix}.core.{section_slug(unit.stem)}",
        layer="home" if scope == "home" else "project",
        text=unit.text.strip("\n"),
        sources=[_section_source_for_unit(scope, unit, root)],
    )


def reference_section(scope: str, unit: Any, root: Path) -> SectionBuilder:
    """Return the included section for a reference memory unit."""
    prefix = "home" if scope == "home" else "proj"
    sources = [_section_source_for_unit(scope, unit, root)]
    if unit.used_legacy_fallback:
        try:
            rel = "AGENTS.md"
            legacy = root / "AGENTS.md"
            fallback_text = (
                legacy.read_text(encoding="utf-8") if legacy.is_file() else ""
            )
        except OSError:
            fallback_text = ""
        sources.append(
            {
                "scope": scope,
                "kind": "legacy_fallback",
                "path": rel,
                **(
                    {"sha256": hashlib.sha256(fallback_text.encode()).hexdigest()}
                    if fallback_text
                    else {}
                ),
            }
        )
    return SectionBuilder(
        id=f"{prefix}.ref.{section_slug(unit.stem)}",
        layer="home" if scope == "home" else "project",
        text=unit.entry_text.strip("\n"),
        sources=sources,
    )


def web_section(scope: str, unit: Any, root: Path) -> SectionBuilder:
    """Return the included section for a memory-web unit."""
    prefix = "home" if scope == "home" else "proj"
    sources = [_section_source_for_unit(scope, unit, root)]
    for strand in unit.strand_files:
        strand_path = Path(strand)
        sources.append(_unit_source(scope, "memory_strands", root, strand_path, ""))
    return SectionBuilder(
        id=f"{prefix}.web.{section_slug(unit.stem)}",
        layer="home" if scope == "home" else "project",
        text=unit.block.strip("\n"),
        sources=sources,
    )


def frame_sections(
    *,
    project_units: Any,
    home_units: Any,
    home_contributes: bool,
) -> dict[str, SectionBuilder]:
    """Return the frame scaffolding sections keyed by kind group."""
    project_title = project_units.title
    home_title = home_units.title
    title = project_title or home_title or DEFAULT_FRAME_TITLE
    title_text = f"# {title}"
    if home_contributes and home_title:
        title_text += f"\nHome: {home_title}"
    return {
        "title": SectionBuilder(
            id="frame.title", layer="frame", required=True, text=title_text
        ),
        "core": SectionBuilder(
            id="frame.core",
            layer="frame",
            required=True,
            text=f"## Core Memory\n\n{project_units.intros.core}",
        ),
        "reference": SectionBuilder(
            id="frame.reference",
            layer="frame",
            required=True,
            text=f"## Reference Memory\n\n{project_units.intros.reference}",
        ),
        "webs": SectionBuilder(
            id="frame.webs",
            layer="frame",
            required=True,
            text=f"## Memory Webs\n\n{project_units.intros.webs}",
        ),
    }


__all__ = [
    "core_section",
    "frame_sections",
    "reference_section",
    "shadowed_section",
    "superseded_section",
    "web_section",
]
