"""Mount / unmount / focus lifecycle for the agent prompt input bar."""

from __future__ import annotations

from ._prompt_bar_mount_focus import PromptBarFocusMixin
from ._prompt_bar_mount_home import PromptBarHomeMixin
from ._prompt_bar_mount_lifecycle import PromptBarLifecycleMixin
from ._prompt_bar_mount_markers import (
    strip_editor_review_markers as strip_editor_review_markers,
)
from ._prompt_bar_mount_spare import PromptBarSpareMixin

__all__ = [
    "PromptBarMountMixin",
    "strip_editor_review_markers",
]


class PromptBarMountMixin(
    PromptBarSpareMixin,
    PromptBarLifecycleMixin,
    PromptBarFocusMixin,
    PromptBarHomeMixin,
):
    """Mount/unmount + focus management for the prompt input bar."""
