"""Pure-logic xprompt completion engine for the prompt input bar."""

from __future__ import annotations

import os

from sase.ace.tui.widgets.file_completion import CompletionCandidate


def is_xprompt_like_token(token: str) -> bool:
    """Return True when token looks like an xprompt reference (starts with #)."""
    if not token or not token.startswith("#"):
        return False
    # Must have no whitespace (token extraction already strips whitespace,
    # but guard against edge cases).
    return not any(c.isspace() for c in token)


def build_xprompt_completion_candidates(
    token: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates and shared extension for an xprompt token.

    Args:
        token: The full token including the leading ``#``.

    Returns:
        (candidates, shared_extension) just like the file completion builder.
    """
    from sase.xprompt.loader import get_all_prompts

    partial = token[1:]  # strip leading '#'
    all_prompts = get_all_prompts()
    partial_lower = partial.lower()

    candidates: list[CompletionCandidate] = []
    for name in all_prompts:
        if not name.lower().startswith(partial_lower):
            continue
        candidates.append(
            CompletionCandidate(
                display=name,
                insertion=f"#{name}",
                is_dir=False,
                name=name,
            )
        )

    candidates.sort(key=lambda c: c.name.lower())

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix([c.name for c in candidates])
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension
