"""Selection, stable-target navigation, and detail behavior for Beads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.keymaps import KeymapRegistry
from sase.bead.flag_fields import is_flag_bead
from sase.bead.model import Issue, IssueType, Status
from sase.core.artifact_relation_layout import RelationKeymap

from ...models.group_fold import GroupFoldRegistry, GroupKey
from .._prompt_preview_target import PreviewPayload
from .beads_data import BeadsSnapshot
from .beads_data_models import ProjectBead
from .beads_data_sources import (
    _hierarchical_id_key,
    _project_beads_dir,
    _resolve_projects,
)
from .beads_detail import (
    bead_body_markdown,
    bead_preview_markdown,
    bead_properties_header,
    resolved_plan_path,
)
from .beads_list import BeadRow, BeadRowKind, bead_row_target, row_option_id
from .entry_navigation import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    HydrationOutcome,
    HydrationResult,
    LinkRequestState,
    prewarm_option_render_cache,
    reveal_option_list_highlight,
    schedule_option_list_highlight_reveal,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from .beads_data_models import ExternalIssueLink
else:
    _MixinBase = ArtifactEntryNavigator


class BeadsOptionList(OptionList):
    """Bead rows whose guarded highlights retain viewport following."""

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


class BeadsNavigationMixin(_MixinBase):
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

    if TYPE_CHECKING:

        def _empty_detail(self) -> str: ...

        def _refresh_options(
            self,
            *,
            preferred_id: str | None = None,
            update_detail: bool = True,
        ) -> None: ...

        def refresh_relation_panel(self, *, refresh_footer: bool = True) -> Any: ...

        def relation_footer_entries(
            self, keymap: Any = None
        ) -> tuple[tuple[str, str], ...]: ...

        def external_links_for_row(
            self,
            row: BeadRow,
        ) -> tuple[ExternalIssueLink, ...]: ...

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
            footer_entries = BeadsNavigationMixin._conditional_footer_entries(
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
            self._refresh_options()
        return LinkRequestState.PENDING

    def clear_pending_entry_target(self) -> None:
        self._pending_entry_target = None
        self._pending_entry_generation = None

    def hydrate_ref(self, kind: str, payload: str) -> HydrationResult:
        """Resolve one bead by exact id, searching only the current scope.

        Scoping the store search to ``self.project_scope`` (one project, or
        every enabled project when unscoped) guarantees the resolved
        project is always compatible with the current snapshot, so the
        merge in :meth:`install_hydrated_row` never has to reconcile a
        foreign project scope.
        """
        if kind != "bead":
            return HydrationResult(HydrationOutcome.UNSUPPORTED)
        from sase.core.bead_read_facade import resolve_id, show

        found: tuple[str, Issue] | None = None
        for item in _resolve_projects(self.project_scope):
            beads_dir = _project_beads_dir(item.project)
            if beads_dir is None:
                continue
            try:
                full_id = resolve_id(beads_dir, payload)
                issue = show(beads_dir, full_id)
            except KeyError:
                continue
            except Exception as exc:  # noqa: BLE001 - reported as FAILED below
                return HydrationResult(HydrationOutcome.FAILED, error=str(exc))
            found = (item.project, issue)
            break
        if found is None:
            return HydrationResult(HydrationOutcome.ABSENT)
        project, issue = found
        parent_epic: Issue | None = None
        if issue.issue_type is IssueType.PHASE and issue.parent_id:
            beads_dir = _project_beads_dir(project)
            if beads_dir is not None:
                try:
                    parent_epic = show(beads_dir, issue.parent_id)
                except KeyError:
                    parent_epic = None
                except Exception as exc:  # noqa: BLE001 - reported as FAILED below
                    return HydrationResult(HydrationOutcome.FAILED, error=str(exc))
        return HydrationResult(
            HydrationOutcome.FETCHED, payload=(project, issue, parent_epic)
        )

    def install_hydrated_row(self, payload: Any) -> ArtifactEntryTarget | None:
        """Merge one fetched bead (plus its parent epic, if needed) in.

        Leaves rebuilding ``_rows``/options to the request that follows:
        the coordinator immediately re-requests the returned target, whose
        ``request_entry_target`` miss path already calls
        ``_refresh_options()`` with ``_pending_entry_target`` set, which
        expands the owning epic fold for a phase for free.
        """
        if not isinstance(payload, tuple) or len(payload) != 3:
            return None
        project, issue, parent_epic = payload
        snapshot = self._snapshot
        if snapshot is None:
            return None
        if parent_epic is not None and not any(
            bead.project == project and bead.issue.id == parent_epic.id
            for bead in snapshot.epics
        ):
            snapshot = _merge_bead_into_snapshot(snapshot, project, parent_epic)
        self._snapshot = _merge_bead_into_snapshot(snapshot, project, issue)
        return ArtifactEntryTarget("beads", (project, _bead_row_kind(issue), issue.id))

    def conditional_footer_entries(self) -> tuple[tuple[str, str], ...]:
        row = self.selected_row()
        refresh_relation_panel = getattr(self, "refresh_relation_panel", None)
        keymap = getattr(
            getattr(self, "app", None),
            "_relation_footer_keymap_override",
            None,
        )
        if row is None:
            if keymap is None and callable(refresh_relation_panel):
                refresh_relation_panel(refresh_footer=False)
            return ()
        if keymap is None:
            keymap = (
                refresh_relation_panel(refresh_footer=False)
                if callable(refresh_relation_panel)
                else None
            )
        return BeadsNavigationMixin._conditional_footer_entries(self, keymap)

    def _conditional_footer_entries(
        self,
        keymap: Any = None,
    ) -> tuple[tuple[str, str], ...]:
        row = self.selected_row()
        if row is None:
            return ()
        entries: list[tuple[str, str]] = []
        snapshot = self._snapshot
        if _can_launch_bead_row(row, snapshot):
            entries.append(("beads_launch_work", "launch"))
        entries.append(
            (
                "beads_close",
                "reopen" if row.issue.status is Status.CLOSED else "close",
            )
        )
        if _bead_row_is_snoozable(row):
            entries.append(
                (
                    "beads_snooze",
                    "re-snooze" if row.issue.status is Status.SNOOZED else "snooze",
                )
            )
        external_links_for_row = getattr(self, "external_links_for_row", None)
        if callable(external_links_for_row) and external_links_for_row(row):
            entries.append(("beads_open_bug", "open issue"))
        entries.append(("start_bead_issue_mode", "issue"))
        relation_footer_entries = getattr(self, "relation_footer_entries", None)
        if callable(relation_footer_entries):
            entries.extend(relation_footer_entries(keymap))
        return tuple(entries)

    def _sync_artifacts_footer_if_changed(
        self,
        footer_entries: tuple[tuple[str, str], ...],
        keymap: RelationKeymap,
    ) -> None:
        if self._conditional_footer_signature == footer_entries:
            return
        self._conditional_footer_signature = footer_entries
        if not getattr(self, "artifacts_active", False):
            return
        app = getattr(self, "app", None)
        sync = getattr(app, "_sync_active_artifacts_entry_state", None)
        if app is None or not callable(sync):
            return
        attr = "_relation_footer_keymap_override"
        had_previous = hasattr(app, attr)
        previous = getattr(app, attr, None)
        setattr(app, attr, keymap)
        try:
            sync()
        finally:
            if had_previous:
                setattr(app, attr, previous)
            else:
                delattr(app, attr)

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

    def preview_for_row(self, row: BeadRow) -> PreviewPayload:
        issue = row.issue
        return PreviewPayload(
            content=bead_preview_markdown(
                issue,
                self._snapshot,
                project=row.project,
                registry=self._registry,
                external_links=self.external_links_for_row(row),
            ),
            lexer="markdown",
            title=f"{issue.id} · {issue.title}",
            kind_label=f"{row.kind} bead",
            icon="◈",
            source_path=resolved_plan_path(
                issue,
                self._snapshot,
                project=row.project,
            ),
            reference=issue.design.strip() or None,
            default_view="rendered",
        )

    def selected_preview(self) -> PreviewPayload | None:
        row = self.selected_row()
        return None if row is None else self.preview_for_row(row)

    def _update_detail(self) -> None:
        try:
            properties = self.query_one("#beads-detail-properties", Static)
            body = self.query_one("#beads-detail", Markdown)
        except Exception:
            return
        row = self.selected_row()
        if row is None:
            properties.display = False
            properties.update("")
            body.update(self._empty_detail())
            self.refresh_relation_panel()
            return
        properties.display = True
        properties.update(
            bead_properties_header(
                row.issue,
                self._snapshot,
                project=row.project,
                project_name=self._project_name(row.project),
                external_links=self.external_links_for_row(row),
            )
        )
        triage = (
            None
            if self._snapshot is None
            else self._snapshot.triage_gates.get((row.project, row.issue.id))
        )
        body.update(
            bead_body_markdown(
                row.issue,
                triage,
                registry=self._registry,
                external_links=self.external_links_for_row(row),
            )
        )
        self.refresh_relation_panel()

    def _project_name(self, project: str) -> str:
        if self._snapshot is None:
            return project
        return self._snapshot.display_names.get(project, project)

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


def _can_launch_bead_row(
    row: BeadRow,
    snapshot: BeadsSnapshot | None,
) -> bool:
    issue = row.issue
    if issue.status is Status.CLOSED:
        return False
    if issue.issue_type is IssueType.PHASE:
        return False
    if issue.issue_type is IssueType.TASK:
        return issue.status in {Status.OPEN, Status.READY}
    if snapshot is None:
        return False
    key = (row.project, issue.id)
    return bool(snapshot.phases_by_epic.get(key)) and key not in snapshot.blocked_ids


def _bead_row_is_snoozable(row: BeadRow) -> bool:
    """Return whether *row* is a task bead the store would let us snooze."""
    return row.issue.issue_type is IssueType.TASK and row.issue.status in {
        Status.OPEN,
        Status.READY,
        Status.SNOOZED,
    }


def _bead_row_kind(issue: Issue) -> BeadRowKind:
    if issue.issue_type is IssueType.PLAN:
        return "epic"
    if issue.issue_type is IssueType.PHASE:
        return "phase"
    if is_flag_bead(issue):
        return "flag"
    return "task"


def _merge_bead_into_snapshot(
    snapshot: BeadsSnapshot,
    project: str,
    issue: Issue,
) -> BeadsSnapshot:
    """Append one hydrated bead into *snapshot*, preserving phase grouping."""
    from dataclasses import replace as _replace

    if issue.issue_type is IssueType.PLAN:
        if any(
            bead.project == project and bead.issue.id == issue.id
            for bead in snapshot.epics
        ):
            return snapshot
        epics = (*snapshot.epics, ProjectBead(project, issue))
        key = (project, issue.id)
        phases_by_epic = snapshot.phases_by_epic
        if key not in phases_by_epic:
            phases_by_epic = {**phases_by_epic, key: ()}
        return _replace(snapshot, epics=epics, phases_by_epic=phases_by_epic)
    if issue.issue_type is IssueType.PHASE:
        if not issue.parent_id:
            return snapshot  # an orphan phase has no epic to group under
        key = (project, issue.parent_id)
        existing = snapshot.phases_by_epic.get(key, ())
        if any(bead.issue.id == issue.id for bead in existing):
            return snapshot
        phases = tuple(
            sorted(
                (*existing, ProjectBead(project, issue)),
                key=lambda bead: _hierarchical_id_key(bead.issue.id),
            )
        )
        phases_by_epic = {**snapshot.phases_by_epic, key: phases}
        return _replace(snapshot, phases_by_epic=phases_by_epic)
    if is_flag_bead(issue):
        if any(
            bead.project == project and bead.issue.id == issue.id
            for bead in snapshot.flags
        ):
            return snapshot
        return _replace(snapshot, flags=(*snapshot.flags, ProjectBead(project, issue)))
    if any(
        bead.project == project and bead.issue.id == issue.id for bead in snapshot.tasks
    ):
        return snapshot
    return _replace(snapshot, tasks=(*snapshot.tasks, ProjectBead(project, issue)))


__all__ = ["BeadsNavigationMixin", "BeadsOptionList"]
