"""Operations pane for the SASE Admin Center."""

from __future__ import annotations

from typing import Any, Literal

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.events import Click
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Static
from textual.containers import Vertical

from .logs_pane import LogsPane
from .tasks_pane import TasksPane

OperationsSubTab = Literal["tasks", "logs"]

_SUBTAB_ORDER: tuple[OperationsSubTab, ...] = ("tasks", "logs")
_SUBTAB_LABELS: list[tuple[OperationsSubTab, str]] = [
    ("tasks", "Tasks"),
    ("logs", "Logs"),
]
_SUBTAB_COLORS: dict[OperationsSubTab, str] = {
    "tasks": "#5FD75F",
    "logs": "#FFD700",
}
_DEFAULT_SUBTAB: OperationsSubTab = "tasks"


class _OperationsSubTabStrip(Static):
    """Clickable one-line sub-tab strip for the Operations pane."""

    class SubTabClicked(Message):
        """Message emitted when an Operations sub-tab is clicked."""

        def __init__(self, subtab: OperationsSubTab) -> None:
            super().__init__()
            self.subtab: OperationsSubTab = subtab

    def __init__(self, active_subtab: OperationsSubTab, **kwargs: Any) -> None:
        self._active_subtab: OperationsSubTab = active_subtab
        self._subtab_ranges: dict[OperationsSubTab, tuple[int, int]] = {}
        self._line_width = 0
        super().__init__(self._build_content(), **kwargs)

    def set_active_subtab(self, active_subtab: OperationsSubTab) -> None:
        """Refresh the active sub-tab indicator."""
        self._active_subtab = active_subtab
        self.update(self._build_content())

    def _build_content(self) -> Text:
        text = Text()
        self._subtab_ranges.clear()
        for index, (subtab, label) in enumerate(_SUBTAB_LABELS):
            if index:
                text.append(" │ ", style="#444444")
            start = len(text.plain)
            if subtab == self._active_subtab:
                text.append(
                    f" {label.upper()} ",
                    style=f"bold reverse {_SUBTAB_COLORS[subtab]}",
                )
            else:
                text.append(label, style="dim")
            self._subtab_ranges[subtab] = (start, len(text.plain))
        self._line_width = len(text.plain)
        return text

    def on_click(self, event: Click) -> None:
        content_width = max(0, int(self.size.width))
        center_pad = max(0, (content_width - self._line_width) // 2)
        x = event.x - center_pad
        for subtab, (start, end) in self._subtab_ranges.items():
            if start <= x < end:
                if subtab != self._active_subtab:
                    self.post_message(self.SubTabClicked(subtab))
                return


class OperationsPane(Vertical):
    """Nested Operations tab hosting Tasks and Logs sub-tabs."""

    can_focus = False

    BINDINGS = [
        ("tab", "next_operations_subtab", "Next Operations Tab"),
        ("shift+tab", "prev_operations_subtab", "Previous Operations Tab"),
    ]

    def __init__(
        self,
        *,
        initial_subtab: OperationsSubTab | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._initial_subtab = (
            initial_subtab if initial_subtab in _SUBTAB_ORDER else None
        )
        self._active_subtab: OperationsSubTab = self._initial_subtab or _DEFAULT_SUBTAB

    def compose(self) -> ComposeResult:
        yield _OperationsSubTabStrip(
            self._active_subtab,
            id="operations-subtabs",
        )
        with ContentSwitcher(initial=self._active_subtab, id="operations-switcher"):
            yield TasksPane(id="tasks")
            yield LogsPane(id="logs")

    def on_mount(self) -> None:
        requested = self._initial_subtab or self._remembered_subtab()
        self._switch_to(requested or _DEFAULT_SUBTAB, focus=False)
        self._remember_active_subtab()

    def _remembered_subtab(self) -> OperationsSubTab | None:
        remembered = getattr(self.app, "_operations_subtab", None)
        return remembered if remembered in _SUBTAB_ORDER else None

    def _remember_active_subtab(self) -> None:
        try:
            self.app._operations_subtab = self._active_subtab  # type: ignore[attr-defined]
        except Exception:
            pass

    def _active_pane(self) -> Widget | None:
        try:
            return self.query_one(f"#{self._active_subtab}", Widget)
        except Exception:
            return None

    def focus_default(self) -> None:
        """Focus the default control in the visible Operations sub-pane."""
        pane = self._active_pane()
        focus_default = getattr(pane, "focus_default", None)
        if callable(focus_default):
            focus_default()

    def is_subtab_active(self, pane: Widget) -> bool:
        """Return whether *pane* is the visible sub-pane on the active top tab."""
        try:
            outer_active = getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            outer_active = False
        return outer_active and pane.id == self._active_subtab

    def _switch_to(self, subtab: OperationsSubTab, *, focus: bool = True) -> None:
        if subtab not in _SUBTAB_ORDER:
            return
        changed = subtab != self._active_subtab
        self._active_subtab = subtab
        try:
            switcher = self.query_one("#operations-switcher", ContentSwitcher)
            switcher.current = subtab
        except Exception:
            return
        try:
            strip = self.query_one("#operations-subtabs", _OperationsSubTabStrip)
            strip.set_active_subtab(subtab)
        except Exception:
            pass
        self._remember_active_subtab()
        if focus and changed:
            self.focus_default()

    def action_next_operations_subtab(self) -> None:
        """Switch to the next Operations sub-tab."""
        index = _SUBTAB_ORDER.index(self._active_subtab)
        self._switch_to(_SUBTAB_ORDER[(index + 1) % len(_SUBTAB_ORDER)])

    def action_prev_operations_subtab(self) -> None:
        """Switch to the previous Operations sub-tab."""
        index = _SUBTAB_ORDER.index(self._active_subtab)
        self._switch_to(_SUBTAB_ORDER[(index - 1) % len(_SUBTAB_ORDER)])

    def action_scroll_to_top(self) -> None:
        """Forward top-scroll to the active sub-pane."""
        pane = self._active_pane()
        scroll_to_top = getattr(pane, "action_scroll_to_top", None)
        if callable(scroll_to_top):
            scroll_to_top()

    def action_scroll_to_bottom(self) -> None:
        """Forward bottom-scroll to the active sub-pane."""
        pane = self._active_pane()
        scroll_to_bottom = getattr(pane, "action_scroll_to_bottom", None)
        if callable(scroll_to_bottom):
            scroll_to_bottom()

    @on(_OperationsSubTabStrip.SubTabClicked)
    def _on_subtab_clicked(self, event: _OperationsSubTabStrip.SubTabClicked) -> None:
        """Handle mouse selection of an Operations sub-tab."""
        event.stop()
        self._switch_to(event.subtab)


__all__ = [
    "OperationsPane",
    "OperationsSubTab",
    "_OperationsSubTabStrip",
]
