"""Archive column: the Inbox pulse above the Archive list."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import tzinfo
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical

from ...models.agent_archive_controller import ArchiveInboxPulse
from ...models.agent_archive_list import ArchiveListItem
from ...models.agent_archive_view import ARCHIVE_SECTION_PULSE
from ._list import ArchiveList
from ._pulse import ArchivePulse


class ArchiveColumn(Vertical):
    """Lazily mounted sibling of ``#agent-list-container``.

    State pushed before the children exist (the column is mounted and fed in
    one tick) is held and flushed on mount.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._children_ready = False
        self._pending: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield ArchivePulse(id="archive-pulse")
        yield ArchiveList(id="archive-list")

    @property
    def archive_list(self) -> ArchiveList:
        return self.query_one("#archive-list", ArchiveList)

    @property
    def archive_pulse(self) -> ArchivePulse:
        return self.query_one("#archive-pulse", ArchivePulse)

    def on_mount(self) -> None:
        self._children_ready = True
        pending, self._pending = self._pending, {}
        if "items" in pending:
            self.apply_items(**pending["items"])
        if "cursor" in pending:
            self.set_cursor(pending["cursor"])
        if "section" in pending:
            self.set_section(pending["section"])
        if "pulse" in pending:
            self.set_pulse(pending["pulse"])

    def apply_items(
        self,
        items: Sequence[ArchiveListItem],
        cursor_key: str | None,
        *,
        tz: tzinfo | None,
        grouping: str,
        restored_keys: Collection[str] = (),
    ) -> None:
        if not self._children_ready:
            self._pending["items"] = {
                "items": tuple(items),
                "cursor_key": cursor_key,
                "tz": tz,
                "grouping": grouping,
                "restored_keys": frozenset(restored_keys),
            }
            return
        self.archive_list.apply_items(
            items,
            cursor_key,
            tz=tz,
            grouping=grouping,
            restored_keys=restored_keys,
        )

    def set_cursor(self, key: str | None) -> None:
        if not self._children_ready:
            self._pending["cursor"] = key
            return
        self.archive_list.set_cursor(key)

    def reveal_cursor(self) -> None:
        """Keep the cursor row visible after the column was just shown."""
        if self._children_ready:
            self.archive_list.reveal_cursor()

    def set_section(self, section: str) -> None:
        """Mark the pulse selected (pulse focus) or the list active (list focus)."""
        if not self._children_ready:
            self._pending["section"] = section
            return
        on_pulse = section == ARCHIVE_SECTION_PULSE
        self.archive_pulse.set_selected(on_pulse)
        self.archive_list.set_class(on_pulse, "-dimmed")

    def set_pulse(self, pulse: ArchiveInboxPulse) -> None:
        if not self._children_ready:
            self._pending["pulse"] = pulse
            return
        self.archive_pulse.set_pulse(pulse)


__all__ = ["ArchiveColumn"]
