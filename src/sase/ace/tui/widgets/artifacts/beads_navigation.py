"""Selection, stable-target navigation, and epic fold behavior for Beads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sase.ace.tui.keymaps import KeymapRegistry
from sase.ace.tui.util.debounce import DetailPanelDebouncer

from ...models.group_fold import GroupFoldRegistry, GroupKey
from .beads_data import BeadsSnapshot
from .beads_list import BeadRow, bead_row_target, row_option_id
from .beads_navigation_detail import BeadsNavigationDetailMixin
from .beads_navigation_hydration import BeadsNavigationHydrationMixin
from .beads_option_list import BeadsOptionList
from .entry_navigation import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    LinkRequestState,
    prewarm_option_render_cache,
    schedule_option_list_highlight_reveal,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
    from textual.widgets.option_list import Option
else:
    _MixinBase = ArtifactEntryNavigator


class BeadsNavigationMixin(
    BeadsNavigationHydrationMixin, BeadsNavigationDetailMixin, _MixinBase
):
    """Own bead selection, jump targets, expansion, and detail content."""

    project_scope: str | None
    _registry: KeymapRegistry
    _snapshot: BeadsSnapshot | None
    _rows: dict[str, BeadRow]
    _epic_fold_registry: GroupFoldRegistry
    _known_epic_keys: set[GroupKey]
    _detail_debouncer: DetailPanelDebouncer | None
    _syncing_options: bool
    _entry_jump_hints: dict[ArtifactEntryTarget, str]
    _entry_marks: set[ArtifactEntryTarget]
    _entry_targets_cache: tuple[ArtifactEntryTarget, ...]
    _entry_target_index_by_target: dict[ArtifactEntryTarget, int]
    _option_index_by_target: dict[ArtifactEntryTarget, int]
    _conditional_footer_signature: tuple[tuple[str, str], ...] | None
    _pending_entry_target: ArtifactEntryTarget | None
    _pending_entry_generation: int | None
    _query_profile: Any
    _query_index: Any
    _filter_index: Any
    _filter_index_source_key: Any
    _query_session: Any
    _load_generation: int

    if TYPE_CHECKING:

        def _refresh_options(
            self,
            *,
            preferred_id: str | None = None,
            update_detail: bool = True,
        ) -> None: ...

        def _expand_parent_for_target(self, target: ArtifactEntryTarget) -> bool: ...

        def _refresh_for_entry_request(self, refresh: Any) -> LinkRequestState: ...

        def _complete_entry_request(
            self, state: LinkRequestState
        ) -> LinkRequestState: ...

    def _init_beads_navigation(self) -> None:
        self._rows = {}
        self._epic_fold_registry = GroupFoldRegistry()
        self._known_epic_keys = set()
        self._detail_debouncer = None
        self._syncing_options = False
        self._entry_jump_hints = {}
        self._entry_marks = set()
        self._entry_targets_cache = ()
        self._entry_target_index_by_target = {}
        self._option_index_by_target = {}
        self._conditional_footer_signature = None
        self._pending_entry_target = None
        self._pending_entry_generation = None

    def _set_bead_rows(
        self,
        rows: dict[str, BeadRow],
        options: list[Option],
    ) -> None:
        """Install rows and their stable-target indexes in visual order."""
        self._rows = rows
        indexed_targets = tuple(
            (index, bead_row_target(row))
            for index, option in enumerate(options)
            if (row := rows.get(option.id or "")) is not None
        )
        self._entry_targets_cache = tuple(target for _index, target in indexed_targets)
        self._entry_target_index_by_target = {
            target: target_index
            for target_index, (_option_index, target) in enumerate(indexed_targets)
        }
        self._option_index_by_target = {
            target: index for index, target in indexed_targets
        }

    def selected_row(self) -> BeadRow | None:
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
            prewarm_option_render_cache(option_list)

    def move_selection(self, step: int) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        option_list.focus()
        if step > 0:
            option_list.action_cursor_down()
        else:
            option_list.action_cursor_up()

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return self._entry_targets_cache

    def entry_target_index(self, target: ArtifactEntryTarget) -> int | None:
        return self._entry_target_index_by_target.get(target)

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        row = self.selected_row()
        return None if row is None else bead_row_target(row)

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        option_list = self._option_list()
        target_index = self._option_index_for_target(target)
        if option_list is None or target_index is None:
            return False
        changed = option_list.highlighted != target_index
        relation_panel = None
        if changed:
            relation_panel_getter = getattr(self, "relation_panel", None)
            if callable(relation_panel_getter):
                relation_panel = relation_panel_getter()
        had_relation_panel = bool(getattr(relation_panel, "display", False))
        option_list.focus()
        self._syncing_options = True
        try:
            option_list.set_highlight(target_index)
        finally:
            self._syncing_options = False
        if changed:
            if self._detail_debouncer is None:
                self._update_detail()
            else:
                self._detail_debouncer.schedule(self._update_detail)
            keymap = self.refresh_relation_panel(refresh_footer=False)
            footer_entries = BeadsNavigationDetailMixin._conditional_footer_entries(
                self, keymap
            )
            has_relation_panel = bool(getattr(relation_panel, "display", False))
            self._sync_artifacts_footer_if_changed(footer_entries, keymap)
            schedule_option_list_highlight_reveal(
                option_list,
                allow_future_growth=has_relation_panel and not had_relation_panel,
            )
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
        if self._snapshot is not None and self._snapshot.project == self.project_scope:
            return self._refresh_for_entry_request(self._refresh_options)
        return LinkRequestState.PENDING

    def clear_pending_entry_target(self) -> None:
        self._pending_entry_target = None
        self._pending_entry_generation = None

    def expand_fold_for_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Expand the epic fold hiding a pending phase target."""
        expanded = self._expand_parent_for_target(target)
        if not expanded and (
            target.pane_id == "beads"
            and len(target.parts) >= 3
            and target.parts[1] == "epic"
        ):
            key = (target.parts[0], target.parts[2])
            expanded = self._epic_fold_registry.expand(key)
        if not expanded:
            return False
        self._refresh_options()
        return True

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        self._entry_jump_hints = dict(hints)
        self._refresh_options(update_detail=False)

    def clear_entry_jump_hints(self) -> None:
        if not self._entry_jump_hints:
            return
        self._entry_jump_hints = {}
        self._refresh_options(update_detail=False)

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        self._entry_marks = set(marks)
        self._refresh_options(update_detail=False)

    def _sync_artifacts_footer(self) -> None:
        if not getattr(self, "artifacts_active", False):
            return
        sync = getattr(self.app, "_sync_active_artifacts_entry_state", None)
        if callable(sync):
            sync()

    def _option_index_for_target(self, target: ArtifactEntryTarget) -> int | None:
        return self._option_index_by_target.get(target)

    def _seed_new_epic_keys(self) -> None:
        """Default newly-seen epics to collapsed, without touching known ones.

        Called once per options refresh so a first-loaded epic starts
        collapsed while an epic the user already toggled keeps its state
        across refreshes.  Also prunes fold state for epics that dropped out
        of the snapshot entirely, so long sessions don't accumulate stale
        collapsed entries as epics close and age out.
        """
        snapshot = self._snapshot
        if snapshot is None:
            return
        known_now: set[GroupKey] = set()
        for item in snapshot.epics:
            key: GroupKey = (item.project, item.issue.id)
            known_now.add(key)
            if key not in self._known_epic_keys:
                self._known_epic_keys.add(key)
                self._epic_fold_registry.collapse(key)
        self._epic_fold_registry.clear_unknown(known_now)
        self._known_epic_keys &= known_now

    def _expanded_epic_keys(self) -> set[tuple[str, str]]:
        snapshot = self._snapshot
        if snapshot is None:
            return set()
        return {
            (item.project, item.issue.id)
            for item in snapshot.epics
            if not self._epic_fold_registry.is_collapsed((item.project, item.issue.id))
        }

    def set_selected_epic_expanded(self, expanded: bool) -> None:
        row = self.selected_row()
        if row is None:
            return
        epic_id = row.issue.id if row.kind == "epic" else row.issue.parent_id
        if epic_id is None:
            return
        cancel_jump = getattr(
            self.app, "_cancel_artifacts_jump_mode_for_model_change", None
        )
        if callable(cancel_jump):
            cancel_jump("beads")
        key: GroupKey = (row.project, epic_id)
        changed = (
            self._epic_fold_registry.expand(key)
            if expanded
            else self._epic_fold_registry.collapse(key)
        )
        if not changed:
            return
        preferred_id = (
            None
            if self._snapshot is None
            else row_option_id(self._snapshot, "epic", row.project, epic_id)
        )
        self._refresh_options(preferred_id=preferred_id)

    def _option_list(self) -> BeadsOptionList | None:
        try:
            return self.query_one("#beads-list", BeadsOptionList)
        except Exception:
            return None

    def _selected_option_id(self) -> str | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            return option_list.get_option_at_index(option_list.highlighted).id
        except Exception:
            return None

    def _option_index(self, option_id: str | None) -> int | None:
        if option_id is None:
            return None
        option_list = self._option_list()
        if option_list is None:
            return None
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == option_id:
                return index
        if option_id.startswith("phase:"):
            row = self._rows.get(option_id)
            if row is not None and row.issue.parent_id and self._snapshot is not None:
                return self._option_index(
                    row_option_id(
                        self._snapshot,
                        "epic",
                        row.project,
                        row.issue.parent_id,
                    )
                )
        return None


__all__ = [
    "BeadsNavigationDetailMixin",
    "BeadsNavigationHydrationMixin",
    "BeadsNavigationMixin",
    "BeadsOptionList",
]
