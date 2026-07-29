"""Warm directory snapshots for prompt ``@`` path completion."""

from __future__ import annotations

from itertools import islice
from typing import NamedTuple
import os

from sase.ace.tui.widgets.file_completion import lookup_completion_path
from sase.ace.tui.widgets.prompt_completion_root import (
    resolve_prompt_completion_base_dir,
)

MAX_PROMPT_PATH_ROWS = 1000
"""Maximum number of directory entries retained in one prompt snapshot."""


class PromptPathRow(NamedTuple):
    """One immutable directory entry supplied to the completion policy."""

    name: str
    is_dir: bool


class PromptPathSnapshot(NamedTuple):
    """A directory listing and the metadata token that validates it."""

    directory_key: str
    rows: tuple[PromptPathRow, ...]
    token: tuple[int, int] | None


def prompt_path_directory_key(prompt: str, directory: str = "") -> str:
    """Resolve *directory* exactly as prompt file completion does.

    This helper performs path-string expansion only. It deliberately does not
    stat, scan, or canonicalize the resulting directory.
    """
    base_dir = resolve_prompt_completion_base_dir(prompt) or os.getcwd()
    raw_directory = directory or "."
    resolved = lookup_completion_path(raw_directory, base_dir=base_dir)
    return os.path.abspath(os.path.normpath(resolved))


def load_prompt_path_snapshot(abs_dir: str) -> PromptPathSnapshot:
    """Load one bounded directory snapshot.

    This function performs filesystem I/O and must only run in a background
    worker. Unreadable or missing directories become cold empty snapshots so a
    later revalidation can retry them.
    """
    directory_key = os.path.abspath(os.path.normpath(abs_dir))
    try:
        stat = os.stat(directory_key)
        token = (stat.st_mtime_ns, stat.st_ino)
        with os.scandir(directory_key) as entries:
            rows = tuple(
                PromptPathRow(
                    entry.name,
                    _entry_is_dir(entry),
                )
                for entry in islice(entries, MAX_PROMPT_PATH_ROWS)
            )
    except OSError:
        return PromptPathSnapshot(directory_key, (), None)

    return PromptPathSnapshot(
        directory_key,
        tuple(
            sorted(
                rows, key=lambda row: (not row.is_dir, row.name.casefold(), row.name)
            )
        ),
        token,
    )


def revalidate_prompt_path_snapshot(
    abs_dir: str,
    previous: PromptPathSnapshot | None,
) -> PromptPathSnapshot:
    """Return *previous* when its directory token is unchanged.

    The cheap token check and any resulting rescan both belong on the worker
    thread. Returning the same object lets the UI handler skip a needless menu
    refresh.
    """
    directory_key = os.path.abspath(os.path.normpath(abs_dir))
    try:
        stat = os.stat(directory_key)
        token: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_ino)
    except OSError:
        token = None

    if (
        previous is not None
        and previous.directory_key == directory_key
        and previous.token == token
    ):
        return previous
    return load_prompt_path_snapshot(directory_key)


def _entry_is_dir(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir(follow_symlinks=True)
    except OSError:
        return False
