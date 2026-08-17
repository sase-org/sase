"""Help-text shortening for column-friendly completion descriptions."""

from __future__ import annotations

import argparse
import re
from typing import Final

_SENTENCE_BOUNDARY_RE = re.compile(r"\.(?=\s|$)")
_ABBREVIATIONS = frozenset(
    {
        "e.g",
        "i.e",
        "etc",
        "approx",
        "cf",
        "vs",
        "no",
        "mr",
        "mrs",
        "dr",
        "ms",
        "jr",
        "sr",
    }
)
_ELLIPSIS = "…"

_SUMMARY_ATTR: Final = "_sase_completion_summary"


def _preceding_word(text: str, index: int) -> str:
    tokens = text[:index].split()
    return tokens[-1] if tokens else ""


def _first_sentence(text: str) -> str:
    """Return the leading sentence of *text*, skipping known abbreviations."""
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        period_index = match.start()
        if _preceding_word(text, period_index).lower() in _ABBREVIATIONS:
            continue
        return text[:period_index]
    return text


def short_summary(help_text: str, limit: int = 60) -> str:
    """Shorten *help_text* to a column-friendly completion description.

    Takes the leading sentence, collapses whitespace, strips backticks, and
    -- only if still over *limit* -- truncates at the last word boundary at
    or before ``limit - 1`` and appends an ellipsis. Never truncates
    mid-word.
    """
    text = help_text.replace("`", "")
    text = " ".join(text.split())
    sentence = _first_sentence(text).rstrip(".").strip()
    if len(sentence) <= limit:
        return sentence

    truncated = sentence[: limit - 1]
    boundary = truncated.rfind(" ")
    if boundary > 0:
        truncated = truncated[:boundary]
    return f"{truncated.rstrip()}{_ELLIPSIS}"


def set_completion_summary(action: argparse.Action, text: str) -> None:
    """Record an explicit short completion summary override on *action*.

    ``build_spec`` prefers this over deriving a summary from ``action.help``
    with :func:`short_summary`. Use it only where derivation reads badly.
    """
    setattr(action, _SUMMARY_ATTR, text)


def get_completion_summary(action: argparse.Action) -> str | None:
    """Return the explicit summary override recorded for *action*, if any."""
    return getattr(action, _SUMMARY_ATTR, None)


__all__ = [
    "get_completion_summary",
    "set_completion_summary",
    "short_summary",
]
