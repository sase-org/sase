"""Archive-restore shared types and chooser choice keys.

Type seam for the Archive restore split. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_restore`, which re-exports this
module's public names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

CHOICE_RESTORE = "archive-restore"
CHOICE_RESTORE_SHOW = "archive-restore-show"
CHOICE_FORK = "archive-fork"
CHOICE_OPEN_CHAT = "archive-open-chat"
CHOICE_COPY_REF = "archive-copy-ref"
CHOICE_COPY_MORE = "archive-copy-more"


@dataclass(frozen=True, slots=True)
class ArchiveRestoreSkip:
    """One requested restore that did not run, with its user-facing reason."""

    key: str
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ArchiveRestoreSummary:
    """Outcome of one Archive restore submission for toasts and tests."""

    restored: tuple[tuple[str, str], ...]
    skipped: tuple[ArchiveRestoreSkip, ...]
    failed: tuple[tuple[str, str, str], ...]
    and_show: bool = False


@dataclass(frozen=True, slots=True)
class ArchiveRestoreTargets:
    """The run keys one restore acts on, resolved once per chooser open.

    ``keys`` drives both the chooser's label count and the executed restore,
    so the two always agree. ``rows`` carries the light rows of container
    members, which a collapsed container never loads into the column.
    ``skipped`` holds containers that resolved to no matching members.
    """

    keys: tuple[str, ...] = ()
    rows: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    skipped: tuple[ArchiveRestoreSkip, ...] = ()
    marked: bool = False


__all__ = [
    "CHOICE_COPY_MORE",
    "CHOICE_COPY_REF",
    "CHOICE_FORK",
    "CHOICE_OPEN_CHAT",
    "CHOICE_RESTORE",
    "CHOICE_RESTORE_SHOW",
    "ArchiveRestoreSkip",
    "ArchiveRestoreSummary",
    "ArchiveRestoreTargets",
]
