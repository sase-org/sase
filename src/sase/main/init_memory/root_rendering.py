"""Rendering helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sase.amd._config import resolve_markdown_template_override
from sase.amd.init import AmdMemorySyncPlan
from sase.directory_map_assets import read_directory_map_asset
from sase.mdtemplates import render_markdown_template
from sase.memory.inventory import MemoryStats, stats_for_text
from sase.memory.notes import (
    MemoryNote,
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
from .models import LinkedRepoMemoryEntry, MemoryExpectedFile
from .root_rendering_artifact_relations import (
    generated_artifact_relation_snapshot_path,
    render_generated_artifact_relation_snapshot_json,
)
from .root_rendering_notes import (
    generated_long_notes,
    generated_memory_note_relative_paths,
    generated_project_long_expected_files,
    generated_sase_memory_content,
    generated_sase_memory_relative_path,
    generated_short_notes,
    render_generated_project_long_memory_contents,
    render_generated_sase_memory_body,
)
from .root_rendering_task_types import (
    generated_task_type_snapshot_path,
    generated_task_types_memory_relative_path,
    render_generated_task_type_snapshot_json,
)

MEMORY_DIRECTORY_MAP_FILENAME = "memory-directory-map.png"
MEMORY_DIRECTORY_MAP_RELATIVE_PATH = (
    CANONICAL_MEMORY_RELATIVE_ROOT / "assets" / MEMORY_DIRECTORY_MAP_FILENAME
)
MEMORY_README_TEMPLATE_FILENAME = "memory-README.template.md"
_MEMORY_TEMPLATE_PACKAGE = "sase.main.init_memory"
_MEMORY_README_TEMPLATE_VARS = frozenset(
    {
        "memory_notes",
        "total_notes",
        "total_lines",
        "total_tokens",
    }
)
_MEMORY_README_OPTIONAL_TEMPLATE_VARS = frozenset(
    {"core_notes", "reference_notes", "short_notes", "long_notes"}
)


@dataclass(frozen=True)
class _MemoryReadmeNote:
    note: MemoryNote
    stats: MemoryStats


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
            {"core": 0, "reference": 1}.get(row.note.type or "", 2),
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
            "core_notes": sum(1 for row in note_rows if row.note.type == "core"),
            "reference_notes": sum(
                1 for row in note_rows if row.note.type == "reference"
            ),
            # User template overrides may still reference the old variable names.
            "short_notes": sum(1 for row in note_rows if row.note.type == "core"),
            "long_notes": sum(1 for row in note_rows if row.note.type == "reference"),
            "total_lines": sum(row.stats.line_count for row in note_rows),
            "total_tokens": sum(row.stats.approx_token_count for row in note_rows),
        },
        optional_variables=_MEMORY_README_OPTIONAL_TEMPLATE_VARS,
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
    source_memory_root: Path | None = None,
    include_project_memory: bool = False,
    excluded_note_paths: frozenset[str] = frozenset(),
    additional_note_overlay: Mapping[Path, str] | None = None,
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
    generated_sase_path = root / generated_sase_memory_relative_path()
    generated_sase_content = generated_sase_memory_content(generated_sase_body)
    note_overlay = {
        generated_sase_path: generated_sase_content,
    }
    if include_project_memory and generated_project_long_contents is not None:
        for relative_path, content in generated_project_long_contents.items():
            note_overlay[root / relative_path] = content
    if amd_sync is not None:
        note_overlay.update(
            {update.path: update.content for update in amd_sync.frontmatter_updates}
        )
    if additional_note_overlay is not None:
        note_overlay.update(additional_note_overlay)
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
    if include_project_memory:
        relation_snapshot_content, relation_snapshot_error = (
            render_generated_artifact_relation_snapshot_json()
        )
        if relation_snapshot_error is not None or relation_snapshot_content is None:
            return (
                (),
                relation_snapshot_error
                or "failed to render sase/artifact_relations.json snapshot",
            )
        expected.append(
            MemoryExpectedFile(
                path=generated_artifact_relation_snapshot_path(root),
                content=relation_snapshot_content,
                detail="generated artifact relation registry snapshot",
            )
        )
        snapshot_content, snapshot_error = render_generated_task_type_snapshot_json()
        if snapshot_error is not None or snapshot_content is None:
            return (
                (),
                snapshot_error or "failed to render sase/task_types.json snapshot",
            )
        expected.append(
            MemoryExpectedFile(
                path=generated_task_type_snapshot_path(root),
                content=snapshot_content,
                detail="generated task-type catalog snapshot",
            )
        )
    if include_project_memory and generated_project_long_contents is not None:
        expected.extend(
            generated_project_long_expected_files(root, generated_project_long_contents)
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
                detail="memory note frontmatter",
                stale_operation="update",
            )
            for update in amd_sync.frontmatter_updates
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
