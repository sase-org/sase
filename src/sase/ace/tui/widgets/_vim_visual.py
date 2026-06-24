"""Vim visual-mode key handling for PromptTextArea."""

from __future__ import annotations

from sase.ace.tui.widgets._vim_visual_keys import VimVisualKeyHandlingMixin
from sase.ace.tui.widgets._vim_visual_state import VisualKind


class VimVisualModeMixin(VimVisualKeyHandlingMixin):
    """Compatibility facade for vim visual-mode key handling."""


__all__ = ["VisualKind", "VimVisualModeMixin"]
