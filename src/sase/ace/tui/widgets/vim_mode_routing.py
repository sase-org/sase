"""Route a focused vim editor's mode to its host screen when the host wants it."""

from __future__ import annotations

#: Vim mode name to the chip label a host screen renders for it.
VIM_MODE_LABELS = {
    "insert": "INSERT",
    "normal": "NORMAL",
    "visual": "VISUAL",
    "visual_line": "V-LINE",
}


class VimModeRoutingMixin:
    """Hand this editor's vim mode to ``screen._set_editor_mode_label``.

    A host screen that exposes the hook owns the mode chip for every editor it
    contains; any other host keeps the editor's own border-title fallback. The
    host call is guarded because a host that raises must never break editing.
    """

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        try:
            setter = getattr(
                getattr(self, "screen", None), "_set_editor_mode_label", None
            )
        except Exception:
            setter = None
        if not callable(setter):
            super()._update_vim_mode_display(indicator)  # type: ignore[misc]
            return
        mode = VIM_MODE_LABELS.get(getattr(self, "_vim_mode", ""), "")
        try:
            setter(mode, indicator)
        except Exception:
            super()._update_vim_mode_display(indicator)  # type: ignore[misc]


__all__ = ["VIM_MODE_LABELS", "VimModeRoutingMixin"]
