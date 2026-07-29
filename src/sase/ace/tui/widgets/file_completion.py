"""Pure-logic file completion engine for the prompt input bar."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

COMPLETION_PANEL_MAX_HEIGHT = 10
"""Mirror of the ``max-height`` for ``#prompt-completion`` in styles.tcss."""

COMPLETION_PANEL_BORDER_ROWS = 2
"""Top and bottom border rows the completion panel spends on its frame."""

COMPLETION_PANEL_CONTENT_ROWS = (
    COMPLETION_PANEL_MAX_HEIGHT - COMPLETION_PANEL_BORDER_ROWS
)
"""Content lines the completion panel can render without clipping."""


def completion_visible_rows(total: int, *, group_rule: bool = False) -> int:
    """Return how many candidate rows the panel can render without clipping.

    Args:
        total: Number of candidates available.
        group_rule: True when the renderer draws a group rule line, which
            costs one content line of its own.

    Returns:
        The visible-row budget, reserving a line for the ``↓ N more…``
        indicator whenever the candidates overflow the panel.
    """
    capacity = COMPLETION_PANEL_CONTENT_ROWS - (1 if group_rule else 0)
    if total > capacity:
        capacity -= 1
    return max(1, capacity)


def completion_scroll_offset(
    total: int,
    selected_index: int,
    *,
    group_rule: bool = False,
) -> int:
    """Return the first visible row index that keeps *selected_index* on screen.

    Args:
        total: Number of candidates available.
        selected_index: Highlighted candidate index.
        group_rule: True when the renderer draws a group rule line.

    Returns:
        A scroll offset clamped so the highlighted row is inside the window
        produced by :func:`completion_visible_rows`.
    """
    visible = completion_visible_rows(total, group_rule=group_rule)
    if total <= visible:
        return 0
    half = visible // 2
    return max(0, min(selected_index - half, total - visible))


@dataclass(slots=True)
class CompletionCandidate:
    """Single candidate rendered by the shared prompt completion panel."""

    display: str
    insertion: str
    is_dir: bool
    name: str
    metadata: Any | None = None


_TOKEN_DELIMITERS: frozenset[str] = frozenset("'\"`?!;,()[]{}<>|&=+*^%$:\\")


def _is_token_delimiter(char: str) -> bool:
    """Return True when *char* terminates a token."""
    return char.isspace() or char in _TOKEN_DELIMITERS


def is_path_like_token(token: str) -> bool:
    """Return True when token looks like a file path fragment."""
    if not token:
        return False
    # Strip a leading @ (file-reference prefix) before checking patterns.
    bare = token[1:] if token.startswith("@") else token
    if not bare:
        return False
    if bare.startswith(("~/", "/", "./", "../", ".sase/")):
        return True
    return "/" in bare


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

    if start >= 2 and line[start - 2 : start] == "#!":
        marker_start = start - 2
        if marker_start == 0 or _is_token_delimiter(line[marker_start - 1]):
            start = marker_start

    if start == end and col >= 2 and line[col - 2 : col] == "#!":
        marker_start = col - 2
        if marker_start == 0 or _is_token_delimiter(line[marker_start - 1]):
            return marker_start, col, "#!"

    if start == end:
        return None
    return start, end, line[start:end]


def build_completion_candidates(
    token: str,
    *,
    base_dir: str | os.PathLike[str] | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates and shared extension for a path token.

    Dotfiles (entries starting with ``'.'``) are hidden unless the partial
    filter prefix itself starts with ``'.'``, matching standard shell behavior.

    Symlinked directories are followed so they appear as directories.
    """
    # Strip a leading @ (file-reference prefix) so path expansion works.
    at_prefix = ""
    if token.startswith("@"):
        at_prefix = "@"
        token = token[1:]

    if token.endswith("/"):
        raw_dir = token
        expanded_dir = _lookup_path(token, base_dir=base_dir)
        partial = ""
    else:
        raw_head, raw_tail = token.rsplit("/", 1)
        raw_dir = f"{raw_head}/"
        expanded_head, expanded_tail = _lookup_path(
            token,
            base_dir=base_dir,
        ).rsplit("/", 1)
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

    if at_prefix:
        for c in candidates:
            c.insertion = at_prefix + c.insertion

    return candidates, shared_extension


def _lookup_path(
    raw_path: str,
    *,
    base_dir: str | os.PathLike[str] | None,
) -> str:
    """Return the filesystem path used to look up a caller-visible token."""
    expanded = os.path.expandvars(os.path.expanduser(raw_path))
    if base_dir is None or os.path.isabs(expanded):
        return expanded
    return os.path.join(os.fspath(base_dir), expanded)


def build_file_history_completion_candidates() -> tuple[list[CompletionCandidate], str]:
    """Build candidates from the recency-ordered file-reference history.

    Each history entry becomes one candidate whose ``display`` and
    ``insertion`` are the raw stored path.  The returned ``shared_extension``
    is always empty — there is no prefix-based filtering on this list.
    """
    from sase.history.file_references import load_file_references

    paths = load_file_references()
    candidates = [
        CompletionCandidate(
            display=path,
            insertion=path,
            is_dir=False,
            name=path,
        )
        for path in paths
    ]
    return candidates, ""
