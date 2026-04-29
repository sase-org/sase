"""Multi-agent xprompt expansion at dispatch time.

When a user-prompt segment is a top-level reference to an xprompt whose body
contains ``---`` segment separators, expand the xprompt body once (substituting
the call-site's arguments) and then split the substituted body on ``---``,
replacing the original segment with N sub-segments — one per body segment.

Each spawned agent therefore receives the same input arguments, substituted
into its own segment.  See ``plans/202604/multi_agent_xprompts.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.agent.multi_prompt import split_segments_protecting_fences
from sase.xprompt._fenced_blocks import protect_fenced_blocks
from sase.xprompt._parsing import find_matching_paren_for_args, parse_args
from sase.xprompt.loader import get_all_xprompts
from sase.xprompt.models import XPrompt
from sase.xprompt.processor import expand_single_xprompt

_SEGMENT_SEP_RE = re.compile(r"^---\s*$", re.MULTILINE)

# Lines that are treated as leading directives attached to the call site
# (not part of the xprompt reference itself).  Mirrors the directive forms
# accepted elsewhere in the codebase: %name, %name:..., %wait, %m(...), etc.
_DIRECTIVE_LINE_RE = re.compile(r"^%[a-zA-Z][a-zA-Z0-9_]*(?:[:(].*)?\s*$")

# Matches a single xprompt reference token (subset of processor._XPROMPT_PATTERN
# without the leading-context lookbehind, since we anchor at start-of-string).
_REFERENCE_RE = re.compile(
    r"^#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?:(\()|:(`[^`]*`|\$\([^)]*\)|[a-zA-Z0-9_.~,/-]*[a-zA-Z0-9_~/-])|(\+))?"
)


class _MultiAgentXPromptError(ValueError):
    """Base class for multi-agent xprompt expansion errors."""


# pyvision: tests/test_multi_agent_xprompt.py
class MultiAgentXPromptUsageError(_MultiAgentXPromptError):
    """Raised when a multi-agent xprompt is referenced mid-segment.

    A multi-agent xprompt (one whose body contains ``---`` separators) must
    be the *only* content in its segment.  Mixing the reference with other
    prose is ambiguous — the user can split their prompt manually if they
    want surrounding text.
    """


# pyvision: tests/test_multi_agent_xprompt.py
class MultiAgentXPromptDepthError(_MultiAgentXPromptError):
    """Raised when recursive multi-agent xprompt expansion exceeds the depth cap."""


@dataclass
class _XPromptCall:
    """A parsed top-level xprompt reference in a segment."""

    name: str
    positional_args: list[str] = field(default_factory=list)
    named_args: dict[str, str] = field(default_factory=dict)
    leading_directives: list[str] = field(default_factory=list)


# pyvision: tests/test_multi_agent_xprompt.py
def xprompt_has_segment_separators(xp: XPrompt) -> bool:
    """Return True iff *xp*'s body contains a ``---`` line outside fenced blocks."""
    blocks: list[str] = []
    protected = protect_fenced_blocks(xp.content, blocks)
    return bool(_SEGMENT_SEP_RE.search(protected))


def _split_leading_directives(segment: str) -> tuple[list[str], str]:
    """Split *segment* into (leading directive lines, remaining body).

    Directive lines are consecutive lines at the top of the segment matching
    ``_DIRECTIVE_LINE_RE``.  Leading blank lines are skipped.  The returned
    body keeps its original trailing whitespace stripped.
    """
    directives: list[str] = []
    lines = segment.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if _DIRECTIVE_LINE_RE.match(stripped):
            directives.append(stripped)
            i += 1
            continue
        break
    remaining = "\n".join(lines[i:]).strip()
    return directives, remaining


# pyvision: tests/test_multi_agent_xprompt.py
def extract_top_level_xprompt_reference(
    segment: str, available: set[str]
) -> _XPromptCall | None:
    """Return the call info if *segment* is a sole top-level xprompt reference.

    A segment qualifies if, after stripping leading blank/directive lines and
    trailing whitespace, what remains is exactly one ``#name`` (optionally with
    args) and nothing else, and ``name`` is in *available*.
    """
    directives, body = _split_leading_directives(segment)
    if not body:
        return None

    match = _REFERENCE_RE.match(body)
    if match is None:
        return None

    name = match.group(1).replace("__", "/")
    has_open_paren = match.group(2) is not None
    colon_arg = match.group(3)
    plus_suffix = match.group(4)

    positional_args: list[str] = []
    named_args: dict[str, str] = {}
    end = match.end()

    if has_open_paren:
        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(body, paren_start)
        if paren_end is None:
            return None
        paren_content = body[paren_start + 1 : paren_end]
        positional_args, named_args = parse_args(paren_content)
        end = paren_end + 1
    elif colon_arg is not None:
        if colon_arg.startswith("`") and colon_arg.endswith("`"):
            positional_args = [colon_arg[1:-1]]
        else:
            positional_args = colon_arg.split(",")
    elif plus_suffix is not None:
        positional_args = ["true"]

    # Must be the only non-directive content in the segment.
    trailing = body[end:].strip()
    if trailing:
        return None

    if name not in available:
        return None

    return _XPromptCall(
        name=name,
        positional_args=positional_args,
        named_args=named_args,
        leading_directives=directives,
    )


def _segment_contains_multi_agent_reference(
    segment: str, multi_agent_names: set[str]
) -> bool:
    """Return True if *segment* references any multi-agent xprompt anywhere.

    Used to detect the "mixed with other prose" error case.  The segment
    qualified for sole-reference treatment if and only if
    :func:`extract_top_level_xprompt_reference` returned a call;
    if it didn't but a multi-agent xprompt name still appears, the segment
    is mid-prose and we raise.
    """
    if not multi_agent_names:
        return False
    # Strip fenced code blocks so we don't false-positive on inline examples.
    blocks: list[str] = []
    protected = protect_fenced_blocks(segment, blocks)
    # Lazy import to avoid a circular dependency at module load.
    from sase.xprompt.workflow_validator_extract import extract_xprompt_calls

    for call in extract_xprompt_calls(protected):
        if call.name in multi_agent_names:
            return True
    return False


def expand_multi_agent_xprompts(
    segments: list[str],
    local_xprompts: dict[str, XPrompt] | None = None,
    *,
    max_depth: int = 8,
    _strict_segment_check: bool = True,
) -> list[str]:
    """Expand any multi-agent xprompt references in *segments* into sub-segments.

    For each segment:
        * If the segment is a sole top-level reference (per
          :func:`extract_top_level_xprompt_reference`) to an xprompt whose body
          contains ``---`` separators, substitute the call's args into the
          xprompt body and split the result on ``---``.  The call site's
          leading directives (e.g. ``%name:custom``) attach to the *first*
          sub-segment only.
        * Otherwise, the segment is passed through unchanged.

    Recursion: each sub-segment is fed back through this function with
    ``max_depth - 1`` so a multi-agent xprompt can compose another multi-agent
    xprompt.  When *max_depth* is exhausted on a still-qualifying reference,
    :class:`MultiAgentXPromptDepthError` is raised.

    Raises:
        MultiAgentXPromptUsageError: A segment contains a multi-agent xprompt
            reference but isn't a sole top-level reference to it.
        MultiAgentXPromptDepthError: Recursive expansion exceeded *max_depth*.
    """
    # Fast path: if no segment contains '#', no xprompt reference is possible.
    if not any("#" in seg for seg in segments):
        return list(segments)

    catalog: dict[str, XPrompt] = dict(get_all_xprompts())
    if local_xprompts:
        catalog.update(local_xprompts)
    available = set(catalog.keys())

    multi_agent_names = {
        name for name, xp in catalog.items() if xprompt_has_segment_separators(xp)
    }

    expanded: list[str] = []
    for segment in segments:
        call = extract_top_level_xprompt_reference(segment, available)
        if call is not None and call.name in multi_agent_names:
            if max_depth <= 0:
                raise MultiAgentXPromptDepthError(
                    f"multi-agent xprompt expansion exceeded max depth at "
                    f"#{call.name} (possible self-reference)"
                )
            xp = catalog[call.name]
            substituted = expand_single_xprompt(
                xp, call.positional_args, call.named_args
            )
            sub_segments = split_segments_protecting_fences(substituted)
            if not sub_segments:
                # An xprompt body that had separators but produces no content
                # after substitution (e.g. all-empty segments): drop entirely.
                continue
            if call.leading_directives:
                directive_block = "\n".join(call.leading_directives)
                sub_segments[0] = f"{directive_block}\n{sub_segments[0]}"
            recursively_expanded = expand_multi_agent_xprompts(
                sub_segments,
                local_xprompts=local_xprompts,
                max_depth=max_depth - 1,
                _strict_segment_check=False,
            )
            expanded.extend(recursively_expanded)
        elif _strict_segment_check and _segment_contains_multi_agent_reference(
            segment, multi_agent_names
        ):
            raise MultiAgentXPromptUsageError(
                "Multi-agent xprompt reference must be the only content in "
                "its segment (no surrounding prose). Segment:\n"
                f"{segment}"
            )
        else:
            expanded.append(segment)

    return expanded


__all__ = [
    "MultiAgentXPromptDepthError",
    "MultiAgentXPromptUsageError",
    "expand_multi_agent_xprompts",
    "extract_top_level_xprompt_reference",
    "xprompt_has_segment_separators",
]
