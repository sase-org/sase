"""Pure-logic xprompt completion engine for the prompt input bar."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    extract_token_around_cursor,
)
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
)
from sase.xprompt.naming import (
    is_inline_reference_name,
    is_inline_reference_name_char,
)

_SLASH_SKILL_TOKEN_RE = re.compile(r"^/[A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class XPromptTokenSpan:
    """Grammar-aware bounds for an xprompt completion token."""

    start: int
    end: int
    token: str
    clamped: bool


def is_xprompt_like_token(token: str) -> bool:
    """Return True when token looks like an xprompt or slash-skill reference."""
    if not token:
        return False
    if token.startswith("/"):
        return _SLASH_SKILL_TOKEN_RE.fullmatch(token) is not None
    if not token.startswith("#"):
        return False
    # Must have no whitespace (token extraction already strips whitespace,
    # but guard against edge cases).
    return not any(c.isspace() for c in token)


def extract_xprompt_token_around_cursor(
    line: str,
    col: int,
) -> XPromptTokenSpan | None:
    """Extract an xprompt token without consuming trailing punctuation."""
    col = min(col, len(line))
    raw_span = extract_token_around_cursor(line, col)
    if raw_span is None:
        return None

    start, raw_end, raw_token = raw_span
    if not raw_token.startswith("#"):
        if not is_xprompt_like_token(raw_token):
            return None
        return XPromptTokenSpan(start, raw_end, raw_token, clamped=False)

    marker_length = 2 if raw_token.startswith("#!") else 1
    name_end = start + marker_length
    while name_end < raw_end and is_inline_reference_name_char(line[name_end]):
        name_end += 1

    if col > name_end:
        return None
    return XPromptTokenSpan(
        start=start,
        end=name_end,
        token=line[start:name_end],
        clamped=name_end < raw_end,
    )


def build_xprompt_completion_candidates(
    token: str,
    *,
    entries: list[XPromptAssistEntry] | None = None,
    inline_reference_only: bool = False,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates and shared extension for an xprompt token.

    Args:
        token: The full token including the leading ``#`` or ``/``.

    Returns:
        (candidates, shared_extension) just like the file completion builder.
    """
    slash_skill = token.startswith("/")
    standalone_only = token.startswith("#!")
    partial = token[2:] if standalone_only else token[1:]
    partial_lower = partial.lower()

    source_entries = entries if entries is not None else []
    candidates: list[CompletionCandidate] = []
    for entry in source_entries:
        if inline_reference_only and not is_inline_reference_name(entry.name):
            continue
        # ``#`` completion matches the xprompt reference name (``skill/foo``);
        # ``/`` completion matches the provider skill name (``foo``).
        match_name = entry.name
        if slash_skill:
            if not entry.is_skill or not entry.skill_name:
                continue
            match_name = entry.skill_name
        elif standalone_only:
            if entry.reference_prefix != "#!":
                continue
        insertion = f"/{match_name}" if slash_skill else entry.insertion
        if not match_name.lower().startswith(partial_lower):
            continue
        candidates.append(
            CompletionCandidate(
                display=insertion,
                insertion=insertion,
                is_dir=False,
                name=match_name,
                metadata=entry,
            )
        )

    candidates.sort(key=lambda c: c.name.lower())

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix([c.name for c in candidates])
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension
