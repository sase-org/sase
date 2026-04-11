"""Memory defragmentation logic for periodic reorganization."""

from __future__ import annotations

from sase.memory.repo import repo_exists
from sase.memory.store import list_memories


def gather_defrag_context(project: str | None = None) -> str:
    """Gather context needed for memory defragmentation.

    Returns a markdown-formatted string containing the full content of
    every memory file, so the defrag agent can analyze the collection for:
    - Overlapping or near-duplicate entries
    - Oversized files that should be split
    - Stale or outdated entries
    - Poorly organized directory structure
    """
    sections: list[str] = []
    sections.append("# Defragmentation Context\n")

    if project:
        sections.append(f"Project: `{project}`\n")

    if not repo_exists():
        sections.append("Memory repo not initialized — nothing to defragment.\n")
        return "\n".join(sections)

    memories = list_memories(project=project)
    if not memories:
        scope = f"project '{project}'" if project else "all scopes"
        sections.append(f"No memories found for {scope} — nothing to defragment.\n")
        return "\n".join(sections)

    sections.append(f"**Total memories:** {len(memories)}\n")

    # Group by type for easier analysis
    by_type: dict[str, list[tuple[str, str, str, str]]] = {}
    for rel_path, mem in memories:
        key = mem.memory_type.value
        if key not in by_type:
            by_type[key] = []
        by_type[key].append((rel_path, mem.name, mem.description, mem.body))

    sections.append("## Memory Inventory by Type\n")
    for mem_type, entries in sorted(by_type.items()):
        sections.append(f"### {mem_type} ({len(entries)} files)\n")
        for rel_path, name, description, body in entries:
            sections.append(f"#### `{rel_path}`")
            sections.append(f"- **Name:** {name}")
            sections.append(f"- **Description:** {description}")
            line_count = body.count("\n") + 1
            sections.append(f"- **Size:** {len(body)} chars, {line_count} lines")
            sections.append(f"- **Body:**\n{body}")
            sections.append("")

    # Summary statistics
    sections.append("## Statistics\n")
    total_chars = sum(len(mem.body) for _, mem in memories)
    sections.append(f"- Total files: {len(memories)}")
    sections.append(f"- Total content size: {total_chars} chars")
    sections.append(f"- Types: {', '.join(sorted(by_type.keys()))}")
    large_files = [rel for rel, mem in memories if mem.body.count("\n") + 1 > 50]
    if large_files:
        sections.append(f"- Large files (>50 lines): {', '.join(large_files)}")
    sections.append("")

    return "\n".join(sections)
