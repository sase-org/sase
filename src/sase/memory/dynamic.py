"""Dynamic memory generation for agent sessions.

Scans the user's expanded prompt against keyword-tagged memory xprompts,
resolves ``$(cat ...)`` shell substitution in matched content, and writes
each matched memory to its own file under ``.sase/memory/``.  The file
paths are injected into the agent prompt as a ``### DYNAMIC MEMORY``
markdown section.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.xprompt.workflow_models import Workflow


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


def _split_keywords(keywords: list[str]) -> tuple[list[str], list[str]]:
    """Split raw keyword strings into (positives, negatives) by the ``!`` sigil.

    A keyword is negative iff it starts with ``!``; the remainder (after
    stripping the ``!``) is the text used for regex matching. Empty
    post-strip keywords are dropped so a bare ``!`` does not degenerate into
    an always-matching empty regex.
    """
    positives: list[str] = []
    negatives: list[str] = []
    for kw in keywords:
        if kw.startswith("!"):
            stripped = kw[1:]
            if stripped:
                negatives.append(stripped)
        elif kw:
            positives.append(kw)
    return positives, negatives


def _keyword_pattern(keyword: str) -> str:
    """Build the case-insensitive regex for a keyword.

    Anchors ``\\b`` only at edges whose keyword char is a word character — a
    ``\\b`` next to a non-word char (e.g. ``/`` in ``/foo/``) requires the
    *other* side to be a word char, which would prevent keywords like
    ``/foo/`` from matching inside ``/path/to/foo/``. For word-char-bounded
    keywords this is identical to ``\\b{kw}\\b``.
    """
    pattern = re.escape(keyword)
    if keyword and (keyword[0].isalnum() or keyword[0] == "_"):
        pattern = r"\b" + pattern
    if keyword and (keyword[-1].isalnum() or keyword[-1] == "_"):
        pattern = pattern + r"\b"
    return pattern


def _keyword_matches(keyword: str, prompt: str) -> bool:
    """Whole-word, case-insensitive match of ``keyword`` in ``prompt``."""
    return bool(re.search(_keyword_pattern(keyword), prompt, re.IGNORECASE))


def _mask_negative_spans(prompt: str, negatives: list[str]) -> str:
    """Return ``prompt`` with every span matched by any negative keyword blanked to spaces.

    Replacing with spaces (rather than removing) preserves offsets and surrounding
    word boundaries so a positive keyword adjacent to a masked span still sees
    the same ``\\b`` transitions it would see in the unmasked prompt.
    """
    if not negatives:
        return prompt
    masked = list(prompt)
    for neg in negatives:
        for m in re.finditer(_keyword_pattern(neg), prompt, re.IGNORECASE):
            for i in range(m.start(), m.end()):
                masked[i] = " "
    return "".join(masked)


def _memory_filename(xprompt_name: str) -> str:
    """Derive a ``.sase/memory/`` filename from an xprompt name.

    Example: ``memory/long/external_repos`` -> ``long-external-repos.md``

    The ``long-`` prefix tells agents the file originates from a long-term
    (tier 3) memory source.  Hyphens avoid Prettier underscore mangling.
    """
    # Strip the "memory/" prefix, then convert separators
    stem = xprompt_name.removeprefix("memory/")
    return stem.replace("/", "-").replace("_", "-") + ".md"


def format_dynamic_memory_section(result: DynamicMemoryResult) -> str:
    """Format the ``### DYNAMIC MEMORY`` markdown section with keyword annotations."""
    lines = ["### DYNAMIC MEMORY"]
    for path, mem in zip(result.paths, result.matched, strict=True):
        kw_list = ", ".join(f"`{kw}`" for kw in mem.keywords_matched)
        lines.append(f"- @{path} (matched: {kw_list})")
    return "\n".join(lines)


def _strip_dynamic_memory_section(prompt: str) -> str:
    """Remove any existing ``### DYNAMIC MEMORY`` section from a prompt.

    Strips the ``### DYNAMIC MEMORY`` heading and everything after it so that
    keyword matching runs against the clean prompt without stale references.
    """
    marker = "### DYNAMIC MEMORY"
    idx = prompt.find(marker)
    if idx == -1:
        return prompt
    return prompt[:idx].rstrip()


def _cleanup_stale_memory_files(
    all_prompts: Mapping[str, Workflow], memory_dir: Path
) -> None:
    """Delete ``.sase/memory/long-*.md`` files that no longer have a source xprompt."""
    from sase.xprompt.tags import XPromptTag

    valid_filenames: set[str] = set()
    for wf in all_prompts.values():
        if XPromptTag.memory not in wf.tags:
            continue
        if wf.name.startswith("memory/long/"):
            valid_filenames.add(_memory_filename(wf.name))

    if not memory_dir.is_dir():
        return

    for path in memory_dir.glob("long-*.md"):
        if path.name not in valid_filenames:
            path.unlink()


def generate_dynamic_memory(prompt: str, project: str | None) -> DynamicMemoryResult:
    """Match memory-tagged xprompts against the prompt and write individual files.

    Loads all xprompts, filters to those with the ``memory`` tag and
    non-empty ``keywords``, then checks each keyword against the prompt
    (word-boundary regex, case-insensitive). Negative (``!``-prefixed) keywords
    mask their matched spans out of the prompt before positive matching runs,
    so a memory is excluded only when every positive hit fell inside a masked
    region. Matched content uses ``$(cat ...)`` shell substitution which is
    resolved before writing each match to its own file under ``.sase/memory/``
    in the current working directory.

    Before matching, any existing ``### DYNAMIC MEMORY`` section is stripped
    from the prompt so that stale references don't influence keyword hits.
    After matching, stale ``long-*.md`` cache files whose source xprompts no
    longer exist are deleted.

    Returns:
        A result containing the list of matched memories and the file paths
        (empty if no matches).
    """
    from sase.xprompt.loader import get_all_prompts
    from sase.xprompt.tags import XPromptTag

    prompt = _strip_dynamic_memory_section(prompt)

    all_prompts = get_all_prompts(project=project)

    memory_dir = Path(".sase/memory")
    _cleanup_stale_memory_files(all_prompts, memory_dir)

    matched: list[MatchedMemory] = []

    for wf in all_prompts.values():
        if XPromptTag.memory not in wf.tags:
            continue
        if not wf.keywords:
            continue

        positives, negatives = _split_keywords(wf.keywords)
        search_prompt = _mask_negative_spans(prompt, negatives)
        hits = [kw for kw in positives if _keyword_matches(kw, search_prompt)]
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

    memory_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    for m in matched:
        resolved = process_command_substitution(m.content)
        filename = _memory_filename(m.name)
        file_path = memory_dir / filename
        file_path.write_text(resolved, encoding="utf-8")
        paths.append(str(file_path))

    return DynamicMemoryResult(matched=matched, paths=paths)
