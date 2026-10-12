"""Restore, fork, and copy entry points for Archive rows (sase-1jm.5).

Public facade for the split restore modules. Behavior lives in
:mod:`sase.ace.tui.actions.agents._archive_restore_types` (choice keys and
outcome types), ``_archive_restore_keys`` (target collection and hydration),
``_archive_restore_run`` (restore submission, toasts, and reveal), and
``_archive_restore_entry`` (fork, chat, and chooser). Shared helpers live as
public names in the already-private ``_archive_restore_support`` module so no
split module imports a ``_``-prefixed name across modules. This module
re-exports the public names only so every existing import path keeps working.
"""

from __future__ import annotations

from ._archive_restore_entry import (
    archive_chooser_model,
    archive_fork_accepted,
    fork_archive_agent,
    open_archive_chat,
    open_archive_chooser,
)
from ._archive_restore_keys import (
    collect_archive_restore_keys,
    hydrate_archive_candidate,
)
from ._archive_restore_run import run_archive_restore
from ._archive_restore_types import (
    CHOICE_COPY_MORE,
    CHOICE_COPY_REF,
    CHOICE_FORK,
    CHOICE_OPEN_CHAT,
    CHOICE_RESTORE,
    CHOICE_RESTORE_SHOW,
    ArchiveRestoreSkip,
    ArchiveRestoreSummary,
)

__all__ = [
    "CHOICE_COPY_MORE",
    "CHOICE_COPY_REF",
    "CHOICE_FORK",
    "CHOICE_OPEN_CHAT",
    "CHOICE_RESTORE",
    "CHOICE_RESTORE_SHOW",
    "ArchiveRestoreSkip",
    "ArchiveRestoreSummary",
    "archive_chooser_model",
    "archive_fork_accepted",
    "collect_archive_restore_keys",
    "fork_archive_agent",
    "hydrate_archive_candidate",
    "open_archive_chat",
    "open_archive_chooser",
    "run_archive_restore",
]
