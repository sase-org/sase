"""Dynamic memory generation for agent sessions.

Scans the user's expanded prompt against keyword-tagged memory xprompts,
resolves ``$(cat ...)`` shell substitution in matched content, and writes
each matched memory to its own file under ``.sase/memory/``.  The file
paths are injected into the agent prompt as a ``### DYNAMIC MEMORY``
markdown section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MatchedMemory:
    """A memory xprompt that matched the user's prompt."""

    name: str
    keywords_matched: list[str]
    content: str


@dataclass
class DynamicMemoryResult:
    """Result of dynamic memory generation."""

    matched: list[MatchedMemory]
    paths: list[str] = field(default_factory=list)


def _memory_filename(xprompt_name: str) -> str:
    """Derive a ``.sase/memory/`` filename from an xprompt name.

    Example: ``memory/long/external_repos`` -> ``long-external-repos.md``

    The ``long-`` prefix tells agents the file originates from a long-term
    (tier 3) memory source.  Hyphens avoid Prettier underscore mangling.
    """
    # Strip the "memory/" prefix, then convert separators
    stem = xprompt_name.removeprefix("memory/")
    return stem.replace("/", "-").replace("_", "-") + ".md"


def format_dynamic_memory_section(paths: list[str]) -> str:
    """Format the ``### DYNAMIC MEMORY`` markdown section from file paths."""
    lines = ["### DYNAMIC MEMORY"]
    for p in paths:
        lines.append(f"- @{p}")
    return "\n".join(lines)


def generate_dynamic_memory(prompt: str, project: str | None) -> DynamicMemoryResult:
    """Match memory-tagged xprompts against the prompt and write individual files.

    Loads all xprompts, filters to those with the ``memory`` tag and
    non-empty ``keywords``, then checks each keyword against the prompt
    (case-insensitive substring).  Matched content uses ``$(cat ...)`` shell
    substitution which is resolved before writing each match to its own file
    under ``.sase/memory/`` in the current working directory.

    Returns:
        A result containing the list of matched memories and the file paths
        (empty if no matches).
    """
    from sase.xprompt.loader import get_all_prompts
    from sase.xprompt.tags import XPromptTag

    all_prompts = get_all_prompts(project=project)
    prompt_lower = prompt.lower()
    matched: list[MatchedMemory] = []

    for wf in all_prompts.values():
        if XPromptTag.memory not in wf.tags:
            continue
        if not wf.keywords:
            continue

        hits = [kw for kw in wf.keywords if kw.lower() in prompt_lower]
        if hits:
            matched.append(
                MatchedMemory(
                    name=wf.name,
                    keywords_matched=hits,
                    content=wf.get_prompt_part_content(),
                )
            )

    if not matched:
        return DynamicMemoryResult(matched=[])

    from sase.gemini_wrapper.file_references import process_command_substitution

    memory_dir = Path(".sase/memory")
    memory_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    for m in matched:
        resolved = process_command_substitution(m.content)
        filename = _memory_filename(m.name)
        file_path = memory_dir / filename
        file_path.write_text(resolved, encoding="utf-8")
        paths.append(str(file_path))

    return DynamicMemoryResult(matched=matched, paths=paths)
