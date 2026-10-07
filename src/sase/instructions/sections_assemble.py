"""Ordered bundle assembly from package sections and memory units."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sase.instructions._sections_shared import (
    InstructionCompileError,
    git_blob_oid,
    overlay_exclusion,
)
from sase.instructions.directives import (
    has_provider_directive,
    provider_adapter_path,
    provider_directive,
    provider_display_name,
)
from sase.instructions.facts import InstructionFacts
from sase.instructions.sections_base import (
    GENERATED_CONTRACT_RELATIVE_PATH,
    HELPER_TEMPLATE_SOURCE_PATH,
    PACKAGED_TEMPLATE_SOURCE_PATH,
    SectionBuilder,
)
from sase.instructions.sections_package import (
    repos_config_sources,
    split_package_sections,
)
from sase.instructions.sections_units import (
    core_section,
    frame_sections,
    reference_section,
    shadowed_section,
    superseded_section,
    web_section,
)


def _normalize_section_text(text: str) -> str:
    """Return section bytes: stripped of trailing newlines plus two."""
    return text.rstrip("\n") + "\n\n"


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
            "blob_oid": git_blob_oid(template_text.encode("utf-8")),
        }
    )
    reason = overlay_exclusion(facts, lifecycle="helper", section_id=builder.id)
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
        split_package_sections(
            package_text,
            template_path=template_label,
            template_sha256=hashlib.sha256(template_data).hexdigest(),
            template_blob_oid=git_blob_oid(template_data),
            facts=facts,
            repos_config_sources=repos_config_sources(
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
        reason = overlay_exclusion(
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
                excluded.append(superseded_section(scope, unit, root, facts.project))
                continue
            if scope == "home" and unit.relative_path in project_paths:
                excluded.append(shadowed_section(scope, unit, root))
                continue
            builder = core_section(scope, unit, root)
            if export_mode and scope == "home":
                builder.text = None
                builder.reason = "mode"
                excluded.append(builder)
            else:
                sections.append(builder)
        for unit in units.references:
            if scope == "home" and unit.relative_path in project_paths:
                excluded.append(shadowed_section(scope, unit, root))
                continue
            builder = reference_section(scope, unit, root)
            if export_mode and scope == "home":
                builder.text = None
                builder.reason = "mode"
                excluded.append(builder)
            else:
                sections.append(builder)
        for unit in units.webs:
            if scope == "home" and unit.relative_path in project_paths:
                excluded.append(shadowed_section(scope, unit, root))
                continue
            builder = web_section(scope, unit, root)
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
    frames = frame_sections(
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
    "assemble_sections",
]
