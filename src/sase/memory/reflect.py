"""Post-run reflection logic for distilling learnings into memory."""

from __future__ import annotations

from pathlib import Path

from sase.memory.repo import repo_exists
from sase.memory.store import list_memories


def gather_reflection_context(
    project: str | None = None,
    chat_log: str | None = None,
) -> str:
    """Gather context needed for post-run reflection.

    Returns a markdown-formatted string containing:
    - Current memory inventory (so the agent can avoid duplicates)
    - The recent chat log to extract learnings from (if provided)
    """
    sections: list[str] = []
    sections.append("# Reflection Context\n")

    if project:
        sections.append(f"Project: `{project}`\n")

    # --- Existing memories ---
    if repo_exists():
        memories = list_memories(project=project)
        if memories:
            sections.append("## Existing Memories\n")
            sections.append(
                "The following memories already exist. Do NOT create duplicates."
                " Update existing memories if new information refines them.\n"
            )
            for rel_path, mem in memories:
                sections.append(f"### {rel_path}")
                sections.append(f"- **Type:** {mem.memory_type.value}")
                sections.append(f"- **Description:** {mem.description}")
                sections.append(f"- **Body:** {mem.body}")
                sections.append("")
        else:
            sections.append("## Existing Memories\n")
            sections.append("No memories exist yet for this scope.\n")
    else:
        sections.append("## Existing Memories\n")
        sections.append("Memory repo not initialized — no existing memories.\n")

    # --- Chat log ---
    if chat_log:
        sections.append("## Recent Chat Session\n")
        sections.append(
            "Extract actionable learnings from the following chat session:\n"
        )
        # Truncate very long chat logs to keep context manageable
        max_chars = 50_000
        if len(chat_log) > max_chars:
            sections.append(chat_log[:max_chars])
            sections.append("\n... (truncated)")
        else:
            sections.append(chat_log)
        sections.append("")

    return "\n".join(sections)


def find_recent_chat_log(project: str | None = None) -> str | None:
    """Find the most recent chat log file for the given project.

    Searches ``~/.sase/chats/`` for the most recently modified chat log.
    Returns its contents, or ``None`` if no chat logs are found.
    """
    chats_dir = Path.home() / ".sase" / "chats"
    if not chats_dir.is_dir():
        return None

    # Look for chat files, preferring project-scoped ones
    candidates: list[Path] = []
    if project:
        proj_dir = chats_dir / project
        if proj_dir.is_dir():
            candidates.extend(proj_dir.glob("*.md"))
            candidates.extend(proj_dir.glob("*.txt"))
            candidates.extend(proj_dir.glob("*.json"))
    # Also check top-level chats
    candidates.extend(chats_dir.glob("*.md"))
    candidates.extend(chats_dir.glob("*.txt"))
    candidates.extend(chats_dir.glob("*.json"))

    if not candidates:
        return None

    # Pick the most recently modified
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        return latest.read_text(errors="replace")
    except OSError:
        return None
