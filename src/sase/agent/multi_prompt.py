"""Multi-prompt parsing: split a user prompt into frontmatter + segments.

A user prompt may contain YAML frontmatter (for local xprompts) and ``---``
segment separators (for launching multiple agents sequentially).

Rules:
- The first ``---`` pair at the start of the document is frontmatter.
- After frontmatter is consumed, subsequent ``---`` lines are segment separators.
- If there is no frontmatter, ALL ``---`` lines are segment separators.
- A prompt with frontmatter but only one segment is a single-agent prompt
  with local xprompts (not a multi-agent prompt).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.xprompt.loader_parsing import parse_xprompt_entries, parse_yaml_front_matter
from sase.xprompt.models import XPrompt

_SEGMENT_SEP_RE = re.compile(r"^---\s*$", re.MULTILINE)


def split_segments_protecting_fences(body: str) -> list[str]:
    """Split *body* on ``---`` separator lines, protecting fenced code blocks.

    Empty/whitespace-only segments are dropped.  Used both by
    :func:`parse_multi_prompt` (to split user-submitted prompts) and by
    :mod:`sase.agent.multi_agent_xprompt` (to split a multi-agent xprompt body
    after argument substitution).
    """
    blocks: list[str] = []
    protected = protect_fenced_blocks(body, blocks)
    raw_segments = _SEGMENT_SEP_RE.split(protected)
    segments: list[str] = []
    for seg in raw_segments:
        restored = unprotect_fenced_blocks(seg, blocks).strip()
        if restored:
            segments.append(restored)
    return segments


@dataclass
class MultiPrompt:
    """Result of parsing a user prompt into frontmatter and segments."""

    frontmatter: dict[str, object] | None = None
    local_xprompts: dict[str, XPrompt] = field(default_factory=dict)
    segments: list[str] = field(default_factory=list)


class _LocalXPromptNameError(ValueError):
    """Raised when a local xprompt name does not start with ``_``."""


def parse_multi_prompt(text: str) -> MultiPrompt:
    """Parse a user prompt into frontmatter, local xprompts, and segments.

    Steps:
        1. Extract YAML frontmatter (if present).
        2. Parse the ``xprompts`` key from frontmatter into ``XPrompt`` objects.
        3. Validate that all local xprompt names start with ``_``.
        4. Split the remaining body on ``---`` lines (protecting fenced code
           blocks so that ``---`` inside code blocks is not treated as a
           separator).
        5. Strip empty/whitespace-only segments.

    Raises:
        _LocalXPromptNameError: If any xprompt name does not start with ``_``.
    """
    frontmatter, body = parse_yaml_front_matter(text)

    # Extract local xprompts from frontmatter.
    local_xprompts: dict[str, XPrompt] = {}
    if frontmatter is not None:
        xprompt_entries = frontmatter.pop("xprompts", None)
        if isinstance(xprompt_entries, dict):
            local_xprompts = parse_xprompt_entries(
                xprompt_entries, source_path="user-prompt"
            )
            _validate_local_xprompt_names(local_xprompts)

    segments = split_segments_protecting_fences(body)

    return MultiPrompt(
        frontmatter=frontmatter,
        local_xprompts=local_xprompts,
        segments=segments,
    )


def build_wait_chained_multi_prompt(prompts: list[str]) -> str:
    """Join *prompts* into a multi-prompt where every segment after the first
    starts with a ``%wait`` directive.

    Empty/whitespace-only prompts are dropped.  Returns ``""`` when no prompts
    survive that filter, so callers can use a falsy check to skip launches.
    """
    cleaned = [p.strip() for p in prompts if p and p.strip()]
    if not cleaned:
        return ""
    segments = [cleaned[0]] + [f"%wait\n{p}" for p in cleaned[1:]]
    return "\n---\n".join(segments)


def is_multi_prompt(text: str) -> bool:
    """Quick check: does *text* contain multiple prompt segments?

    Returns ``True`` when the text would parse into more than one segment.
    This avoids a full parse when only a boolean answer is needed.
    """
    _, body = parse_yaml_front_matter(text)

    blocks: list[str] = []
    protected = protect_fenced_blocks(body, blocks)

    # More than one non-empty chunk after splitting means multi-prompt.
    parts = _SEGMENT_SEP_RE.split(protected)
    non_empty = sum(1 for p in parts if p.strip())
    return non_empty > 1


def _validate_local_xprompt_names(xprompts: dict[str, XPrompt]) -> None:
    """Raise if any local xprompt name does not start with ``_``."""
    for name in xprompts:
        if not name.startswith("_"):
            raise _LocalXPromptNameError(
                f"Local xprompt '{name}' must start with '_' (e.g. '_{name}')"
            )
