"""One-line Inbox nav item for the dismissed-agent Archive."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.events import Blur, Click, Key
from textual.widgets import Static

from ..models.agent_archive_controller import ArchiveShelfSnapshot


class AgentArchiveShelf(Static):
    """Focusable, clickable shelf docked beneath the Inbox node list."""

    can_focus = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(Text(""), **kwargs)
        self._snapshot = ArchiveShelfSnapshot()
        self._inbox_empty = False

    def set_snapshot(
        self,
        snapshot: ArchiveShelfSnapshot,
        *,
        inbox_empty: bool,
    ) -> None:
        was_displayed = self.display
        self._snapshot = snapshot
        self._inbox_empty = inbox_empty
        self.display = bool(
            snapshot.status in {"ready", "unanswerable"} and snapshot.total
        )
        self.set_class(self.display, "-visible")
        self.set_class(bool(inbox_empty), "-empty")
        self._paint()
        if was_displayed != self.display and self.is_mounted:
            reapply = getattr(self.app, "_reapply_panel_heights", None)
            if callable(reapply):
                self.app.call_after_refresh(reapply)

    def _paint(self) -> None:
        snapshot = self._snapshot
        if snapshot.status not in {"ready", "unanswerable"} or snapshot.total <= 0:
            self.update(Text(""))
            return
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append("◷ Archive", style="bold #d7af5f")
        if snapshot.query.strip():
            if snapshot.status == "unanswerable":
                text.append(" · can't answer this filter", style="dim")
                text.append(" · ⏎ browse", style="bold #d7af5f")
            else:
                count = int(snapshot.matching or 0)
                verb = "matches" if count == 1 else "match"
                text.append(f" · {count:,} {verb} this filter", style="dim")
                text.append(" · ⏎ search", style="bold #d7af5f")
        else:
            text.append(
                f" · {snapshot.total:,} runs · {snapshot.today:,} today", style="dim"
            )
        self.update(text)

    def on_click(self, event: Click) -> None:
        if not self.display:
            return
        event.stop()
        self.app._agent_archive_shelf_focused = True  # type: ignore[attr-defined]
        self.add_class("-focused")
        self._open_archive()

    def on_blur(self, event: Blur) -> None:
        del event
        from ..actions.agents._archive_shelf import clear_archive_shelf_focus

        self.remove_class("-focused")
        clear_archive_shelf_focus(self.app)

    def on_key(self, event: Key) -> None:
        if event.key not in {"enter", "l", "space"} or not self.display:
            return
        event.prevent_default()
        event.stop()
        self._open_archive()

    def _open_archive(self) -> None:
        activate = getattr(self.app, "_activate_agents_archive_shelf", None)
        if callable(activate):
            activate()


__all__ = ["AgentArchiveShelf"]
