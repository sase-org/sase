"""Cleanup and repair commands for ``sase workspace``.

This module is a backwards-compatible facade. Implementations live in
:mod:`workspace_handler_maintenance_cleanup`,
:mod:`workspace_handler_maintenance_compact`, and
:mod:`workspace_handler_maintenance_repair`, with helpers shared by more
than one of those modules exposed under public names from the private
:mod:`_workspace_handler_maintenance_shared` module.
"""

from __future__ import annotations

from ._workspace_handler_maintenance_shared import ClaimedNums
from .workspace_handler_maintenance_cleanup import (
    RemoveCheckout,
    RemoveTransitionSymlink,
    claimed_nums,
    handle_cleanup,
    remove_checkout,
    remove_transition_symlink,
)
from .workspace_handler_maintenance_compact import handle_compact
from .workspace_handler_maintenance_repair import handle_repair

__all__ = [
    "ClaimedNums",
    "RemoveCheckout",
    "RemoveTransitionSymlink",
    "claimed_nums",
    "handle_cleanup",
    "handle_compact",
    "handle_repair",
    "remove_checkout",
    "remove_transition_symlink",
]
