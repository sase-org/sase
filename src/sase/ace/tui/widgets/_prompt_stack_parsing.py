"""Canonical parsing helpers for prompt-stack text."""

from __future__ import annotations

from sase.agent.multi_prompt import split_segments_protecting_fences
from sase.xprompt.loader_parsing import parse_yaml_front_matter


def split_prompt_text(text: str) -> list[str]:
    """Split *text* into prompt segments using canonical multi-prompt parsing.

    Thin wrapper over :func:`split_segments_protecting_fences` so callers in the
    TUI layer have a single, intention-revealing entry point.  Empty and
    whitespace-only segments are dropped, fenced ``---`` is protected, and
    leading YAML frontmatter is consumed rather than split.
    """
    return split_segments_protecting_fences(text)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(raw_frontmatter, body)`` for *text*.

    ``raw_frontmatter`` is the leading YAML frontmatter block including its
    opening and closing ``---`` delimiters (no trailing newline), or ``""`` when
    *text* has no valid frontmatter.  ``body`` is the remaining text after the
    frontmatter, matching :func:`parse_yaml_front_matter` exactly so that
    splitting the body stays consistent with agent dispatch.

    Public so the app layer can inspect an incoming prompt's frontmatter
    (e.g. a history entry) without loading it into the bar.
    """
    frontmatter, body = parse_yaml_front_matter(text)
    if frontmatter is None:
        return "", text

    lines = text.split("\n")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[: index + 1]), body
    # Unreachable: parse_yaml_front_matter only returns a dict when a closing
    # delimiter exists, but fall back to "no frontmatter" defensively.
    return "", text


__all__ = ["split_frontmatter", "split_prompt_text"]
