"""XPrompt loader for flat SASE memory notes."""

from __future__ import annotations

from pathlib import Path

from sase.content_layout import (
    LayoutCollisionError,
    MemoryFileSource,
    memory_note_issue,
    memory_reference_name,
    resolve_memory_file_sources,
)
from sase.memory.notes import MemoryNote, discover_memory_notes

from .load_issues import record_load_issue
from .models import MemoryType, XPrompt

MEMORY_LOAD_ISSUE_KIND = "memory"


def load_memory_xprompts(
    project: str | None = None,
    *,
    project_root: Path | str | None = None,
    home_root: Path | str | None = None,
    include_discovered_project: bool = True,
) -> dict[str, XPrompt]:
    """Load contextual ``memory/<stem>`` xprompts from project and home memory."""
    xprompts: dict[str, XPrompt] = {}
    sources = resolve_memory_file_sources(
        project_root=project_root,
        home_root=home_root,
        project=project,
        include_discovered_project=include_discovered_project,
    )

    # Sources are first-wins in the shared contract. Load lower-priority
    # sources first, then let project memory replace same-stem home memory.
    for source in reversed(sources):
        for xprompt in _load_memory_xprompts_from_source(source):
            xprompts[xprompt.name] = xprompt
    return xprompts


def load_project_memory_xprompts(
    workspace_dir: Path,
    project: str,
) -> dict[str, XPrompt]:
    """Load memory xprompts for one registered project workspace."""
    return load_memory_xprompts(project=project, project_root=workspace_dir)


def _load_memory_xprompts_from_source(source: MemoryFileSource) -> tuple[XPrompt, ...]:
    try:
        memory_root = source.resolve_read_root(f"{source.scope} memory")
    except LayoutCollisionError as exc:
        record_load_issue(source.id, exc, kind=MEMORY_LOAD_ISSUE_KIND)
        return ()

    if memory_root is None or not memory_root.is_dir():
        return ()

    try:
        notes = discover_memory_notes(source.root, source_memory_root=memory_root)
    except OSError as exc:
        record_load_issue(memory_root, exc, kind=MEMORY_LOAD_ISSUE_KIND)
        return ()

    loaded: list[XPrompt] = []
    for note in notes:
        xprompt = _memory_note_to_xprompt(note, source)
        if xprompt is not None:
            loaded.append(xprompt)
    return tuple(loaded)


def _memory_note_to_xprompt(
    note: MemoryNote,
    source: MemoryFileSource,
) -> XPrompt | None:
    note_source = note.source_relative_path.as_posix()
    note_type = note.type or ""
    issue = memory_note_issue(note_source, stem=note.path.stem, note_type=note_type)
    if issue is not None:
        record_load_issue(issue.source, issue.message, kind=MEMORY_LOAD_ISSUE_KIND)
        return None

    memory_type = _memory_type(note.type)
    if memory_type is None:
        # Defense in depth when the shared checker is older than the parser.
        record_load_issue(
            note_source,
            "memory note must declare type: short or type: long",
            kind=MEMORY_LOAD_ISSUE_KIND,
        )
        return None

    source_path = source.root / note.source_relative_path
    return XPrompt(
        name=memory_reference_name(note.path.stem),
        content=note.body,
        inputs=[],
        source_path=str(source_path),
        description=note.description,
        memory_type=memory_type,
    )


def _memory_type(value: str | None) -> MemoryType | None:
    if value == "short":
        return "short"
    if value == "long":
        return "long"
    return None


__all__ = [
    "MEMORY_LOAD_ISSUE_KIND",
    "load_memory_xprompts",
    "load_project_memory_xprompts",
]
