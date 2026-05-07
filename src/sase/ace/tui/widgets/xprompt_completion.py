"""Pure-logic xprompt completion engine for the prompt input bar."""

from __future__ import annotations

import os
import re

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.xprompt_arg_assist import build_xprompt_assist_entries

_SLASH_SKILL_TOKEN_RE = re.compile(r"^/[A-Za-z0-9_]*$")


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


def build_xprompt_completion_candidates(
    token: str,
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

    candidates: list[CompletionCandidate] = []
    for entry in build_xprompt_assist_entries():
        if slash_skill:
            if not entry.is_skill:
                continue
        elif standalone_only:
            if entry.reference_prefix != "#!":
                continue
        insertion = f"/{entry.name}" if slash_skill else entry.insertion
        if not entry.name.lower().startswith(partial_lower):
            continue
        candidates.append(
            CompletionCandidate(
                display=insertion,
                insertion=insertion,
                is_dir=False,
                name=entry.name,
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
