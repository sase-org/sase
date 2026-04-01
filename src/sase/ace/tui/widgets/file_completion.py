"""Pure-logic file completion engine for the prompt input bar."""

from __future__ import annotations

import os
from dataclasses import dataclass

MAX_VISIBLE = 10
"""Maximum number of completion entries visible in the panel at once."""


@dataclass(slots=True)
class CompletionCandidate:
    """Single file completion candidate."""

    display: str
    insertion: str
    is_dir: bool
    name: str


def _is_token_delimiter(char: str) -> bool:
    """Return True when *char* terminates a token."""
    return char.isspace() or char in {"'", '"', "`"}


def is_path_like_token(token: str) -> bool:
    """Return True when token looks like a file path fragment."""
    if not token:
        return False
    if token.startswith(("~/", "/", "./", "../", ".sase/")):
        return True
    return "/" in token


def extract_token_around_cursor(line: str, col: int) -> tuple[int, int, str] | None:
    """Extract token bounds around a cursor position in a line.

    Args:
        line: The text line to scan.
        col: Cursor column within the line.

    Returns:
        (start, end, token) or None if cursor is not on a token.
    """
    col = min(col, len(line))

    start = col
    while start > 0 and not _is_token_delimiter(line[start - 1]):
        start -= 1

    end = col
    while end < len(line) and not _is_token_delimiter(line[end]):
        end += 1

    if start == end:
        return None
    return start, end, line[start:end]


def build_completion_candidates(
    token: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates and shared extension for a path token.

    Dotfiles (entries starting with ``'.'``) are hidden unless the partial
    filter prefix itself starts with ``'.'``, matching standard shell behavior.

    Symlinked directories are followed so they appear as directories.
    """
    if token.endswith("/"):
        raw_dir = token
        expanded_dir = os.path.expanduser(token)
        partial = ""
    else:
        raw_head, raw_tail = token.rsplit("/", 1)
        raw_dir = f"{raw_head}/"
        expanded_head, expanded_tail = os.path.expanduser(token).rsplit("/", 1)
        expanded_dir = f"{expanded_head}/"
        partial = expanded_tail
        if raw_tail != expanded_tail:
            # expanduser can only alter the head, so keep caller-visible partial
            partial = raw_tail

    show_dotfiles = partial.startswith(".")

    try:
        with os.scandir(expanded_dir) as entries:
            candidates: list[CompletionCandidate] = []
            for entry in entries:
                # Dotfile filtering: skip entries starting with '.' unless
                # the user's partial prefix also starts with '.'
                if entry.name.startswith(".") and not show_dotfiles:
                    continue
                if not entry.name.lower().startswith(partial.lower()):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                except OSError:
                    is_dir = False
                display = f"{entry.name}/" if is_dir else entry.name
                candidates.append(
                    CompletionCandidate(
                        display=display,
                        insertion=f"{raw_dir}{display}",
                        is_dir=is_dir,
                        name=entry.name,
                    )
                )
    except OSError:
        return [], ""

    candidates.sort(key=lambda c: (not c.is_dir, c.name.lower(), c.name))

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix([c.name for c in candidates])
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension
