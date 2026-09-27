"""Prompt-stash restore and pinned-entry workflows (facade).

This module preserves the original public import path. The implementation
lives in :mod:`_prompt_bar_stash_restore_overlay`,
:mod:`_prompt_bar_stash_restore_trash`, and
:mod:`_prompt_bar_stash_restore_apply`; this facade only combines the
public mixins into :class:`PromptBarStashRestoreMixin`.
"""

from __future__ import annotations

from ._prompt_bar_stash_restore_apply import PromptBarStashRestoreApplyMixin
from ._prompt_bar_stash_restore_overlay import PromptBarStashRestoreOverlayMixin
from ._prompt_bar_stash_restore_trash import PromptBarStashRestoreTrashMixin


__all__ = ["PromptBarStashRestoreMixin"]


class PromptBarStashRestoreMixin(
    PromptBarStashRestoreOverlayMixin,
    PromptBarStashRestoreTrashMixin,
    PromptBarStashRestoreApplyMixin,
):
    """Restore, pin, and remove entries from the shared prompt stash."""
