"""Memory rendering and synchronization for AMD-managed instructions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import re

from ._agents_doc import parse_amd_agents_document
from ._config import resolve_amd_h1_title
from ._shared import (
    AmdLongMemoryDescriptionUpdate,
    AmdMemorySyncPlan,
    read_text,
)
from .constants import AGENTS_FILENAME
from .inline_memory import inline_memory_section, validate_short_memory_structure
from sase.memory.notes import (
    AGENTS_PARENT,
    apply_memory_frontmatter,
    discover_memory_notes,
    render_memory_note_references,
)

_AGENTS_LONG_MEMORY_RE = re.compile(
    r"^\*\*`(?P<path>memory/[^`]+\.md)`\*\*[ \t]*\n(?P<body>.*?)(?=\n\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


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
    for match in _AGENTS_LONG_MEMORY_RE.finditer(text):
        body = " ".join(line.strip() for line in match.group("body").splitlines())
        body = " ".join(body.split())
        body = re.sub(r"\s+_Read when\b.*?_$", "", body).strip()
        if body:
            descriptions[match.group("path")] = body
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


def _long_memory_descriptions(root: Path) -> dict[str, str]:
    existing_agents_descriptions = _existing_agents_long_descriptions(root)
    notes = discover_memory_notes(root)
    return {
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


def _long_memory_description_updates(
    root: Path, descriptions: dict[str, str]
) -> tuple[AmdLongMemoryDescriptionUpdate, ...]:
    updates: list[AmdLongMemoryDescriptionUpdate] = []
    for note in discover_memory_notes(root):
        if note.type != "long":
            continue
        path = root / note.path
        rel = note.relative_path
        description = descriptions[rel]
        text, error = read_text(path)
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
) -> dict[str, str]:
    """Return short-note bodies to inline, keyed by root-relative path.

    Bodies discovered on disk are overlaid with the freshly generated bodies in
    *generated_short_notes* (for example ``memory/sase.md``) so a single
    ``sase memory init`` pass inlines the just-written note content rather than a
    stale on-disk copy. The result is sorted by path so the rendered ``AGENTS.md``
    section order is deterministic.
    """
    bodies: dict[str, str] = {
        note.relative_path: note.body
        for note in discover_memory_notes(root)
        if note.type == "short"
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


def _render_managed_agents(
    root: Path,
    title: str,
    *,
    long_memory_descriptions: dict[str, str] | None = None,
    short_memory_bodies: Mapping[str, str] | None = None,
) -> str:
    """Render the project-managed AMD ``AGENTS.md`` content for *root*."""
    existing_descriptions = _existing_agents_long_descriptions(root)
    notes = discover_memory_notes(root)
    top_level_long_notes = tuple(
        sorted(
            (
                note
                for note in notes
                if note.type == "long" and note.parent == AGENTS_PARENT
            ),
            key=lambda note: note.relative_path,
        )
    )
    descriptions = long_memory_descriptions or {}

    lines = [
        f"# {title}",
        "",
        "IMPORTANT: You should not modify any of these memory files without "
        "approval from the user.",
        "",
        "## Tier 1 (short-term) Memory",
        "",
        "The following memories contains core (always loaded) context:",
        "",
    ]
    bodies = short_memory_bodies or {}
    for index, (relative_path, body) in enumerate(bodies.items()):
        if index:
            lines.append("")
        lines.extend(
            inline_memory_section(relative_path, body, number=index + 1).splitlines()
        )
    lines.append("")
    lines.extend(
        [
            "## Tier 2 (long-term) Memory",
            "",
            "The below files contain detailed reference material. When working "
            "in their domain, you MUST use your `/sase_memory_read`",
            "skill to review their contents. Do not read canonical memory files directly.",
            "",
        ]
    )
    for index, note in enumerate(top_level_long_notes):
        if index:
            lines.append("")
        description = descriptions.get(note.relative_path) or _long_memory_description(
            root / note.path,
            body=note.body,
            relative_path=note.relative_path,
            description=note.description,
            existing_agents_descriptions=existing_descriptions,
        )
        lines.extend(
            render_memory_note_references(
                (replace(note, description=description),)
            ).splitlines()
        )
    lines.append("")
    return "\n".join(lines)


def plan_amd_memory_sync(
    root: Path | None = None,
    *,
    derive_project_title: bool = False,
    generated_short_notes: Mapping[str, str] | None = None,
) -> AmdMemorySyncPlan:
    """Plan AMD-managed memory block synchronization for ``sase memory init``.

    *generated_short_notes* maps a root-relative short-note path to its freshly
    generated body so the rendered ``AGENTS.md`` inlines current content (e.g.
    ``memory/sase.md``) in a single pass instead of a stale on-disk copy.
    """
    root = root or Path.cwd()
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
        return AmdMemorySyncPlan(
            title=None,
            agents_content=None,
            description_updates=(),
        )

    short_memory_bodies = _short_memory_bodies(root, generated_short_notes or {})
    structure_blockers = _short_memory_structure_blockers(short_memory_bodies)
    if structure_blockers:
        return AmdMemorySyncPlan(
            title=title,
            agents_content=None,
            description_updates=(),
            blockers=structure_blockers,
        )

    descriptions = _long_memory_descriptions(root)
    updates = _long_memory_description_updates(root, descriptions)
    agents_content = _render_managed_agents(
        root,
        title,
        long_memory_descriptions=descriptions,
        short_memory_bodies=short_memory_bodies,
    )
    return AmdMemorySyncPlan(
        title=title,
        agents_content=agents_content,
        description_updates=updates,
    )
