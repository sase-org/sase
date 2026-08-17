"""Rendering helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sase.amd._config import resolve_markdown_template_override
from sase.amd.inline_memory import validate_short_memory_structure
from sase.amd.init import AmdMemorySyncPlan
from sase.directory_map_assets import read_directory_map_asset
from sase.mdtemplates import render_markdown_template
from sase.memory.inventory import MemoryStats, stats_for_text
from sase.memory.notes import (
    AGENTS_PARENT,
    GeneratedLongMemoryNote,
    MemoryNote,
    apply_memory_frontmatter,
    collapse_description,
    discover_memory_notes,
    parse_memory_note_text,
)
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
    memory_write_root,
)

from .formatting import format_generated_memory_markdown
from .glossary import GeneratedGlossaryMemory
from .models import LinkedRepoMemoryEntry, MemoryExpectedFile

MEMORY_DIRECTORY_MAP_FILENAME = "memory-directory-map.png"
MEMORY_DIRECTORY_MAP_RELATIVE_PATH = (
    CANONICAL_MEMORY_RELATIVE_ROOT / "assets" / MEMORY_DIRECTORY_MAP_FILENAME
)
MEMORY_SASE_TEMPLATE_FILENAME = "memory-sase.template.md"
MEMORY_SASE_BEADS_TEMPLATE_FILENAME = "memory-sase-beads.template.md"
MEMORY_SASE_FLAGS_TEMPLATE_FILENAME = "memory-sase-flags.template.md"
MEMORY_SASE_SIZES_TEMPLATE_FILENAME = "memory-sase-sizes.template.md"
MEMORY_README_TEMPLATE_FILENAME = "memory-README.template.md"
_MEMORY_TEMPLATE_PACKAGE = "sase.main.init_memory"
_MEMORY_SASE_TEMPLATE_VARS = frozenset({"project_name", "linked_repo_entries"})
_MEMORY_README_TEMPLATE_VARS = frozenset(
    {
        "memory_notes",
        "total_notes",
        "short_notes",
        "long_notes",
        "total_lines",
        "total_tokens",
    }
)


@dataclass(frozen=True)
class _MemoryReadmeNote:
    note: MemoryNote
    stats: MemoryStats


@dataclass(frozen=True)
class _GeneratedLongMemorySpec:
    template_filename: str
    relative_path: Path
    parent: str
    detail: str


def _linked_repo_list_item(entry: LinkedRepoMemoryEntry) -> str:
    return f"- `{entry.name}`: {entry.description}"


def _render_sase_memory(
    root: Path,
    entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
) -> tuple[str | None, str | None]:
    override, resolve_error = resolve_markdown_template_override(
        root,
        memory_key="sase_template",
        legacy_key="memory_sase_template",
        user_filename=MEMORY_SASE_TEMPLATE_FILENAME,
    )
    if resolve_error is not None:
        return None, resolve_error
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{MEMORY_SASE_TEMPLATE_FILENAME}",
        required_variables=_MEMORY_SASE_TEMPLATE_VARS,
        context={
            "project_name": project_name or "",
            "linked_repo_entries": "\n".join(
                _linked_repo_list_item(entry) for entry in entries
            ),
        },
        override_path=override,
    )
    if render_error is not None or rendered is None:
        return None, render_error or "failed to render sase/memory/sase.md template"
    formatted = format_generated_memory_markdown(rendered)
    structure_error = validate_short_memory_structure(formatted)
    if structure_error is not None:
        label = (
            str(override)
            if override is not None
            else f"packaged {MEMORY_SASE_TEMPLATE_FILENAME}"
        )
        return None, f"{label}: {structure_error}"
    return formatted, None


def _generated_sase_memory_relative_path() -> Path:
    return CANONICAL_MEMORY_RELATIVE_ROOT / "sase.md"


def generated_glossary_memory_relative_path() -> Path:
    return CANONICAL_MEMORY_RELATIVE_ROOT / "glossary.md"


def _generated_beads_memory_relative_path() -> Path:
    return CANONICAL_MEMORY_RELATIVE_ROOT / "sase_beads.md"


def _generated_flags_memory_relative_path() -> Path:
    return CANONICAL_MEMORY_RELATIVE_ROOT / "sase_flags.md"


def _generated_sizes_memory_relative_path() -> Path:
    return CANONICAL_MEMORY_RELATIVE_ROOT / "sase_sizes.md"


_GENERATED_BEADS_MEMORY_SPEC = _GeneratedLongMemorySpec(
    template_filename=MEMORY_SASE_BEADS_TEMPLATE_FILENAME,
    relative_path=_generated_beads_memory_relative_path(),
    parent=AGENTS_PARENT,
    detail="generated SASE bead memory",
)
_GENERATED_FLAGS_MEMORY_SPEC = _GeneratedLongMemorySpec(
    template_filename=MEMORY_SASE_FLAGS_TEMPLATE_FILENAME,
    relative_path=_generated_flags_memory_relative_path(),
    parent=AGENTS_PARENT,
    detail="generated SASE feature flag memory",
)
_GENERATED_SIZES_MEMORY_SPEC = _GeneratedLongMemorySpec(
    template_filename=MEMORY_SASE_SIZES_TEMPLATE_FILENAME,
    relative_path=_generated_sizes_memory_relative_path(),
    parent=_generated_beads_memory_relative_path().as_posix(),
    detail="generated SASE size memory",
)
_GENERATED_PROJECT_LONG_MEMORY_SPECS = (
    _GENERATED_BEADS_MEMORY_SPEC,
    _GENERATED_FLAGS_MEMORY_SPEC,
    _GENERATED_SIZES_MEMORY_SPEC,
)


def render_generated_sase_memory_body(
    root: Path,
    entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Render the stable ``sase/memory/sase.md`` body or return a blocker."""
    return _render_sase_memory(root, entries, project_name=project_name)


def _generated_sase_memory_content(generated_sase_body: str) -> str:
    return apply_memory_frontmatter(
        generated_sase_body,
        note_type="short",
        parent=AGENTS_PARENT,
    )


def _render_generated_long_memory_content(
    *,
    template_filename: str,
    relative_path: Path,
    parent: str,
) -> tuple[str | None, str | None]:
    """Render a packaged generated long memory note."""
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{template_filename}",
        required_variables=frozenset(),
        context={},
    )
    if render_error is not None or rendered is None:
        return (
            None,
            render_error or f"failed to render {relative_path.as_posix()} template",
        )
    formatted = format_generated_memory_markdown(rendered)
    note = parse_memory_note_text(
        formatted,
        relative_path,
    )
    if note.description is None:
        return (
            None,
            f"packaged {template_filename}: "
            "generated long memory note must have a description",
        )
    canonical_parent = (
        AGENTS_PARENT
        if parent == AGENTS_PARENT
        else canonical_memory_reference(parent).as_posix()
    )
    return (
        apply_memory_frontmatter(
            formatted,
            note_type="long",
            parent=canonical_parent,
            description=note.description,
        ),
        None,
    )


def _render_generated_project_long_memory_content(
    spec: _GeneratedLongMemorySpec,
) -> tuple[str | None, str | None]:
    """Render one generated project-only long memory note."""
    return _render_generated_long_memory_content(
        template_filename=spec.template_filename,
        relative_path=spec.relative_path,
        parent=spec.parent,
    )


def render_generated_project_long_memory_contents() -> tuple[
    dict[str, str], str | None
]:
    """Render generated project-only long memory notes keyed by relative path."""
    contents: dict[str, str] = {}
    for spec in _GENERATED_PROJECT_LONG_MEMORY_SPECS:
        content, error = _render_generated_project_long_memory_content(spec)
        if error is not None or content is None:
            return {}, error or f"failed to render {spec.relative_path.as_posix()}"
        contents[spec.relative_path.as_posix()] = content
    return contents, None


def read_memory_directory_map_bytes() -> bytes:
    return read_directory_map_asset(
        "sase.memory",
        MEMORY_DIRECTORY_MAP_FILENAME,
    )


def _memory_note_overlay_by_relative_path(
    root: Path,
    overlay: dict[Path, str],
) -> dict[str, str]:
    root_resolved = root.resolve(strict=False)
    result: dict[str, str] = {}
    for path, content in overlay.items():
        resolved = path.resolve(strict=False)
        try:
            relative = resolved.relative_to(root_resolved)
        except ValueError:
            relative = path
        result[canonical_memory_reference(relative).as_posix()] = content
    return result


def _read_memory_note_text(root: Path, relative_path: str) -> str | None:
    try:
        return (root / relative_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _discover_memory_readme_notes(
    root: Path,
    *,
    overlay: dict[Path, str],
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> tuple[_MemoryReadmeNote, ...]:
    text_by_relative_path = {
        note.relative_path: _read_memory_note_text(
            root, note.source_relative_path.as_posix()
        )
        for note in discover_memory_notes(root, source_memory_root=source_memory_root)
        if note.relative_path not in excluded_note_paths
    }
    text_by_relative_path.update(_memory_note_overlay_by_relative_path(root, overlay))

    rows: list[_MemoryReadmeNote] = []
    for relative_path, text in text_by_relative_path.items():
        if text is None:
            continue
        note = parse_memory_note_text(text, relative_path)
        rows.append(_MemoryReadmeNote(note=note, stats=stats_for_text(text)))

    rows.sort(
        key=lambda row: (
            {"short": 0, "long": 1}.get(row.note.type or "", 2),
            row.note.relative_path,
        )
    )
    return tuple(rows)


def _note_description(note: MemoryNote) -> str:
    return collapse_description(note.description) or "No description set."


def _note_type(note: MemoryNote) -> str:
    return note.type or "missing"


def _render_memory_notes(
    note_rows: tuple[_MemoryReadmeNote, ...],
) -> str:
    if not note_rows:
        return ""

    lines: list[str] = []
    for index, row in enumerate(note_rows):
        if index:
            lines.append("")
        note = row.note
        lines.extend(
            [
                f"### `{note.relative_path}`",
                "",
                f"- Type: `{_note_type(note)}`",
                f"- Description: {_note_description(note)}",
                f"- Parent: `{note.parent}`",
                f"- Lines: {row.stats.line_count}",
                f"- Approx. tokens: {row.stats.approx_token_count}",
            ]
        )
    return "\n".join(lines)


def _render_memory_readme(
    root: Path,
    *,
    overlay: dict[Path, str] | None = None,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> tuple[str | None, str | None]:
    note_rows = _discover_memory_readme_notes(
        root,
        overlay=overlay or {},
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    override, resolve_error = resolve_markdown_template_override(
        root,
        memory_key="readme_template",
        legacy_key="memory_readme_template",
        user_filename=MEMORY_README_TEMPLATE_FILENAME,
    )
    if resolve_error is not None:
        return None, resolve_error
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{MEMORY_README_TEMPLATE_FILENAME}",
        required_variables=_MEMORY_README_TEMPLATE_VARS,
        context={
            "memory_notes": _render_memory_notes(note_rows),
            "total_notes": len(note_rows),
            "short_notes": sum(1 for row in note_rows if row.note.type == "short"),
            "long_notes": sum(1 for row in note_rows if row.note.type == "long"),
            "total_lines": sum(row.stats.line_count for row in note_rows),
            "total_tokens": sum(row.stats.approx_token_count for row in note_rows),
        },
        override_path=override,
    )
    if render_error is not None or rendered is None:
        return None, render_error or "failed to render sase/memory/README.md template"
    return format_generated_memory_markdown(rendered), None


def render_expected_memory_files(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    amd_sync: AmdMemorySyncPlan | None = None,
    generated_sase_body: str | None = None,
    generated_project_long_contents: Mapping[str, str] | None = None,
    generated_glossary: GeneratedGlossaryMemory | None = None,
    source_memory_root: Path | None = None,
    include_project_memory: bool = False,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> tuple[tuple[MemoryExpectedFile, ...], str | None]:
    if generated_sase_body is None:
        generated_sase_body, render_error = render_generated_sase_memory_body(
            root, linked_entries, project_name=project_name
        )
        if render_error is not None or generated_sase_body is None:
            return (), render_error or "failed to render sase/memory/sase.md template"
    if include_project_memory and generated_project_long_contents is None:
        generated_project_long_contents, render_error = (
            render_generated_project_long_memory_contents()
        )
        if render_error is not None:
            return (
                (),
                render_error,
            )
    generated_sase_path = root / _generated_sase_memory_relative_path()
    generated_sase_content = _generated_sase_memory_content(generated_sase_body)
    note_overlay = {
        generated_sase_path: generated_sase_content,
    }
    if generated_glossary is not None:
        note_overlay[root / generated_glossary_memory_relative_path()] = (
            generated_glossary.content
        )
    if include_project_memory and generated_project_long_contents is not None:
        for relative_path, content in generated_project_long_contents.items():
            note_overlay[root / relative_path] = content
    if amd_sync is not None:
        note_overlay.update(
            {update.path: update.content for update in amd_sync.description_updates}
        )
    rendered_readme, readme_error = _render_memory_readme(
        root,
        overlay=note_overlay,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    if readme_error is not None or rendered_readme is None:
        return (), readme_error or "failed to render sase/memory/README.md template"
    expected: list[MemoryExpectedFile] = [
        MemoryExpectedFile(
            path=generated_sase_path,
            content=generated_sase_content,
            detail="generated SASE memory",
        ),
    ]
    if include_project_memory and generated_project_long_contents is not None:
        content_by_relative_path = dict(generated_project_long_contents)
        for spec in _GENERATED_PROJECT_LONG_MEMORY_SPECS:
            generated_long_content = content_by_relative_path.get(
                spec.relative_path.as_posix()
            )
            if generated_long_content is None:
                continue
            expected.append(
                MemoryExpectedFile(
                    path=root / spec.relative_path,
                    content=generated_long_content,
                    detail=spec.detail,
                )
            )
    if generated_glossary is not None:
        expected.append(
            MemoryExpectedFile(
                path=root / generated_glossary_memory_relative_path(),
                content=generated_glossary.content,
                detail="generated glossary memory",
            )
        )
    expected.extend(
        [
            MemoryExpectedFile(
                path=memory_write_root(root) / "README.md",
                content=rendered_readme,
                detail="memory README",
            ),
            MemoryExpectedFile(
                path=root / MEMORY_DIRECTORY_MAP_RELATIVE_PATH,
                content=read_memory_directory_map_bytes(),
                detail="memory directory map asset",
            ),
        ]
    )
    if amd_sync is not None and amd_sync.agents_content is not None:
        expected.extend(
            MemoryExpectedFile(
                path=update.path,
                content=update.content,
                detail="long-memory description frontmatter",
                stale_operation="update",
            )
            for update in amd_sync.description_updates
        )
        expected.append(
            MemoryExpectedFile(
                path=root / "AGENTS.md",
                content=format_generated_memory_markdown(amd_sync.agents_content),
                detail="managed AGENTS.md",
                stale_operation="overwrite",
            )
        )
    elif amd_sync is not None and amd_sync.fallback_agents_content is not None:
        expected.append(
            MemoryExpectedFile(
                path=root / "AGENTS.md",
                content=format_generated_memory_markdown(
                    amd_sync.fallback_agents_content
                ),
                detail="agent instruction file",
                write_policy="create_if_missing",
            )
        )
    return tuple(expected), None


def generated_short_notes(generated_sase_body: str) -> dict[str, str]:
    """Return freshly generated short-note bodies keyed by relative path."""
    return {_generated_sase_memory_relative_path().as_posix(): generated_sase_body}


def generated_long_notes(
    generated_contents: Mapping[str, str],
) -> dict[str, GeneratedLongMemoryNote]:
    """Return generated long-note metadata keyed by relative path."""
    result: dict[str, GeneratedLongMemoryNote] = {}
    for relative_path, content in generated_contents.items():
        note = parse_memory_note_text(content, relative_path)
        if note.description is None:
            raise ValueError(
                f"generated long memory note lacks a description: {relative_path}"
            )
        result[relative_path] = GeneratedLongMemoryNote(
            description=note.description,
            parent=note.parent,
        )
    return result
