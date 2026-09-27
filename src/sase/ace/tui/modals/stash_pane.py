"""Reusable Stash pane and its shared controller logic.

This module is the public home of the stash list/preview UI and interaction
logic shared by the standalone :class:`StashedPromptsModal` and the tabbed
:class:`PromptsModal` overlay. The implementation lives in focused sibling
modules — :mod:`stash_messages`, :mod:`stash_controller`, and
:mod:`stash_pane_widget` (plus the private :mod:`_stash_trash_commit` and
:mod:`_stash_controller_state` helpers) — and is re-exported here so the
original import path keeps working.
"""

from __future__ import annotations

from ._stash_trash_commit import preview_trash_commit as preview_trash_commit
from ._stash_trash_commit import trash_commit_confirm_text as trash_commit_confirm_text
from ._stash_trash_commit import trash_outcome_text as trash_outcome_text
from .stash_controller import StashControllerMixin as StashControllerMixin
from .stash_messages import DeleteRequested as DeleteRequested
from .stash_messages import PinToggled as PinToggled
from .stash_messages import STASH_BINDINGS as STASH_BINDINGS
from .stash_messages import StashRestoreResult as StashRestoreResult
from .stash_messages import TrashRequested as TrashRequested
from .stash_messages import newest_first_stash_entries as newest_first_stash_entries
from .stash_messages import single_restore_result as single_restore_result
from .stash_pane_widget import StashPane as StashPane

__all__ = [
    "DeleteRequested",
    "PinToggled",
    "STASH_BINDINGS",
    "StashControllerMixin",
    "StashPane",
    "StashRestoreResult",
    "TrashRequested",
    "newest_first_stash_entries",
    "single_restore_result",
    "preview_trash_commit",
    "trash_commit_confirm_text",
    "trash_outcome_text",
]
