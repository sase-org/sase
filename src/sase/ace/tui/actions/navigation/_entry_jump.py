"""Adaptive entry-jump navigation facade for the ace TUI app."""

from __future__ import annotations

from ._entry_jump_dispatch import EntryJumpDispatchMixin


class EntryJumpNavigationMixin(EntryJumpDispatchMixin):
    """Mixin providing adaptive entry-jump navigation."""

    pass
