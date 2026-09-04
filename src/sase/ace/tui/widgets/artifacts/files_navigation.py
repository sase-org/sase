"""Guarded selection and shared entry navigation for artifact-file rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from textual.widgets import OptionList
from textual.widgets.option_list import Option

from .entry_navigation import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    LinkRequestState,
    prewarm_option_render_cache,
    reveal_option_list_highlight,
)
from .files_list import FileRow, file_row_target

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = ArtifactEntryNavigator


class FilesOptionList(OptionList):
    """File rows whose guarded highlights retain native viewport following."""

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
            prewarm_option_render_cache(self)
        finally:
            self._programmatic_update = False

    def _assign_highlight(self, index: int | None) -> None:
        self.highlighted = index
        reveal_option_list_highlight(self)

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._programmatic_update:
            return
        super().watch_highlighted(highlighted)


class FilesNavigationMixin(_MixinBase):
    """Own file selection and the shared Artifacts entry contract."""

    _rows: dict[str, FileRow]
    _syncing_options: bool
    _entry_jump_hints: dict[ArtifactEntryTarget, str]
    _entry_marks: set[ArtifactEntryTarget]
    _entry_targets_cache: tuple[ArtifactEntryTarget, ...]
    _entry_target_index_by_target: dict[ArtifactEntryTarget, int]
    _option_id_by_target: dict[ArtifactEntryTarget, str]
    _option_index_by_target: dict[ArtifactEntryTarget, int]
    _banner_target_by_option_id: dict[str, ArtifactEntryTarget]
    _pending_entry_target: ArtifactEntryTarget | None
    _pending_entry_generation: int | None

    if TYPE_CHECKING:

        def _refresh_options(
            self,
            *,
            preferred_target: ArtifactEntryTarget | None = None,
        ) -> None: ...

        def refresh_relation_panel(self, *, refresh_footer: bool = True) -> Any: ...

        def relation_footer_entries(
            self, keymap: Any = None
        ) -> tuple[tuple[str, str], ...]: ...

        def _complete_entry_request(
            self, state: LinkRequestState
        ) -> LinkRequestState: ...

    def _init_files_navigation(self) -> None:
        self._rows = {}
        self._syncing_options = False
        self._entry_jump_hints = {}
        self._entry_marks = set()
        self._entry_targets_cache = ()
        self._entry_target_index_by_target = {}
        self._option_id_by_target = {}
        self._option_index_by_target = {}
        self._banner_target_by_option_id = {}
        self._pending_entry_target = None
        self._pending_entry_generation = None

    def _set_file_rows(
        self,
        rows: dict[str, FileRow],
        options: list[Option],
        banner_targets: dict[str, ArtifactEntryTarget] | None = None,
    ) -> None:
        self._rows = rows
        self._banner_target_by_option_id = dict(banner_targets or {})
        target_by_option_id: dict[str, ArtifactEntryTarget] = {
            option_id: file_row_target(row) for option_id, row in rows.items()
        }
        target_by_option_id.update(self._banner_target_by_option_id)
        # Expanded banners render as disabled headers — visible, but not a
        # navigation/jump stop, mirroring Patches (only collapsed banners
        # are stops; real rows are never disabled).
        indexed_targets = tuple(
            (index, target)
            for index, option in enumerate(options)
            if not option.disabled
            and (target := target_by_option_id.get(option.id or "")) is not None
        )
        self._entry_targets_cache = tuple(target for _index, target in indexed_targets)
        self._entry_target_index_by_target = {
            target: target_index
            for target_index, (_option_index, target) in enumerate(indexed_targets)
        }
        self._option_index_by_target = {
            target: index for index, target in indexed_targets
        }
        self._option_id_by_target = {
            target: option.id or ""
            for index, target in indexed_targets
            if (option := options[index]).id is not None
        }

    def selected_row(self) -> FileRow | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        return self._rows.get(option.id or "")

    def selected_group_banner_target(self) -> ArtifactEntryTarget | None:
        """Return the highlighted banner's target, or ``None`` for a real row."""
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        return self._banner_target_by_option_id.get(option.id or "")

    def focus_list(self) -> None:
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()
            prewarm_option_render_cache(option_list)

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
        return self._entry_targets_cache

    def entry_target_index(self, target: ArtifactEntryTarget) -> int | None:
        return self._entry_target_index_by_target.get(target)

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        row = self.selected_row()
        if row is not None:
            return file_row_target(row)
        return self.selected_group_banner_target()

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        option_list = self._option_list()
        target_index = self._option_index_by_target.get(target)
        if option_list is None or target_index is None:
            return False
        option_list.focus()
        self._syncing_options = True
        try:
            option_list.set_highlight(target_index)
        finally:
            self._syncing_options = False
        return True

    def request_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        if self.select_entry_target(target):
            self._pending_entry_generation = generation
            return self._complete_entry_request(LinkRequestState.SELECTED)
        self._pending_entry_target = target
        self._pending_entry_generation = generation
        if self._current_snapshot() is not None:  # type: ignore[attr-defined]
            self._refresh_options()  # type: ignore[attr-defined]
        return LinkRequestState.PENDING

    def clear_pending_entry_target(self) -> None:
        self._pending_entry_target = None
        self._pending_entry_generation = None

    def conditional_footer_entries(self) -> tuple[tuple[str, str], ...]:
        keymap = getattr(
            getattr(self, "app", None),
            "_relation_footer_keymap_override",
            None,
        )
        if keymap is not None:
            return self.relation_footer_entries(keymap)
        return self.relation_footer_entries(
            self.refresh_relation_panel(refresh_footer=False)
        )

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
        self._refresh_options(preferred_target=preferred)

    def _option_list(self) -> FilesOptionList | None:
        try:
            return self.query_one("#files-list", FilesOptionList)
        except Exception:
            return None

    def _option_index_for_target(
        self,
        target: ArtifactEntryTarget | None,
    ) -> int | None:
        option_list = self._option_list()
        if option_list is None or target is None:
            return None
        return self._option_index_by_target.get(target)


__all__ = ["FilesNavigationMixin", "FilesOptionList"]
