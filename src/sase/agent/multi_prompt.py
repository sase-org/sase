"""Multi-prompt parsing: split a user prompt into frontmatter + segments.

A user prompt may contain YAML frontmatter (for local macros) and ``---``
segment separators (for launching multiple agents sequentially).

Rules:
- The first ``---`` pair at the start of the document is frontmatter.
- After frontmatter is consumed, subsequent ``---`` lines are segment separators.
- If there is no frontmatter, ALL ``---`` lines are segment separators.
- A prompt with frontmatter but only one segment is a single-agent prompt
  with local macros (not a multi-agent prompt).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.macro._fenced_blocks import protect_fenced_blocks
from sase.macro.loader_parsing import (
    LocalMacroNameError,
    parse_local_macro_entries,
    parse_yaml_front_matter,
)
from sase.macro.models import Macro

_SEGMENT_SEP_RE = re.compile(r"^---\s*$", re.MULTILINE)


def split_segments_protecting_fences(body: str) -> list[str]:
    """Split *body* on ``---`` separator lines, protecting fenced code blocks.

    Empty/whitespace-only segments are dropped.  Used both by
    :func:`parse_multi_prompt` (to split user-submitted prompts) and by
    :mod:`sase.agent.macro_swarm` (to split a macro swarm body
    after argument substitution).
    """
    from sase.core.agent_launch_facade import plan_agent_launch_fanout

    plan = plan_agent_launch_fanout(body, launch_kind="multi_prompt")
    return [slot.prompt for slot in plan.slots]


@dataclass
class _MultiPrompt:
    """Result of parsing a user prompt into frontmatter and segments."""

    frontmatter: dict[str, object] | None = None
    local_macros: dict[str, Macro] = field(default_factory=dict)
    segments: list[str] = field(default_factory=list)
    template_groups: list[str | None] | None = None
    swarm_macros: list[tuple[str, ...]] | None = None


_LocalMacroNameError = LocalMacroNameError


def parse_multi_prompt(text: str) -> _MultiPrompt:
    """Parse a user prompt into frontmatter, local macros, and segments.

    Steps:
        1. Extract YAML frontmatter (if present).
        2. Parse the ``macros`` key from frontmatter into ``Macro`` objects.
        3. Validate that all local macro names start with ``_``.
        4. Split the remaining body on ``---`` lines (protecting fenced code
           blocks so that ``---`` inside code blocks is not treated as a
           separator).
        5. Strip empty/whitespace-only segments.

    Raises:
        _LocalMacroNameError: If any macro name does not start with ``_``.
    """
    frontmatter, body = parse_yaml_front_matter(text)

    # Extract local macros from frontmatter: canonical ``macros``, with
    # retired ``xprompts`` gated by the sunset flag. Both spellings in one
    # mapping, or a retired spelling with the flag off, raises.
    local_macros: dict[str, Macro] = {}
    if frontmatter is not None:
        from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

        macro_entries = normalize_frontmatter_macros(frontmatter, source="user-prompt")
        frontmatter.pop("xprompts", None)
        frontmatter.pop("macros", None)
        if macro_entries:
            local_macros = parse_local_macro_entries(
                macro_entries, source_path="user-prompt"
            )

    segments = split_segments_protecting_fences(body)

    return _MultiPrompt(
        frontmatter=frontmatter,
        local_macros=local_macros,
        segments=segments,
    )


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
