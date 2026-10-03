"""Post-unmount focus targeting for the agent prompt input bar."""

from __future__ import annotations


class PromptBarFocusMixin:
    """Move focus off the bar to the active tab's list widget on detach."""

    def _transfer_focus_off_prompt_bar(self, bar: object) -> None:
        """Move focus from *bar*'s descendants to the active tab's list widget.

        Must be called *before* the bar is detached from its parent so that
        Textual's focus-transfer machinery sees a live widget tree.
        """
        screen = getattr(self, "screen", None)
        focused = getattr(screen, "focused", None) if screen is not None else None

        # Only re-target focus if it is currently inside the bar (the common
        # case — the PromptTextArea owns focus while the bar is mounted).
        if focused is None or not self._widget_contains(bar, focused):
            return

        target = self._post_unmount_focus_target()
        if target is not None:
            try:
                target.focus()  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        # Fallback: move focus to the next focusable sibling so we never leave
        # Screen.focused dangling on the about-to-be-detached text area.
        try:
            self.focus_next()  # type: ignore[attr-defined]
        except Exception:
            pass

    @staticmethod
    def _widget_contains(ancestor: object, descendant: object) -> bool:
        """Return True if *descendant* is *ancestor* or a child of it."""
        node = descendant
        while node is not None:
            if node is ancestor:
                return True
            node = getattr(node, "_parent", None)
        return False

    def _post_unmount_focus_target(self) -> object | None:
        """Return the widget that should own focus after the bar is unmounted.

        Keyed off the currently active tab.  Returns ``None`` if no
        suitable target can be resolved.
        """
        tab = getattr(self, "current_tab", None)
        candidates: tuple[str, ...]
        if tab == "agents":
            from ..agents._display_helpers import (
                _MAIN_PANEL_ID,
                first_agent_list_widget,
            )

            widget = first_agent_list_widget(self)
            if widget is not None:
                return widget
            candidates = (f"#{_MAIN_PANEL_ID}",)
        elif tab == "services":
            focus_axe = getattr(self, "_focus_axe_focused_panel", None)
            if callable(focus_axe):
                try:
                    focus_axe(force=True)
                except Exception:
                    pass
                widget = getattr(self, "focused", None)
                from ...widgets import BgCmdList

                if isinstance(widget, BgCmdList):
                    return widget
            candidates = ("#service-procs-panel",)
        else:
            candidates = ("#list-panel",)

        for selector in candidates:
            try:
                widget = self.query_one(selector)  # type: ignore[attr-defined]
            except Exception:
                continue
            if getattr(widget, "display", True) and getattr(widget, "can_focus", True):
                return widget
        return None
