"""Dynamic memory generation for agent sessions.

Scans the user's expanded prompt against keyword-tagged memory xprompts,
resolves ``$(cat ...)`` shell substitution in matched content, and writes
the resolved content to a temp file.  The temp file path is injected into
the agent prompt as ``DYNAMIC MEMORY: @<path>``.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass

from sase.core.paths import get_sase_tmpdir


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
    path: str | None  # Path to temp file with matched content


def generate_dynamic_memory(prompt: str, project: str | None) -> DynamicMemoryResult:
    """Match memory-tagged xprompts against the prompt and write a temp file.

    Loads all xprompts, filters to those with the ``memory`` tag and
    non-empty ``keywords``, then checks each keyword against the prompt
    (case-insensitive substring).  Matched content uses ``$(cat ...)`` shell
    substitution which is resolved before writing to a temp file under
    ``$SASE_TMPDIR`` (or system temp), so the file contains actual content.

    Returns:
        A result containing the list of matched memories and the temp file
        path (None if no matches).
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
        return DynamicMemoryResult(matched=[], path=None)

    from sase.gemini_wrapper.file_references import process_command_substitution

    sections = []
    for m in matched:
        sections.append(f"---\n## {m.name}\n\n{m.content}")
    raw_content = "\n\n".join(sections) + "\n"
    resolved_content = process_command_substitution(raw_content)

    tmpdir = get_sase_tmpdir()
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".md",
        prefix="sase_dynamic_memory_",
        dir=tmpdir,
        mode="w",
        encoding="utf-8",
    ) as f:
        f.write(resolved_content)
        tmp_path = f.name

    return DynamicMemoryResult(matched=matched, path=tmp_path)
