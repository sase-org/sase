"""Guarded selection and shared entry navigation for chat rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from textual.widgets import OptionList
from textual.widgets.option_list import Option

from .chats_list import ChatRow, chat_row_target
from .entry_navigation import ArtifactEntryTarget

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class ChatsOptionList(OptionList):
    """Chat rows whose guarded highlights retain native viewport following."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._programmatic_update = False

    def set_highlight(self, index: int | None) -> None:
        self._programmatic_update = True
        try:
            self._assign_highlight(index)
        finally:
            self._programmatic_update = False

    def replace_options(
        self,
        options: list[Option],
        *,
        highlighted: int | None,
    ) -> None:
        self._programmatic_update = True
        try:
            self.clear_options()
            self.add_options(options)
            self._assign_highlight(highlighted)
        finally:
            self._programmatic_update = False

    def _assign_highlight(self, index: int | None) -> None:
        self.highlighted = index
        self.scroll_to_highlight()

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._programmatic_update:
            return
        super().watch_highlighted(highlighted)


class ChatsNavigationMixin(_MixinBase):
    """Own chat selection and the shared Artifacts entry contract."""

    _rows: dict[str, ChatRow]
    _syncing_options: bool
    _entry_jump_hints: dict[ArtifactEntryTarget, str]
    _entry_marks: set[ArtifactEntryTarget]

    if TYPE_CHECKING:

        def _refresh_options(
            self,
            *,
            preferred_target: ArtifactEntryTarget | None = None,
            update_detail: bool = True,
        ) -> None: ...

    def _init_chats_navigation(self) -> None:
        self._rows = {}
        self._syncing_options = False
        self._entry_jump_hints = {}
        self._entry_marks = set()

    def selected_row(self) -> ChatRow | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        return self._rows.get(option.id or "")

    def focus_list(self) -> None:
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    def move_selection(self, offset: int) -> bool:
        option_list = self._option_list()
        if option_list is None:
            return False
        before = self.selected_entry_target()
        option_list.focus()
        if offset > 0:
            option_list.action_cursor_down()
        elif offset < 0:
            option_list.action_cursor_up()
        return self.selected_entry_target() != before

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        option_list = self._option_list()
        if option_list is None:
            return ()
        targets: list[ArtifactEntryTarget] = []
        for index in range(option_list.option_count):
            option_id = option_list.get_option_at_index(index).id or ""
            row = self._rows.get(option_id)
            if row is not None:
                targets.append(chat_row_target(row))
        return tuple(targets)

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        row = self.selected_row()
        return None if row is None else chat_row_target(row)

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        option_list = self._option_list()
        target_index = self._option_index_for_target(target)
        if option_list is None or target_index is None:
            return False
        option_list.focus()
        self._syncing_options = True
        try:
            option_list.set_highlight(target_index)
        finally:
            self._syncing_options = False
        return True

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        preferred = self.selected_entry_target()
        self._entry_jump_hints = dict(hints)
        self._refresh_options(preferred_target=preferred)

    def clear_entry_jump_hints(self) -> None:
        if not self._entry_jump_hints:
            return
        preferred = self.selected_entry_target()
        self._entry_jump_hints = {}
        self._refresh_options(preferred_target=preferred)

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        preferred = self.selected_entry_target()
        self._entry_marks = set(marks)
        self._refresh_options(preferred_target=preferred, update_detail=False)

    def _option_list(self) -> ChatsOptionList | None:
        try:
            return self.query_one("#chats-list", ChatsOptionList)
        except Exception:
            return None

    def _option_index_for_target(
        self,
        target: ArtifactEntryTarget | None,
    ) -> int | None:
        option_list = self._option_list()
        if option_list is None or target is None:
            return None
        for index in range(option_list.option_count):
            option_id = option_list.get_option_at_index(index).id or ""
            row = self._rows.get(option_id)
            if row is not None and chat_row_target(row) == target:
                return index
        return None


__all__ = ["ChatsNavigationMixin", "ChatsOptionList"]
