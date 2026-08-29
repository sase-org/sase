"""Memory rendering and synchronization for AMD-managed instructions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from ._agents_doc import (
    collect_long_memory_entries,
    parse_amd_agents_document,
)
from ._config import resolve_amd_h1_title
from ._headings import iter_headings
from ._shared import (
    AmdMemoryFrontmatterUpdate,
    AmdMemorySyncPlan,
    read_text,
)
from ._template import render_agents_template
from .constants import AGENTS_FILENAME
from .inline_memory import inline_memory_section, validate_short_memory_structure
from sase.memory.notes import (
    AGENTS_PARENT,
    GeneratedLongMemoryNote,
    GeneratedShortMemoryNote,
    MemoryNote,
    apply_memory_frontmatter,
    discover_memory_notes,
    normalize_memory_note_type,
    render_long_memory_sections,
)
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT

_LONG_MEMORY_INTRO = (
    "The below files contain detailed reference material. When working in "
    "their domain, you MUST use your `/sase_memory_read` skill to review "
    "their contents. Do not read canonical memory files directly."
)
_LONG_MEMORY_INTRO_FIRST_SENTENCE = _LONG_MEMORY_INTRO.split(".", 1)[0] + "."
_WEB_MEMORY_INTRO = (
    "Each memory web below is a keyed collection. Its descriptor is always "
    "loaded, but a strand's body is not: read strands on demand with your "
    "`/sase_memory_read` skill, for example `sase memory read glossary:stitch "
    '-r "<why>"`.'
)
_WEB_MEMORY_INTRO_FIRST_SENTENCE = _WEB_MEMORY_INTRO.split(".", 1)[0] + "."


def _existing_agents_long_descriptions(root: Path) -> dict[str, str]:
    agents_path = root / AGENTS_FILENAME
    if not agents_path.exists():
        return {}
    text, error = read_text(agents_path)
    if error is not None or text is None:
        return {}
    parsed = parse_amd_agents_document(text)
    if parsed.has_long_section:
        entries = parsed.long_memory_entries
    else:
        lines = text.splitlines()
        entries = collect_long_memory_entries(lines, 0, len(lines))
    return {entry.path: entry.description for entry in entries if entry.description}


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
        if note.type == "reference" and not note.is_web_descriptor
    }
    descriptions.update(
        {
            relative_path: generated.description
            for relative_path, generated in generated_long_notes.items()
        }
    )
    return descriptions


def _memory_frontmatter_updates(
    root: Path,
    descriptions: dict[str, str],
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote],
    *,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> tuple[AmdMemoryFrontmatterUpdate, ...]:
    updates: list[AmdMemoryFrontmatterUpdate] = []
    for note in _discover_memory_notes_excluding(
        root,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    ):
        if note.is_web_descriptor:
            continue
        if note.type not in {"core", "reference"}:
            continue
        if note.type_source in {"invalid", "missing"}:
            continue
        source_path = root / note.source_relative_path
        path = root / note.path
        rel = note.relative_path
        if rel in generated_long_notes:
            continue
        raw_note_type = _normalized_frontmatter_type(note)
        type_needs_migration = (
            normalize_memory_note_type(raw_note_type) != raw_note_type
        )
        if (
            note.type == "core"
            and not type_needs_migration
            and note.parent_source == "frontmatter"
        ):
            continue
        description = (
            descriptions.get(rel, note.description)
            if note.type == "reference"
            else note.description
        )
        text, error = read_text(source_path)
        if error is not None or text is None:
            continue
        content = apply_memory_frontmatter(
            text,
            note_type=note.type,
            parent=(
                note.parent if note.parent_source == "frontmatter" else AGENTS_PARENT
            ),
            description=description,
        )
        if content != text:
            updates.append(
                AmdMemoryFrontmatterUpdate(
                    path=path,
                    content=content,
                )
            )
    return tuple(updates)


def _normalized_frontmatter_type(note: MemoryNote) -> str | None:
    raw_type = note.frontmatter.get("type")
    if not isinstance(raw_type, str):
        return None
    normalized = " ".join(raw_type.split())
    return normalized or None


def _short_memory_bodies(
    root: Path,
    generated_short_notes: Mapping[str, GeneratedShortMemoryNote],
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote] | None = None,
    *,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> dict[str, GeneratedShortMemoryNote]:
    """Return core-note bodies to inline, keyed by root-relative path.

    Bodies discovered on disk are overlaid with the freshly generated bodies in
    *generated_short_notes* (for example ``sase/memory/sase.md``) so a single
    ``sase memory init`` pass inlines the just-written note content rather than a
    stale on-disk copy. Paths owned by generated reference notes are excluded from the
    discovered core-note set so type migrations converge in the same pass. The
    result is ordered by ``(priority, path)`` so the rendered ``AGENTS.md``
    section order is deterministic.
    """
    generated_long_note_paths = frozenset(generated_long_notes or {})
    bodies: dict[str, GeneratedShortMemoryNote] = {
        note.relative_path: GeneratedShortMemoryNote(
            body=note.body,
            priority=note.priority,
        )
        for note in discover_memory_notes(root, source_memory_root=source_memory_root)
        if note.type == "core"
        and not note.is_web_descriptor
        and note.relative_path not in excluded_note_paths
        and note.relative_path not in generated_long_note_paths
    }
    bodies.update(generated_short_notes)
    return dict(
        sorted(
            bodies.items(),
            key=lambda item: (item[1].priority, item[0]),
        )
    )


def _web_memory_bodies(
    root: Path,
    generated_web_notes: Mapping[str, GeneratedShortMemoryNote],
    *,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> dict[str, GeneratedShortMemoryNote]:
    """Return web-descriptor bodies to inline, keyed by root-relative path.

    Disk-discovered descriptors are overlaid with *generated_web_notes* so a
    single ``sase memory init`` pass inlines the just-rendered, roster-stripped
    body. The result is ordered by ``(priority, slug)``.
    """
    bodies: dict[str, GeneratedShortMemoryNote] = {
        note.relative_path: GeneratedShortMemoryNote(
            body=note.body,
            priority=note.priority,
        )
        for note in discover_memory_notes(root, source_memory_root=source_memory_root)
        if note.is_web_descriptor and note.relative_path not in excluded_note_paths
    }
    bodies.update(generated_web_notes)
    return dict(
        sorted(
            bodies.items(),
            key=lambda item: (item[1].priority, Path(item[0]).stem),
        )
    )


def _render_web_sections(
    web_memory_bodies: Mapping[str, GeneratedShortMemoryNote],
) -> str:
    """Return the Memory Webs section, or ``""`` when the root has no webs."""
    if not web_memory_bodies:
        return ""
    bodies = "\n\n".join(
        inline_memory_section(relative_path, note.body).rstrip("\n")
        for relative_path, note in web_memory_bodies.items()
    )
    return f"## Memory Webs\n\n{_WEB_MEMORY_INTRO}\n\n{bodies}"


def _short_memory_structure_blockers(
    short_memory_bodies: Mapping[str, GeneratedShortMemoryNote],
) -> tuple[str, ...]:
    """Return blockers for core notes that cannot be inlined safely."""
    blockers: list[str] = []
    for relative_path, note in short_memory_bodies.items():
        error = validate_short_memory_structure(note.body)
        if error is not None:
            blockers.append(f"{relative_path}: {error}")
    return tuple(blockers)


def _memory_priority_blockers(notes: tuple[MemoryNote, ...]) -> tuple[str, ...]:
    """Return blockers for invalid or misplaced memory priority frontmatter."""
    blockers: list[str] = []
    for note in sorted(notes, key=lambda item: item.relative_path):
        if note.is_web_descriptor:
            continue
        if note.priority_source == "invalid":
            blockers.append(
                f"{note.relative_path}: memory note priority must be a "
                "non-negative integer"
            )
        elif note.type == "reference" and note.priority_source == "frontmatter":
            blockers.append(
                f"{note.relative_path}: priority is only meaningful on core "
                "memory notes"
            )
    return tuple(blockers)


def _long_memory_description_blockers(
    descriptions: Mapping[str, str],
) -> tuple[str, ...]:
    """Return blockers for reference notes whose descriptions would break rendering."""
    blockers: list[str] = []
    for relative_path, description in sorted(descriptions.items()):
        if iter_headings(description):
            blockers.append(
                f"{relative_path}: reference memory note description must not contain "
                "Markdown headings"
            )
    return tuple(blockers)


def _render_managed_agents(
    root: Path,
    title: str,
    *,
    long_memory_descriptions: dict[str, str] | None = None,
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote] | None = None,
    short_memory_bodies: Mapping[str, GeneratedShortMemoryNote] | None = None,
    web_memory_bodies: Mapping[str, GeneratedShortMemoryNote] | None = None,
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
            type="reference",
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
                if note.type == "reference"
                and not note.is_web_descriptor
                and note.parent == AGENTS_PARENT
            ),
            key=lambda note: note.relative_path,
        )
    )
    descriptions = long_memory_descriptions or {}

    bodies = short_memory_bodies or {}
    web_bodies = web_memory_bodies or {}
    core_sections = "\n\n".join(
        inline_memory_section(relative_path, note.body).rstrip("\n")
        for relative_path, note in bodies.items()
    )
    web_sections = _render_web_sections(web_bodies)

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
    long_entries = render_long_memory_sections(rendered_long_notes)
    reference_entries = (
        "" if not long_entries else f"{_LONG_MEMORY_INTRO}\n\n{long_entries}"
    )

    rendered, render_error = render_agents_template(
        root,
        title=title,
        core_sections=core_sections,
        web_sections=web_sections,
        reference_entries=reference_entries,
    )
    if render_error is not None or rendered is None:
        return None, render_error or "failed to render AGENTS template"

    parsed = parse_amd_agents_document(rendered)
    if not parsed.has_short_section:
        return (
            None,
            "rendered AGENTS template is missing structural anchor `## Core Memory`",
        )
    if not parsed.has_long_section:
        return (
            None,
            "rendered AGENTS template is missing structural anchor "
            "`## Reference Memory`",
        )
    expected_short_paths = tuple(bodies)
    if parsed.short_memory_paths != expected_short_paths:
        return (
            None,
            "rendered AGENTS template has unexpected Core Memory paths: "
            f"expected {expected_short_paths!r}, found {parsed.short_memory_paths!r}",
        )
    expected_web_paths = tuple(web_bodies)
    if expected_web_paths:
        if not parsed.has_web_section:
            return (
                None,
                "rendered AGENTS template is missing structural anchor "
                "`## Memory Webs`",
            )
        if parsed.web_memory_paths != expected_web_paths:
            return (
                None,
                "rendered AGENTS template has unexpected Memory Webs paths: "
                f"expected {expected_web_paths!r}, found {parsed.web_memory_paths!r}",
            )
        if _WEB_MEMORY_INTRO_FIRST_SENTENCE not in rendered:
            return (
                None,
                "rendered AGENTS template is missing the Memory Webs "
                "instruction paragraph",
            )
    elif parsed.has_web_section:
        return (
            None,
            "rendered AGENTS template has unexpected Memory Webs section",
        )
    expected_long_paths = tuple(note.relative_path for note in top_level_long_notes)
    parsed_long_paths = tuple(entry.path for entry in parsed.long_memory_entries)
    if parsed_long_paths != expected_long_paths:
        return (
            None,
            "rendered AGENTS template has unexpected Reference Memory paths: "
            f"expected {expected_long_paths!r}, found {parsed_long_paths!r}",
        )
    if top_level_long_notes and _LONG_MEMORY_INTRO_FIRST_SENTENCE not in rendered:
        return (
            None,
            "rendered AGENTS template is missing the Reference Memory "
            "instruction paragraph",
        )
    return rendered, None


def plan_minimal_agents_sync(
    root: Path,
    *,
    generated_short_notes: Mapping[str, GeneratedShortMemoryNote],
) -> AmdMemorySyncPlan:
    """Plan the create-if-missing fallback agent document from its template."""
    relative_path = (CANONICAL_MEMORY_RELATIVE_ROOT / "sase.md").as_posix()
    generated_note = generated_short_notes.get(relative_path)
    body = "" if generated_note is None else generated_note.body
    core_sections = inline_memory_section(relative_path, body).rstrip("\n")
    rendered, render_error = render_agents_template(
        root,
        title="Agent Instructions",
        core_sections=core_sections,
        minimal=True,
    )
    if render_error is not None or rendered is None:
        return AmdMemorySyncPlan(
            title=None,
            agents_content=None,
            frontmatter_updates=(),
            blockers=(render_error or "failed to render minimal AGENTS template",),
        )
    return AmdMemorySyncPlan(
        title=None,
        agents_content=None,
        frontmatter_updates=(),
        fallback_agents_content=rendered,
    )


def plan_amd_memory_sync(
    root: Path | None = None,
    *,
    derive_project_title: bool = False,
    generated_short_notes: Mapping[str, GeneratedShortMemoryNote] | None = None,
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote] | None = None,
    generated_web_notes: Mapping[str, GeneratedShortMemoryNote] | None = None,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> AmdMemorySyncPlan:
    """Plan AMD-managed memory block synchronization for ``sase memory init``.

    *generated_short_notes* maps a root-relative core-note path to its freshly
    generated body and priority so the rendered ``AGENTS.md`` inlines current
    content (e.g. ``sase/memory/sase.md``) in a single pass instead of a stale
    on-disk copy.
    *generated_web_notes* maps web-descriptor paths to their freshly rendered,
    roster-stripped bodies so they land in the Memory Webs section in that same
    pass.
    *generated_long_notes* maps generated reference-note paths to their metadata so a
    fresh root lists top-level notes and omits child notes in Reference Memory in
    that same pass.
    """
    root = root or Path.cwd()
    generated_short_notes = generated_short_notes or {}
    generated_long_notes = generated_long_notes or {}
    generated_web_notes = generated_web_notes or {}
    # Generated core and web notes overlay disk in the same pass, including type
    # migrations from a leftover reference note at the same path.
    excluded_note_paths = (
        excluded_note_paths
        | frozenset(generated_short_notes)
        | frozenset(generated_web_notes)
    )
    title, title_error = resolve_amd_h1_title(
        root, derive_project_title=derive_project_title
    )
    if title_error is not None:
        return AmdMemorySyncPlan(
            title=None,
            agents_content=None,
            frontmatter_updates=(),
            blockers=(title_error,),
        )
    if title is None:
        return plan_minimal_agents_sync(
            root,
            generated_short_notes=generated_short_notes,
        )

    memory_notes = _discover_memory_notes_excluding(
        root,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    priority_blockers = _memory_priority_blockers(memory_notes)
    if priority_blockers:
        return AmdMemorySyncPlan(
            title=title,
            agents_content=None,
            frontmatter_updates=(),
            blockers=priority_blockers,
        )

    short_memory_bodies = _short_memory_bodies(
        root,
        generated_short_notes,
        generated_long_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    web_memory_bodies = _web_memory_bodies(
        root,
        generated_web_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    structure_blockers = (
        *_short_memory_structure_blockers(short_memory_bodies),
        *_short_memory_structure_blockers(web_memory_bodies),
    )
    if structure_blockers:
        return AmdMemorySyncPlan(
            title=title,
            agents_content=None,
            frontmatter_updates=(),
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
            frontmatter_updates=(),
            blockers=description_blockers,
        )
    updates = _memory_frontmatter_updates(
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
        web_memory_bodies=web_memory_bodies,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    if template_error is not None or agents_content is None:
        return AmdMemorySyncPlan(
            title=title,
            agents_content=None,
            frontmatter_updates=(),
            blockers=(template_error or "failed to render AGENTS template",),
        )
    return AmdMemorySyncPlan(
        title=title,
        agents_content=agents_content,
        frontmatter_updates=updates,
    )
