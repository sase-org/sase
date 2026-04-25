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


def _mask_command_substitutions(prompt: str) -> str:
    """Return ``prompt`` with every ``$(...)`` payload blanked to spaces.

    Mirrors :func:`_mask_negative_spans` (replace-with-spaces) so offsets and
    surrounding word boundaries are preserved for downstream keyword matching.
    Escaped ``\\$(`` is left intact — its payload is not masked.

    Necessary because :func:`generate_dynamic_memory` runs after
    :func:`process_xprompt_references`, which eagerly resolves ``$(...)``
    inside xprompt argument positions and inlines the resulting text into the
    prompt. That inlined text (e.g. file paths from ``$(branch_changes ...)``)
    would otherwise pollute keyword matching with environment-derived data.
    """
    from sase.gemini_wrapper.file_references import find_command_substitutions

    subs = find_command_substitutions(prompt)
    if not subs:
        return prompt
    masked = list(prompt)
    for start, end, _ in subs:
        for i in range(start, end):
            masked[i] = " "
    return "".join(masked)


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
    """Format the ``### DYNAMIC MEMORY`` markdown section with keyword annotations.

    Each line embeds the source xprompt name so the late-phase rewriter
    (:func:`rewrite_dynamic_memory_for_prompt`) can resolve memories back to
    their xprompts without inverting the lossy ``_memory_filename`` transform.
    """
    lines = ["### DYNAMIC MEMORY"]
    for path, mem in zip(result.paths, result.matched, strict=True):
        kw_list = ", ".join(f"`{kw}`" for kw in mem.keywords_matched)
        lines.append(f"- @{path} ({mem.name}, matched: {kw_list})")
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
    from the prompt so that stale references don't influence keyword hits, and
    every ``$(...)`` command-substitution payload is masked to spaces so that
    environment-derived text inlined by upstream xprompt processing does not
    pollute keyword matches. After matching, stale ``long-*.md`` cache files
    whose source xprompts no longer exist are deleted.

    Returns:
        A result containing the list of matched memories and the file paths
        (empty if no matches).
    """
    from sase.xprompt.loader import get_all_prompts
    from sase.xprompt.tags import XPromptTag

    prompt = _strip_dynamic_memory_section(prompt)
    prompt = _mask_command_substitutions(prompt)

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

    paths = _write_memory_files(matched)
    return DynamicMemoryResult(matched=matched, paths=paths)


def _write_memory_files(matched: list[MatchedMemory]) -> list[str]:
    """Resolve ``$(cat ...)`` substitution and write each matched memory to ``.sase/memory/``.

    Idempotent — overwrites existing files.  Uses the *current* CWD, so callers
    that want files written into a freshly-cleaned workspace must call this
    after any chdir/clean has already happened.
    """
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
    return paths


_DYNAMIC_MEMORY_LINE_RE = re.compile(
    r"^- @(?P<path>\S+) \((?P<name>[^,()]+), matched: (?P<kws>.+)\)\s*$"
)


def _parse_dynamic_memory_section(prompt: str) -> list[tuple[str, str]]:
    """Extract ``(xprompt_name, file_path)`` pairs from a prompt's DYNAMIC MEMORY section.

    Returns an empty list when the section is absent or contains no parseable
    lines.  Tolerates extra blank lines but stops at the first non-blank,
    non-matching line.
    """
    marker = "### DYNAMIC MEMORY"
    idx = prompt.find(marker)
    if idx == -1:
        return []
    body = prompt[idx + len(marker) :]
    pairs: list[tuple[str, str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _DYNAMIC_MEMORY_LINE_RE.match(line)
        if not m:
            break
        pairs.append((m.group("name"), m.group("path")))
    return pairs


def rewrite_dynamic_memory_for_prompt(prompt: str) -> None:
    """Re-write ``.sase/memory/`` files for memories listed in the prompt's section.

    Parses the ``### DYNAMIC MEMORY`` section out of ``prompt``, looks each
    listed xprompt up via the loader, and writes the resolved content using
    :func:`_write_memory_files` in the *current* CWD.  Used by
    :func:`sase.llm_provider.preprocessing.preprocess_prompt_late` so the
    files exist on disk after any embedded-workflow pre-step that may have
    cleaned the workspace.

    No-op when the prompt has no DYNAMIC MEMORY section.
    """
    pairs = _parse_dynamic_memory_section(prompt)
    if not pairs:
        return

    from sase.xprompt.loader import get_all_prompts
    from sase.xprompt.tags import XPromptTag

    all_prompts = get_all_prompts(project=None)
    matched: list[MatchedMemory] = []
    for name, _ in pairs:
        wf = all_prompts.get(name)
        if wf is None or XPromptTag.memory not in wf.tags:
            continue
        matched.append(
            MatchedMemory(
                name=name,
                keywords_matched=[],
                content=wf.get_prompt_part_content(),
            )
        )

    if matched:
        _write_memory_files(matched)
