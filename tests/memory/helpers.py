"""Shared builders for memory-note mutation tests."""

from __future__ import annotations

from pathlib import Path

from sase.memory.mutation import (
    MemoryMutationOutcome,
    MemoryScopeKind,
    create_memory_note,
)
from sase.memory.notes import (
    AGENTS_PARENT,
    apply_memory_frontmatter,
)


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def note_text(
    *,
    note_type: str = "long",
    parent: str = AGENTS_PARENT,
    description: str | None = "A note.",
    body: str = "# Body\n",
) -> str:
    return apply_memory_frontmatter(
        body,
        note_type=note_type,
        parent=parent,
        description=description,
    )


def seed_scope(root: Path, *, hub: bool = False) -> None:
    agents = "@sase/memory/hub.md\n" if hub else "# Agents\n"
    write_file(root / "AGENTS.md", agents)
    if hub:
        write_file(
            root / "sase" / "memory" / "hub.md",
            note_text(description="Hub note.", body="# Hub\n"),
        )


def create_note(
    root: Path,
    stem: str,
    *,
    note_type: str = "long",
    parent: str = AGENTS_PARENT,
    description: str | None = "A note.",
    body: str = "",
    scope_key: str = "demo",
    scope_kind: MemoryScopeKind = "project",
) -> MemoryMutationOutcome:
    return create_memory_note(
        scope_key=scope_key,
        content_root=root,
        stem=stem,
        note_type=note_type,
        parent=parent,
        description=description,
        body=body,
        scope_kind=scope_kind,
    )
