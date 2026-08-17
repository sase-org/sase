"""Memory rendering and synchronization for AMD-managed instructions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import re

from ._agents_doc import (
    long_memory_entry_path,
    normalize_long_memory_description_lines,
    parse_amd_agents_document,
)
from ._config import resolve_amd_h1_title
from ._headings import iter_headings
from ._shared import (
    AmdLongMemoryDescriptionUpdate,
    AmdMemorySyncPlan,
    read_text,
)
from ._template import render_agents_template
from .constants import AGENTS_FILENAME
from .inline_memory import inline_memory_section, validate_short_memory_structure
from sase.memory.notes import (
    AGENTS_PARENT,
    GeneratedLongMemoryNote,
    MemoryNote,
    apply_memory_frontmatter,
    discover_memory_notes,
    render_long_memory_sections,
)
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT

_H2_LINE_RE = re.compile(r"^##\s+")


def _legacy_inline_description(line: str) -> str:
    stripped = line.strip()
    marker = "`**"
    close = stripped.find(marker)
    if not stripped.startswith("**`") or close == -1:
        return ""
    return stripped[close + len(marker) :].strip()


def _existing_agents_long_descriptions(root: Path) -> dict[str, str]:
    agents_path = root / AGENTS_FILENAME
    if not agents_path.exists():
        return {}
    text, error = read_text(agents_path)
    if error is not None or text is None:
        return {}
    parsed = parse_amd_agents_document(text)
    if parsed.has_long_section:
        return {
            entry.path: entry.description
            for entry in parsed.long_memory_entries
            if entry.description
        }

    descriptions: dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        path = long_memory_entry_path(lines[index])
        if path is None:
            index += 1
            continue
        description_lines: list[str] = []
        inline = _legacy_inline_description(lines[index])
        if inline:
            description_lines.append(inline)
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if long_memory_entry_path(candidate) is not None:
                break
            if _H2_LINE_RE.match(candidate):
                break
            description_lines.append(candidate)
            index += 1
        body = normalize_long_memory_description_lines(description_lines)
        if body:
            descriptions[path] = body
    return descriptions


def _first_body_paragraph_or_h1(body: str) -> str:
    h1 = ""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("# ") and not h1:
            h1 = line[2:].strip()
            continue
        if not line:
            if current:
                paragraphs.append(current)
                current = []
            continue
        if line.startswith("#"):
            continue
        current.append(line)
    if current:
        paragraphs.append(current)
    if paragraphs:
        return " ".join(" ".join(paragraphs[0]).split())
    return " ".join(h1.split())


def _long_memory_description(
    note_path: Path,
    *,
    body: str,
    relative_path: str,
    description: str | None,
    existing_agents_descriptions: dict[str, str],
) -> str:
    if description:
        return description
    existing = existing_agents_descriptions.get(relative_path)
    if existing:
        return existing
    fallback = _first_body_paragraph_or_h1(body)
    if fallback:
        return fallback
    return note_path.stem.replace("_", " ").replace("-", " ").strip().capitalize()


def _discover_memory_notes_excluding(
    root: Path,
    *,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> tuple[MemoryNote, ...]:
    return tuple(
        note
        for note in discover_memory_notes(root, source_memory_root=source_memory_root)
        if note.relative_path not in excluded_note_paths
    )


def _long_memory_descriptions(
    root: Path,
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote],
    *,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> dict[str, str]:
    existing_agents_descriptions = _existing_agents_long_descriptions(root)
    notes = _discover_memory_notes_excluding(
        root,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    descriptions = {
        note.relative_path: _long_memory_description(
            root / note.path,
            body=note.body,
            relative_path=note.relative_path,
            description=note.description,
            existing_agents_descriptions=existing_agents_descriptions,
        )
        for note in notes
        if note.type == "long"
    }
    descriptions.update(
        {
            relative_path: generated.description
            for relative_path, generated in generated_long_notes.items()
        }
    )
    return descriptions


def _long_memory_description_updates(
    root: Path,
    descriptions: dict[str, str],
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote],
    *,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> tuple[AmdLongMemoryDescriptionUpdate, ...]:
    updates: list[AmdLongMemoryDescriptionUpdate] = []
    for note in _discover_memory_notes_excluding(
        root,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    ):
        if note.type != "long":
            continue
        source_path = root / note.source_relative_path
        path = root / note.path
        rel = note.relative_path
        if rel in generated_long_notes:
            continue
        description = descriptions[rel]
        text, error = read_text(source_path)
        if error is not None or text is None:
            continue
        content = apply_memory_frontmatter(
            text,
            note_type="long",
            parent=(
                note.parent if note.parent_source == "frontmatter" else AGENTS_PARENT
            ),
            description=description,
        )
        if content != text:
            updates.append(
                AmdLongMemoryDescriptionUpdate(
                    path=path,
                    content=content,
                )
            )
    return tuple(updates)


def _short_memory_bodies(
    root: Path,
    generated_short_notes: Mapping[str, str],
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote] | None = None,
    *,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Return short-note bodies to inline, keyed by root-relative path.

    Bodies discovered on disk are overlaid with the freshly generated bodies in
    *generated_short_notes* (for example ``sase/memory/sase.md``) so a single
    ``sase memory init`` pass inlines the just-written note content rather than a
    stale on-disk copy. Paths owned by generated long notes are excluded from the
    discovered short-note set so type migrations converge in the same pass. The
    result is sorted by path so the rendered ``AGENTS.md`` section order is
    deterministic.
    """
    generated_long_note_paths = frozenset(generated_long_notes or {})
    bodies: dict[str, str] = {
        note.relative_path: note.body
        for note in discover_memory_notes(root, source_memory_root=source_memory_root)
        if note.type == "short"
        and note.relative_path not in excluded_note_paths
        and note.relative_path not in generated_long_note_paths
    }
    bodies.update(generated_short_notes)
    return dict(sorted(bodies.items()))


def _short_memory_structure_blockers(
    short_memory_bodies: Mapping[str, str],
) -> tuple[str, ...]:
    """Return blockers for short notes that cannot be inlined safely."""
    blockers: list[str] = []
    for relative_path, body in short_memory_bodies.items():
        error = validate_short_memory_structure(body)
        if error is not None:
            blockers.append(f"{relative_path}: {error}")
    return tuple(blockers)


def _long_memory_description_blockers(
    descriptions: Mapping[str, str],
) -> tuple[str, ...]:
    """Return blockers for long notes whose descriptions would break Tier 2."""
    blockers: list[str] = []
    for relative_path, description in sorted(descriptions.items()):
        if iter_headings(description):
            blockers.append(
                f"{relative_path}: long memory note description must not contain "
                "Markdown headings"
            )
    return tuple(blockers)


def _render_managed_agents(
    root: Path,
    title: str,
    *,
    long_memory_descriptions: dict[str, str] | None = None,
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote] | None = None,
    short_memory_bodies: Mapping[str, str] | None = None,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> tuple[str | None, str | None]:
    """Render the project-managed AMD ``AGENTS.md`` content for *root*."""
    existing_descriptions = _existing_agents_long_descriptions(root)
    notes_by_relative_path = {
        note.relative_path: note
        for note in _discover_memory_notes_excluding(
            root,
            source_memory_root=source_memory_root,
            excluded_note_paths=excluded_note_paths,
        )
    }
    for relative_path, generated in (generated_long_notes or {}).items():
        existing = notes_by_relative_path.get(relative_path)
        notes_by_relative_path[relative_path] = MemoryNote(
            path=Path(relative_path),
            type="long",
            parent=generated.parent,
            description=generated.description,
            body="" if existing is None else existing.body,
            frontmatter={},
            type_source="frontmatter",
            parent_source="frontmatter",
        )
    top_level_long_notes = tuple(
        sorted(
            (
                note
                for note in notes_by_relative_path.values()
                if note.type == "long" and note.parent == AGENTS_PARENT
            ),
            key=lambda note: note.relative_path,
        )
    )
    descriptions = long_memory_descriptions or {}

    bodies = short_memory_bodies or {}
    tier1_sections = "\n\n".join(
        inline_memory_section(relative_path, body).rstrip("\n")
        for relative_path, body in bodies.items()
    )

    rendered_long_notes = []
    for note in top_level_long_notes:
        description = descriptions.get(note.relative_path) or _long_memory_description(
            root / note.path,
            body=note.body,
            relative_path=note.relative_path,
            description=note.description,
            existing_agents_descriptions=existing_descriptions,
        )
        rendered_long_notes.append(replace(note, description=description))
    tier2_entries = render_long_memory_sections(rendered_long_notes)

    rendered, render_error = render_agents_template(
        root,
        title=title,
        tier1_sections=tier1_sections,
        tier2_entries=tier2_entries,
    )
    if render_error is not None or rendered is None:
        return None, render_error or "failed to render AGENTS template"

    parsed = parse_amd_agents_document(rendered)
    if not parsed.has_short_section:
        return (
            None,
            "rendered AGENTS template is missing structural anchor "
            "`## Tier 1 (short-term) Memory`",
        )
    if not parsed.has_long_section:
        return (
            None,
            "rendered AGENTS template is missing structural anchor "
            "`## Tier 2 (long-term) Memory`",
        )
    expected_short_paths = tuple(bodies)
    if parsed.short_memory_paths != expected_short_paths:
        return (
            None,
            "rendered AGENTS template has unexpected Tier 1 memory paths: "
            f"expected {expected_short_paths!r}, found {parsed.short_memory_paths!r}",
        )
    expected_long_paths = tuple(note.relative_path for note in top_level_long_notes)
    parsed_long_paths = tuple(entry.path for entry in parsed.long_memory_entries)
    if parsed_long_paths != expected_long_paths:
        return (
            None,
            "rendered AGENTS template has unexpected Tier 2 memory paths: "
            f"expected {expected_long_paths!r}, found {parsed_long_paths!r}",
        )
    return rendered, None


def plan_minimal_agents_sync(
    root: Path,
    *,
    generated_short_notes: Mapping[str, str],
) -> AmdMemorySyncPlan:
    """Plan the create-if-missing fallback agent document from its template."""
    relative_path = (CANONICAL_MEMORY_RELATIVE_ROOT / "sase.md").as_posix()
    body = generated_short_notes.get(relative_path, "")
    tier1_sections = inline_memory_section(relative_path, body).rstrip("\n")
    rendered, render_error = render_agents_template(
        root,
        title="Agent Instructions",
        tier1_sections=tier1_sections,
        minimal=True,
    )
    if render_error is not None or rendered is None:
        return AmdMemorySyncPlan(
            title=None,
            agents_content=None,
            description_updates=(),
            blockers=(render_error or "failed to render minimal AGENTS template",),
        )
    return AmdMemorySyncPlan(
        title=None,
        agents_content=None,
        description_updates=(),
        fallback_agents_content=rendered,
    )


def plan_amd_memory_sync(
    root: Path | None = None,
    *,
    derive_project_title: bool = False,
    generated_short_notes: Mapping[str, str] | None = None,
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote] | None = None,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> AmdMemorySyncPlan:
    """Plan AMD-managed memory block synchronization for ``sase memory init``.

    *generated_short_notes* maps a root-relative short-note path to its freshly
    generated body so the rendered ``AGENTS.md`` inlines current content (e.g.
    ``sase/memory/sase.md``) in a single pass instead of a stale on-disk copy.
    *generated_long_notes* maps generated long-note paths to their metadata so a
    fresh root lists top-level notes and omits child notes in Tier 2 in that same pass.
    """
    root = root or Path.cwd()
    generated_short_notes = generated_short_notes or {}
    generated_long_notes = generated_long_notes or {}
    title, title_error = resolve_amd_h1_title(
        root, derive_project_title=derive_project_title
    )
    if title_error is not None:
        return AmdMemorySyncPlan(
            title=None,
            agents_content=None,
            description_updates=(),
            blockers=(title_error,),
        )
    if title is None:
        return plan_minimal_agents_sync(
            root,
            generated_short_notes=generated_short_notes,
        )

    short_memory_bodies = _short_memory_bodies(
        root,
        generated_short_notes,
        generated_long_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    structure_blockers = _short_memory_structure_blockers(short_memory_bodies)
    if structure_blockers:
        return AmdMemorySyncPlan(
            title=title,
            agents_content=None,
            description_updates=(),
            blockers=structure_blockers,
        )

    descriptions = _long_memory_descriptions(
        root,
        generated_long_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    description_blockers = _long_memory_description_blockers(descriptions)
    if description_blockers:
        return AmdMemorySyncPlan(
            title=title,
            agents_content=None,
            description_updates=(),
            blockers=description_blockers,
        )
    updates = _long_memory_description_updates(
        root,
        descriptions,
        generated_long_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    agents_content, template_error = _render_managed_agents(
        root,
        title,
        long_memory_descriptions=descriptions,
        generated_long_notes=generated_long_notes,
        short_memory_bodies=short_memory_bodies,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    if template_error is not None or agents_content is None:
        return AmdMemorySyncPlan(
            title=title,
            agents_content=None,
            description_updates=(),
            blockers=(template_error or "failed to render AGENTS template",),
        )
    return AmdMemorySyncPlan(
        title=title,
        agents_content=agents_content,
        description_updates=updates,
    )
