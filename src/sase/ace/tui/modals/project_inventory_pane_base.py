"""Shared cached-list mechanics for the read-only inventory panes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.keymaps import (
    ProjectsPaneKeymaps,
    build_projects_inventory_bindings,
    load_keymap_registry,
    split_key_alternatives,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import (
    ProgrammaticSelectionGuard,
    restore_selection_by_identity,
)
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name

from ..actions.navigation.jump_hints import normalize_jump_key
from .base import OptionListNavigationMixin
from .config_center_session import SelectionBookmark
from .pane_entry_jump import PaneEntryJumpMixin, apply_jump_hint_prefix
from .project_inventory_loading import InventoryLoadMixin
from .project_inventory_types import InventoryFilterInput, InventoryIssue

if TYPE_CHECKING:
    from .project_inventory_panes import RepoInventoryPane, WorkspaceInventoryPane


class InventoryProjectFilterRequested(Message):
    """Request that the host open its shared project picker for *pane*."""

    def __init__(
        self,
        pane: RepoInventoryPane | WorkspaceInventoryPane,
    ) -> None:
        super().__init__()
        self.pane = pane


class InventoryPaneBase[RecordT, IssueT: InventoryIssue](
    PaneEntryJumpMixin,
    OptionListNavigationMixin,
    InventoryLoadMixin[RecordT, IssueT],
    Vertical,
):
    """Shared cached-list mechanics for the two read-only inventory panes."""

    _prefix: str
    _option_list_id: str
    BINDINGS = []

    def __init__(
        self,
        *,
        projects_root: Path | None,
        project_records: Sequence[ProjectRecordWire],
        bookmark: SelectionBookmark | None = None,
        project_filter: str | None = None,
        on_project_filter_changed: Callable[[str | None], None] | None = None,
        keymaps: ProjectsPaneKeymaps | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._keymaps = keymaps or load_keymap_registry({}).projects
        self._bindings = BindingsMap(build_projects_inventory_bindings(self._keymaps))
        self._init_inventory_load_state()
        self._projects_root = projects_root
        self._bookmark = bookmark or SelectionBookmark()
        self._on_project_filter_changed = on_project_filter_changed
        self._project_states: dict[str, str] = {}
        self._project_names: dict[str, str] = {}
        self._scoped_records: list[RecordT] = []
        self._filtered_records: list[RecordT] = []
        self._project_filter: str | None = project_filter
        self._text_filter = ""
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._selection_guard = ProgrammaticSelectionGuard()
        self.set_project_records(project_records, refresh=False)

    def compose(self) -> ComposeResult:
        yield Static(self._summary_text(), id=f"{self._prefix}-summary")
        yield InventoryFilterInput(
            placeholder=f"Type to filter {self._prefix}…",
            id=f"{self._prefix}-filter",
        )
        list_box = Vertical(id=f"{self._prefix}-box")
        list_box.border_title = self._prefix.title()
        with list_box:
            yield Static(self._column_header_text(), id=f"{self._prefix}-columns")
            yield OptionList(id=self._option_list_id)
        detail_box = VerticalScroll(id=f"{self._prefix}-detail-scroll")
        detail_box.border_title = "Details"
        with detail_box:
            yield Static("", id=f"{self._prefix}-detail")
        yield Static(self._hints_text(), id=f"{self._prefix}-hints")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_options()
        self._start_inventory_load()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        self._cancel_inventory_load()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "clear_project_filter":
            return bool(self._project_filter)
        return super().check_action(action, parameters)

    def set_project_records(
        self,
        records: Sequence[ProjectRecordWire],
        *,
        refresh: bool = True,
    ) -> None:
        """Refresh enabled/disabled metadata without touching cached rows."""

        self._project_states = {record.project_name: record.state for record in records}
        self._project_names = {
            record.project_name: effective_project_name(record) for record in records
        }
        if self._project_filter not in self._project_states:
            self._project_filter = None
            self._record_project_filter()
        self._apply_filters()
        if refresh:
            self._refresh_options()

    @property
    def project_filter(self) -> str | None:
        return self._project_filter

    def set_project_filter(self, project_key: str | None) -> None:
        """Apply a cached project scope, admitting disabled projects explicitly."""

        self._project_filter = (
            project_key if project_key in self._project_states else None
        )
        self._record_project_filter()
        self._apply_filters()
        self._refresh_options()

    def focus_default(self) -> None:
        try:
            self.query_one(f"#{self._option_list_id}", OptionList).focus()
        except Exception:
            pass

    def _apply_filters(self) -> None:
        previous_identities = [
            self._record_id(record) for record in self._filtered_records
        ]
        if self._project_filter is not None:
            scoped = [
                record
                for record in self._records
                if self._record_project_key(record) == self._project_filter
            ]
        else:
            scoped = [
                record for record in self._records if self._enabled_by_default(record)
            ]
        self._scoped_records = scoped
        needle = self._text_filter.casefold().strip()
        self._filtered_records = [
            record
            for record in scoped
            if not needle or needle in self._record_haystack(record).casefold()
        ]
        # Rule 5: a rebuilt row set can strand hints (and, when the rows are no
        # longer the same records, back-stack indices) from an active jump.
        self.invalidate_jump_hints(
            identities_changed=previous_identities
            != [self._record_id(record) for record in self._filtered_records],
            target_count=len(self._filtered_records),
        )

    def _create_options(self) -> list[Option]:
        if not self._filtered_records:
            if self._loading and not self._records:
                message = f"Loading {self._prefix} inventory…"
            elif self._text_filter.strip():
                message = f"No {self._prefix} match the current search"
            elif self._project_filter:
                message = "No inventory rows for the selected project"
            else:
                message = f"No registered {self._prefix}"
            return [Option(Text(message, style="dim"), id="empty")]
        return [
            Option(
                self._jump_decorated_label(index, record),
                id=self._record_id(record),
            )
            for index, record in enumerate(self._filtered_records)
        ]

    def _jump_decorated_label(self, index: int, record: RecordT) -> Text:
        label = self._record_label(record)
        hint = self.jump_hint_for(index)
        return label if hint is None else apply_jump_hint_prefix(label, hint)

    def _refresh_options(self, *, preferred_id: str | None = None) -> None:
        try:
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        current = preferred_id or self._selected_record_id() or self._bookmark.identity
        self._selection_guard.clear()
        selected_index: int | None = None
        option_list.clear_options()
        for option in self._create_options():
            option_list.add_option(option)
        if self._filtered_records:
            index = restore_selection_by_identity(
                self._filtered_records,
                prior_identity=current,
                prior_visual_row=self._bookmark.row,
                identity_fn=self._record_id,
            )
            identity = self._record_id(self._filtered_records[index])
            self._selection_guard.prepare(identity, index)
            option_list.highlighted = index
            selected_index = index
        else:
            option_list.highlighted = None
        self._record_bookmark(selected_index, authoritative=self._loaded_once)
        self._update_summary()
        self._update_detail()
        self._update_hints()

    def _record_bookmark(
        self, index: int | None, *, authoritative: bool = True
    ) -> None:
        if index is None or not (0 <= index < len(self._filtered_records)):
            if authoritative and not self._text_filter.strip():
                self._bookmark.record(None, None)
            elif not authoritative:
                self._bookmark.display(None, None)
            return
        identity = self._record_id(self._filtered_records[index])
        if authoritative:
            self._bookmark.record(identity, index)
        else:
            self._bookmark.display(identity, index)

    def _record_project_filter(self) -> None:
        if self._on_project_filter_changed is not None:
            self._on_project_filter_changed(self._project_filter)

    def _selected_record(self) -> RecordT | None:
        try:
            highlighted = self.query_one(
                f"#{self._option_list_id}", OptionList
            ).highlighted
        except Exception:
            return None
        if highlighted is None or not (0 <= highlighted < len(self._filtered_records)):
            return None
        return self._filtered_records[highlighted]

    def _selected_record_id(self) -> str | None:
        record = self._selected_record()
        return self._record_id(record) if record is not None else None

    def _project_label(self) -> str | None:
        if self._project_filter is None:
            return None
        return self._project_names.get(self._project_filter, self._project_filter)

    def _issues_for(self, record: RecordT | None) -> tuple[str, ...]:
        if record is None:
            return ()
        project = self._record_project(record)
        return tuple(
            issue.message for issue in self._issues if issue.project == project
        )

    def _update_summary(self) -> None:
        try:
            self.query_one(f"#{self._prefix}-summary", Static).update(
                self._summary_text()
            )
        except Exception:
            pass

    def _update_detail(self) -> None:
        try:
            self.query_one(f"#{self._prefix}-detail", Static).update(
                self._detail_text(self._selected_record())
            )
        except Exception:
            pass

    def _schedule_detail_update(self) -> None:
        if self._detail_debouncer is None:
            self._update_detail()
        else:
            self._detail_debouncer.schedule(self._update_detail)

    def _update_hints(self) -> None:
        try:
            self.query_one(f"#{self._prefix}-hints", Static).update(self._hints_text())
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != f"{self._prefix}-filter":
            return
        self._text_filter = event.value
        self._apply_filters()
        self._refresh_options()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.focus_default()

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        if event.option is None or event.option.id is None:
            return
        identity = str(event.option.id)
        try:
            highlighted = self.query_one(
                f"#{self._option_list_id}", OptionList
            ).highlighted
        except Exception:
            return
        if highlighted is None or not (0 <= highlighted < len(self._filtered_records)):
            return
        current_identity = self._record_id(self._filtered_records[highlighted])
        if identity != current_identity or self._selection_guard.should_ignore(
            identity,
            highlighted,
            current_identity=current_identity,
            current_row=highlighted,
        ):
            return
        self._record_bookmark(highlighted)
        self._schedule_detail_update()

    def on_key(self, event: events.Key) -> None:
        if self._filter_has_focus():
            return
        if self.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self.handle_jump_key(key):
                event.prevent_default()
                event.stop()
                return
        if event.key in split_key_alternatives(self._keymaps.jump_to_entry):
            event.stop()
            event.prevent_default()
            self.action_jump_to_entry()
        elif (
            event.key in split_key_alternatives(self._keymaps.clear_project_filter)
            and self._project_filter is not None
        ):
            event.stop()
            event.prevent_default()
            self.action_clear_project_filter()

    def _filter_has_focus(self) -> bool:
        try:
            return self.query_one(
                f"#{self._prefix}-filter", InventoryFilterInput
            ).has_focus
        except Exception:
            return False

    def _jump_target_count(self) -> int:
        return len(self._filtered_records)

    def _jump_current_index(self) -> int | None:
        try:
            highlighted = self.query_one(
                f"#{self._option_list_id}", OptionList
            ).highlighted
        except Exception:
            return None
        if highlighted is None or not (0 <= highlighted < len(self._filtered_records)):
            return None
        return highlighted

    def _jump_select_index(self, index: int) -> None:
        if not (0 <= index < len(self._filtered_records)):
            return
        self._refresh_options(
            preferred_id=self._record_id(self._filtered_records[index])
        )

    def _jump_repaint(self) -> None:
        self._refresh_options()

    def action_focus_filter(self) -> None:
        self.query_one(f"#{self._prefix}-filter", InventoryFilterInput).focus()

    def action_pick_project(self) -> None:
        self.post_message(
            InventoryProjectFilterRequested(
                cast("RepoInventoryPane | WorkspaceInventoryPane", self)
            )
        )

    def action_reload_inventory(self) -> None:
        self._start_inventory_load()

    def action_clear_project_filter(self) -> None:
        if self._project_filter is not None:
            self.set_project_filter(None)

    def _column_header_text(self) -> Text:
        raise NotImplementedError

    def _record_label(self, record: RecordT) -> Text:
        raise NotImplementedError

    def _summary_text(self) -> Text:
        raise NotImplementedError

    def _detail_text(self, record: RecordT | None) -> Text:
        raise NotImplementedError

    def _hints_text(self) -> str:
        raise NotImplementedError

    def _record_id(self, record: RecordT) -> str:
        raise NotImplementedError

    def _record_haystack(self, record: RecordT) -> str:
        raise NotImplementedError

    def _record_project(self, record: RecordT) -> str:
        raise NotImplementedError

    def _record_project_key(self, record: RecordT) -> str:
        raise NotImplementedError

    def _enabled_by_default(self, record: RecordT) -> bool:
        raise NotImplementedError


__all__ = [
    "InventoryPaneBase",
    "InventoryProjectFilterRequested",
]
