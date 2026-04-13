"""Dynamic memory generation for agent sessions.

Scans the user's expanded prompt against keyword-tagged memory xprompts
and writes ``memory/dynamic.md`` containing ``@`` references to matched
tier 3 files.  The agent runtime resolves those references as part of
its CLAUDE.md -> AGENTS.md -> ``@memory/dynamic.md`` inclusion chain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class MatchedMemory:
    """A memory xprompt that matched the user's prompt."""

    name: str
    keywords_matched: list[str]
    content: str


def generate_dynamic_memory(
    prompt: str, workspace_dir: str, project: str | None
) -> list[MatchedMemory]:
    """Match memory-tagged xprompts against the prompt and write dynamic.md.

    Loads all xprompts, filters to those with the ``memory`` tag and
    non-empty ``keywords``, then checks each keyword against the prompt
    (case-insensitive substring).  Matched content (typically ``@`` references
    to ``memory/long/`` files) is written to ``{workspace_dir}/memory/dynamic.md``.

    Returns:
        List of matched memories for artifact/TUI reporting.
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

    dynamic_path = os.path.join(workspace_dir, "memory", "dynamic.md")

    if matched:
        os.makedirs(os.path.dirname(dynamic_path), exist_ok=True)
        with open(dynamic_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(m.content for m in matched) + "\n")
    elif os.path.exists(dynamic_path):
        os.unlink(dynamic_path)

    return matched
