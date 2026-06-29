"""Snippet skeleton helpers for xprompt argument assist."""

from __future__ import annotations

from string import punctuation

from ._xprompt_arg_assist_inputs import required_inputs
from ._xprompt_arg_assist_models import XPromptAssistEntry

_NO_ARG_SPACE_SUPPRESSING_CHARS = frozenset(punctuation)


def _suppresses_no_arg_space(next_char: str | None) -> bool:
    """Return True when a following character should hug a no-arg xprompt."""
    return next_char is not None and next_char in _NO_ARG_SPACE_SUPPRESSING_CHARS


def named_args_skeleton(entry: XPromptAssistEntry) -> str:
    """Return a required-only named-argument snippet skeleton."""
    inputs = required_inputs(entry)
    if not inputs:
        return entry.insertion
    args = ", ".join(f"{inp.name}=${index}" for index, inp in enumerate(inputs, 1))
    return f"{entry.insertion}({args})$0"


def colon_args_skeleton(entry: XPromptAssistEntry) -> str:
    """Return a colon-argument snippet skeleton for the entry."""
    return f"{entry.insertion}:$0"


def xprompt_completion_skeleton(
    entry: XPromptAssistEntry,
    *,
    append_text_arg_space: bool = False,
    next_char: str | None = None,
) -> str:
    """Return the Ctrl+T accept skeleton for an xprompt completion entry.

    For an entry with exactly one required ``text`` input the skeleton is the
    ``::`` double-colon shorthand. The free-form text shorthand is ``:: ``
    followed by text, so when ``append_text_arg_space`` is True the skeleton is
    emitted as ``#name:: `` (with a trailing space) -- this is set by callers
    only when the completion lands at end-of-line, leaving the user one keystroke
    from typing the free-form body. Every other input shape ignores the flag.
    """
    inputs = required_inputs(entry)
    if not inputs:
        if _suppresses_no_arg_space(next_char):
            return entry.insertion
        return f"{entry.insertion} "
    if len(inputs) > 1:
        return f"{entry.insertion}($0)"
    if inputs[0].type == "text":
        suffix = ":: " if append_text_arg_space else "::"
        return f"{entry.insertion}{suffix}"
    return f"{entry.insertion}:"


def xprompt_completion_suffix_skeleton(
    entry: XPromptAssistEntry,
    *,
    append_text_arg_space: bool = False,
    next_char: str | None = None,
) -> str:
    """Return a completion skeleton inserted after an existing ``#`` trigger."""
    skeleton = xprompt_completion_skeleton(
        entry,
        append_text_arg_space=append_text_arg_space,
        next_char=next_char,
    )
    if skeleton.startswith("#"):
        return skeleton[1:]
    return skeleton


__all__ = [
    "colon_args_skeleton",
    "named_args_skeleton",
    "xprompt_completion_skeleton",
    "xprompt_completion_suffix_skeleton",
]
