"""Memory rendering and synchronization for AMD-managed instructions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

from ._agents_doc import parse_amd_agents_document
from ._config import load_amd_h1_title
from ._shared import (
    AmdLongMemoryDescriptionUpdate,
    AmdMemorySyncPlan,
    read_text,
)
from .constants import AGENTS_FILENAME
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


def _short_memory_references(root: Path) -> tuple[str, ...]:
    generated_path = Path("memory/sase.md")
    refs = {generated_path}
    refs.update(
        note.path for note in discover_memory_notes(root) if note.type == "short"
    )
    return tuple(f"@{path.as_posix()}" for path in sorted(refs))


def render_managed_agents(
    root: Path,
    title: str,
    *,
    long_memory_descriptions: dict[str, str] | None = None,
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
        "The following memory files contain core (always loaded) context:",
        "",
    ]
    lines.extend(f"- {ref}" for ref in _short_memory_references(root))
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


def plan_amd_memory_sync(root: Path | None = None) -> AmdMemorySyncPlan:
    """Plan AMD-managed memory block synchronization for ``sase memory init``."""
    root = root or Path.cwd()
    title, title_error = load_amd_h1_title(root)
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

    descriptions = _long_memory_descriptions(root)
    updates = _long_memory_description_updates(root, descriptions)
    agents_content = render_managed_agents(
        root,
        title,
        long_memory_descriptions=descriptions,
    )
    return AmdMemorySyncPlan(
        title=title,
        agents_content=agents_content,
        description_updates=updates,
    )
