"""Bundle section assembly: package split, units, overlays, and layout.

This module owns the section-level composition (E2 decisions 5-7): splitting
the inlined contract template into package sections, turning memory units
into home/project sections, applying lifecycle overlays and shadowing, and
ordering the bundle layout. Only its miss-path helpers import the heavy
composition modules; the cache-hit path never reaches this module.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.instructions.directives import (
    has_provider_directive,
    provider_adapter_path,
    provider_directive,
    provider_display_name,
)
from sase.instructions.facts import InstructionFacts

#: Frame title when neither the project nor the home root resolves one.
DEFAULT_FRAME_TITLE = "SASE Agent Instructions"

#: Relative path of the generated contract note treated as superseded input.
GENERATED_CONTRACT_RELATIVE_PATH = "sase/memory/sase.md"

#: Stable manifest source path for the packaged contract template.
PACKAGED_TEMPLATE_SOURCE_PATH = (
    "sase/main/init_memory/templates/memory-sase.template.md"
)

#: Stable manifest source path for the packaged helper template.
HELPER_TEMPLATE_SOURCE_PATH = (
    "sase/llm_provider/templates/claude_helper_instructions.md"
)

_INVALID_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


class InstructionCompileError(ValueError):
    """Raised when a bundle cannot be compiled from its inputs."""


@dataclass
class SectionBuilder:
    """Mutable section accumulator; excluded sections carry no bytes."""

    id: str
    layer: str
    lifecycle: str = "neutral"
    required: bool = False
    provider_specific: bool = False
    text: str | None = None
    reason: str | None = None
    shadowed_by: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)


def section_slug(text: str) -> str:
    """Return the section-id slug for a note stem or template heading."""
    slug = _INVALID_SLUG_RE.sub("_", text.strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug or "section"


def tokens_estimate(text: str) -> int:
    """Return the ``tokens_est`` estimate (``ceil(len/4)``) for *text*."""
    return -(-len(text) // 4)


def _git_blob_oid(data: bytes) -> str:
    """Return the git blob sha1 object id for *data* (40 lowercase hex)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _rel_posix(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _source_for_file(
    *, scope: str, kind: str, root: Path | None, path: Path, fallback: bytes
) -> dict[str, Any]:
    """Return a manifest source for *path*, relativized against *root*."""
    try:
        data = path.read_bytes()
    except OSError:
        data = fallback
        source: dict[str, Any] = {
            "scope": scope,
            "kind": "generated" if kind != "generated" else kind,
            "path": path.as_posix() if root is None else _rel_posix(root, path),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return source
    if root is not None:
        rel = _rel_posix(root, path)
    else:
        rel = path.as_posix()
    return {
        "scope": scope,
        "kind": kind,
        "path": rel,
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob_oid": _git_blob_oid(data),
    }


def _normalize_section_text(text: str) -> str:
    """Return section bytes: stripped of trailing newlines plus two."""
    return text.rstrip("\n") + "\n\n"


def _overlay_exclusion(
    facts: InstructionFacts, *, lifecycle: str, section_id: str
) -> str | None:
    """Return the exclusion reason for a lifecycle section, or null."""
    if lifecycle == "neutral":
        return None
    if facts.mode in ("interactive", "export"):
        return "mode"
    if lifecycle == "root" and not (
        facts.actor == "sase_root" and facts.mode == "runtime"
    ):
        return "overlay"
    if lifecycle == "helper" and not (
        facts.actor == "native_helper" and facts.mode == "runtime"
    ):
        return "overlay"
    if lifecycle not in ("root", "helper"):
        raise InstructionCompileError(
            f"section {section_id!r} has unknown lifecycle {lifecycle!r}"
        )
    return None


def _package_subsection_id(heading: str) -> tuple[str, str, bool]:
    """Map a template H4 heading to ``(section id, lifecycle, required)``."""
    normalized = heading.strip()
    if normalized == "SASE Memory":
        return "pkg.sase.memory", "neutral", False
    lowered = normalized.lower()
    if "ephemeral" in lowered and "workspace director" in lowered:
        return "pkg.sase.workspaces", "neutral", False
    if normalized == "Repositories":
        return "pkg.sase.repos", "neutral", False
    if normalized == "SASE Final Declaration":
        return "pkg.root.final_declaration", "root", True
    return f"pkg.sase.{section_slug(normalized)}", "neutral", False


_HEADING_RE = re.compile(r"^(#{4})\s+(.*\S)\s*$")


def _split_package_sections(
    package_text: str,
    *,
    template_path: str,
    template_sha256: str,
    template_blob_oid: str | None,
    facts: InstructionFacts,
    repos_config_sources: list[dict[str, Any]],
) -> list[SectionBuilder]:
    """Split inlined contract text into package sections (decision 5)."""
    lines = package_text.splitlines()
    heading_end = len(lines)
    in_fence = False
    fence_marker = ""
    breaks: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            marker = stripped.split()[0] if stripped.split() else "```"
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif stripped.startswith(fence_marker):
                in_fence = False
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            if heading_end == len(lines):
                heading_end = index
            breaks.append((index, match.group(2)))
    head_text = "\n".join(lines[:heading_end]).strip("\n")
    sections = [
        SectionBuilder(
            id="pkg.sase.heading",
            layer="package",
            text=head_text,
            sources=[
                {
                    "scope": "package",
                    "kind": "package_template",
                    "path": template_path,
                    "sha256": template_sha256,
                    **({"blob_oid": template_blob_oid} if template_blob_oid else {}),
                }
            ],
        )
    ]
    for order, (start, heading) in enumerate(breaks):
        end = breaks[order + 1][0] if order + 1 < len(breaks) else len(lines)
        section_id, lifecycle, required = _package_subsection_id(heading)
        sources: list[dict[str, Any]] = [
            {
                "scope": "package",
                "kind": "package_template",
                "path": template_path,
                "sha256": template_sha256,
                **({"blob_oid": template_blob_oid} if template_blob_oid else {}),
            }
        ]
        if section_id == "pkg.sase.repos":
            sources.extend(repos_config_sources)
        builder = SectionBuilder(
            id=section_id,
            layer="package",
            lifecycle=lifecycle,
            required=required,
            text="\n".join(lines[start:end]).strip("\n"),
            sources=sources,
        )
        reason = _overlay_exclusion(facts, lifecycle=lifecycle, section_id=section_id)
        if reason is not None:
            builder.text = None
            builder.reason = reason
        sections.append(builder)
    return sections


def _resolve_template_file(project_root: Path) -> Path | None:
    """Return the contract template file backing the package render."""
    from sase.amd._config import resolve_markdown_template_override

    override, error = resolve_markdown_template_override(
        project_root,
        memory_key="sase_template",
        legacy_key="memory_sase_template",
        user_filename="memory-sase.template.md",
    )
    if error is not None:
        raise InstructionCompileError(error)
    if override is not None:
        return override
    from sase.main.init_memory.root_rendering_notes import (
        MEMORY_SASE_TEMPLATE_FILENAME,
    )

    import importlib.resources

    try:
        path = (
            importlib.resources.files("sase.main.init_memory")
            / "templates"
            / MEMORY_SASE_TEMPLATE_FILENAME
        )
    except (ImportError, ValueError, TypeError) as exc:
        raise InstructionCompileError(
            f"packaged template is unavailable: {exc}"
        ) from exc
    return Path(str(path))


def _helper_section(facts: InstructionFacts) -> SectionBuilder:
    """Return the helper-contract section for *facts*."""
    from sase.llm_provider._claude_helper_channel import helper_template_path

    builder = SectionBuilder(
        id="pkg.helper.contract",
        layer="package",
        lifecycle="helper",
        required=True,
        sources=[],
    )
    try:
        template_text = helper_template_path().read_text(encoding="utf-8")
    except OSError as exc:
        raise InstructionCompileError(f"helper template is unavailable: {exc}") from exc
    builder.sources.append(
        {
            "scope": "package",
            "kind": "helper_template",
            "path": HELPER_TEMPLATE_SOURCE_PATH,
            "sha256": hashlib.sha256(template_text.encode("utf-8")).hexdigest(),
            "blob_oid": _git_blob_oid(template_text.encode("utf-8")),
        }
    )
    reason = _overlay_exclusion(facts, lifecycle="helper", section_id=builder.id)
    if reason is not None:
        builder.reason = reason
        return builder
    first, _, rest = template_text.partition("\n")
    if first.startswith("# "):
        body = "#### " + first[2:] + ("\n" + rest if rest else "")
    else:
        body = template_text
    builder.text = body.strip("\n")
    return builder


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
        source["blob_oid"] = _git_blob_oid(data)
    return source


def _superseded_section(
    scope: str, unit: Any, root: Path, project: str | None
) -> SectionBuilder:
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


def _shadowed_section(scope: str, unit: Any, root: Path) -> SectionBuilder:
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


def _core_section(scope: str, unit: Any, root: Path) -> SectionBuilder:
    prefix = "home" if scope == "home" else "proj"
    return SectionBuilder(
        id=f"{prefix}.core.{section_slug(unit.stem)}",
        layer="home" if scope == "home" else "project",
        text=unit.text.strip("\n"),
        sources=[_section_source_for_unit(scope, unit, root)],
    )


def _reference_section(scope: str, unit: Any, root: Path) -> SectionBuilder:
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


def _web_section(scope: str, unit: Any, root: Path) -> SectionBuilder:
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


def _frame_sections(
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


def section_wire_dict(section: SectionBuilder, *, offset: int | None) -> dict[str, Any]:
    """Return the wire-shaped section dict for one built section."""
    if section.text is not None:
        data = section.text.encode("utf-8")
        wire: dict[str, Any] = {
            "id": section.id,
            "layer": section.layer,
            "status": "included",
            "lifecycle": section.lifecycle,
            "required": section.required,
            "provider_specific": section.provider_specific,
            "offset": offset,
            "length": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "tokens_est": tokens_estimate(section.text),
            "sources": section.sources,
        }
        return wire
    return {
        "id": section.id,
        "layer": section.layer,
        "status": "excluded",
        "lifecycle": section.lifecycle,
        "required": section.required,
        "provider_specific": section.provider_specific,
        "tokens_est": 0,
        "sources": section.sources,
        "reason": section.reason,
        **({"shadowed_by": section.shadowed_by} if section.shadowed_by else {}),
    }


def _repos_config_sources(
    *,
    project_root: Path,
    project_config: Path,
    global_config: Path,
    project_entries: tuple[Any, ...],
    home_entries: tuple[Any, ...],
) -> list[dict[str, Any]]:
    """Return config sources for the merged Repositories section."""
    try:
        project_config_rel = project_config.relative_to(project_root).as_posix()
    except ValueError:
        project_config_rel = project_config.as_posix()
    repos_sources: list[dict[str, Any]] = []
    if project_entries:
        repos_sources.append(
            _source_for_file(
                scope="project",
                kind="config",
                root=project_root,
                path=project_config,
                fallback=b"",
            )
        )
        repos_sources[-1]["path"] = project_config_rel
    if home_entries:
        repos_sources.append(
            {
                "scope": "home",
                "kind": "config",
                "path": f"global/{global_config.name}",
            }
        )
    return repos_sources


def assemble_sections(
    facts: InstructionFacts,
    *,
    project_root: Path,
    home_root: Path,
    project_units: Any,
    home_units: Any,
    template_body: str,
    project_config: Path,
    global_config: Path,
    project_entries: tuple[Any, ...],
    home_entries: tuple[Any, ...],
) -> tuple[str, list[SectionBuilder]]:
    """Assemble ordered sections and bundle text from collected units."""
    from sase.amd.inline_memory import inline_memory_section

    sections: list[SectionBuilder] = []
    package_text = inline_memory_section(
        GENERATED_CONTRACT_RELATIVE_PATH, template_body
    )
    try:
        template_file = _resolve_template_file(project_root)
    except InstructionCompileError:
        template_file = None
    if template_file is not None:
        try:
            template_data = template_file.read_bytes()
        except OSError:
            template_data = template_body.encode("utf-8")
            template_file = None
    else:
        template_data = template_body.encode("utf-8")
    if template_file is not None:
        try:
            template_label = template_file.relative_to(project_root).as_posix()
        except ValueError:
            template_label = PACKAGED_TEMPLATE_SOURCE_PATH
    else:
        template_label = PACKAGED_TEMPLATE_SOURCE_PATH
    sections.extend(
        _split_package_sections(
            package_text,
            template_path=template_label,
            template_sha256=hashlib.sha256(template_data).hexdigest(),
            template_blob_oid=_git_blob_oid(template_data),
            facts=facts,
            repos_config_sources=_repos_config_sources(
                project_root=project_root,
                project_config=project_config,
                global_config=global_config,
                project_entries=project_entries,
                home_entries=home_entries,
            ),
        )
    )

    directive = (
        provider_directive(facts.provider)
        if has_provider_directive(facts.provider)
        else None
    )
    if directive is None:
        provider_builder = SectionBuilder(
            id=f"pkg.provider.{facts.provider}",
            layer="package",
            lifecycle="root",
            required=False,
            provider_specific=True,
            reason="no_directive",
            sources=[],
        )
    else:
        heading = (
            f"#### {provider_display_name(facts.provider)} Single-Turn Instructions"
        )
        provider_builder = SectionBuilder(
            id=f"pkg.provider.{facts.provider}",
            layer="package",
            lifecycle="root",
            required=True,
            provider_specific=True,
            text=f"{heading}\n\n{directive.strip()}",
            sources=[
                {
                    "scope": "package",
                    "kind": "provider_directive",
                    "path": provider_adapter_path(facts.provider),
                    "sha256": hashlib.sha256(directive.encode("utf-8")).hexdigest(),
                }
            ],
        )
        reason = _overlay_exclusion(
            facts, lifecycle="root", section_id=provider_builder.id
        )
        if reason is not None:
            provider_builder.text = None
            provider_builder.reason = reason
            provider_builder.required = False
    helper_builder = _helper_section(facts)
    helper_position = next(
        (
            index
            for index, section in enumerate(sections)
            if section.id == "pkg.root.final_declaration"
        ),
        len(sections),
    )
    sections.insert(helper_position + 1, helper_builder)
    sections.insert(helper_position + 2, provider_builder)

    project_paths = (
        {unit.relative_path for unit in project_units.core}
        | {unit.relative_path for unit in project_units.references}
        | {unit.relative_path for unit in project_units.webs}
    )
    excluded: list[SectionBuilder] = []
    export_mode = facts.mode == "export"
    for scope, root, units in (
        ("home", home_root, home_units),
        ("project", project_root, project_units),
    ):
        for unit in units.core:
            if unit.relative_path == GENERATED_CONTRACT_RELATIVE_PATH:
                excluded.append(_superseded_section(scope, unit, root, facts.project))
                continue
            if scope == "home" and unit.relative_path in project_paths:
                excluded.append(_shadowed_section(scope, unit, root))
                continue
            builder = _core_section(scope, unit, root)
            if export_mode and scope == "home":
                builder.text = None
                builder.reason = "mode"
                excluded.append(builder)
            else:
                sections.append(builder)
        for unit in units.references:
            if scope == "home" and unit.relative_path in project_paths:
                excluded.append(_shadowed_section(scope, unit, root))
                continue
            builder = _reference_section(scope, unit, root)
            if export_mode and scope == "home":
                builder.text = None
                builder.reason = "mode"
                excluded.append(builder)
            else:
                sections.append(builder)
        for unit in units.webs:
            if scope == "home" and unit.relative_path in project_paths:
                excluded.append(_shadowed_section(scope, unit, root))
                continue
            builder = _web_section(scope, unit, root)
            if export_mode and scope == "home":
                builder.text = None
                builder.reason = "mode"
                excluded.append(builder)
            else:
                sections.append(builder)

    package = [s for s in sections if s.layer == "package" and s.text is not None]
    package_excluded = [s for s in sections if s.layer == "package" and s.text is None]
    core = [
        s
        for s in sections
        if s.layer in ("home", "project") and ".core." in s.id and s.text is not None
    ]
    refs = [
        s
        for s in sections
        if s.layer in ("home", "project") and ".ref." in s.id and s.text is not None
    ]
    webs = [
        s
        for s in sections
        if s.layer in ("home", "project") and ".web." in s.id and s.text is not None
    ]
    # Creation order already encodes template order (package) and home-before-
    # project within each kind group, so the partitions stay stable as built.
    home_contributes = any(
        section.layer == "home" and section.text is not None for section in sections
    )
    frames = _frame_sections(
        project_units=project_units,
        home_units=home_units,
        home_contributes=home_contributes,
    )
    included: list[SectionBuilder] = [frames["title"]]
    if core:
        included.append(frames["core"])
    included.extend(package)
    included.extend(core)
    if refs:
        included.append(frames["reference"])
    included.extend(refs)
    if webs:
        included.append(frames["webs"])
    included.extend(webs)
    for section in included:
        section.text = _normalize_section_text(section.text or "")
    bundle_text = "".join(section.text or "" for section in included)
    wire_sections = list(included)
    wire_sections.extend(
        sorted([*package_excluded, *excluded], key=lambda section: section.id)
    )
    return bundle_text, wire_sections


__all__ = [
    "DEFAULT_FRAME_TITLE",
    "GENERATED_CONTRACT_RELATIVE_PATH",
    "HELPER_TEMPLATE_SOURCE_PATH",
    "InstructionCompileError",
    "PACKAGED_TEMPLATE_SOURCE_PATH",
    "SectionBuilder",
    "assemble_sections",
    "section_slug",
    "section_wire_dict",
    "tokens_estimate",
]
