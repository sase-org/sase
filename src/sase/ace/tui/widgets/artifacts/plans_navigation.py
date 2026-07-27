"""Selection, entry navigation, and detail behavior for the plans pane."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer

from .._prompt_preview_target import PreviewPayload
from .entry_navigation import ArtifactEntryTarget
from .plans_data import PlansSnapshot
from .plans_detail import (
    archive_preview_markdown,
    archive_properties_header,
    bead_body_markdown,
    bead_preview_markdown,
    bead_properties_header,
    linked_plan_for_issue,
    proposal_properties_header,
    resolved_plan_path,
)
from .plans_list import PlanRow, plan_row_target, row_option_id

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class PlansOptionList(OptionList):
    """Plan rows whose guarded highlights retain native viewport following."""

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
        self, options: list[Option], *, highlighted: int | None
    ) -> None:
        """Replace rows and selection under one synchronous echo guard."""
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


class PlansNavigationMixin(_MixinBase):
    """Own plan selection, jump targets, expansion, and detail content."""

    project_scope: str | None
    _snapshot: PlansSnapshot | None
    _rows: dict[str, PlanRow]
    _expanded_epics: set[tuple[str, str]]
    _detail_debouncer: DetailPanelDebouncer | None
    _syncing_options: bool
    _entry_jump_hints: dict[ArtifactEntryTarget, str]

    if TYPE_CHECKING:

        def _empty_detail(self) -> str: ...

        def _refresh_options(
            self,
            *,
            preferred_id: str | None = None,
            update_detail: bool = True,
        ) -> None: ...

    def _init_plans_navigation(self) -> None:
        self._rows = {}
        self._expanded_epics = set()
        self._detail_debouncer = None
        self._syncing_options = False
        self._entry_jump_hints = {}

    def selected_row(self) -> PlanRow | None:
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
        option_list = self._option_list()
        if option_list is None:
            return ()
        targets: list[ArtifactEntryTarget] = []
        for index in range(option_list.option_count):
            option_id = option_list.get_option_at_index(index).id or ""
            row = self._rows.get(option_id)
            if row is not None:
                targets.append(plan_row_target(row))
        return tuple(targets)

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        row = self.selected_row()
        return None if row is None else plan_row_target(row)

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        option_list = self._option_list()
        target_index = self._option_index_for_target(target)
        if option_list is None or target_index is None:
            return False
        changed = option_list.highlighted != target_index
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

    def _option_index_for_target(self, target: ArtifactEntryTarget) -> int | None:
        option_list = self._option_list()
        if option_list is None:
            return None
        for index in range(option_list.option_count):
            option_id = option_list.get_option_at_index(index).id or ""
            row = self._rows.get(option_id)
            if row is not None and plan_row_target(row) == target:
                return index
        return None

    def set_selected_epic_expanded(self, expanded: bool) -> None:
        row = self.selected_row()
        if row is None or row.issue is None:
            return
        epic_id = row.issue.id if row.kind == "epic" else row.issue.parent_id
        if epic_id is None:
            return
        cancel_jump = getattr(
            self.app, "_cancel_artifacts_jump_mode_for_model_change", None
        )
        if callable(cancel_jump):
            cancel_jump("plans")
        epic_key = (row.project, epic_id)
        if expanded:
            if epic_key in self._expanded_epics:
                return
            self._expanded_epics.add(epic_key)
        else:
            if epic_key not in self._expanded_epics:
                return
            self._expanded_epics.discard(epic_key)
        snapshot = self._snapshot
        preferred_id = (
            None
            if snapshot is None
            else row_option_id(snapshot, "epic", row.project, epic_id)
        )
        self._refresh_options(preferred_id=preferred_id)

    def selected_preview(self) -> PreviewPayload | None:
        row = self.selected_row()
        if row is None:
            return None
        if row.proposal is not None:
            return PreviewPayload(
                content=row.proposal.content,
                lexer="markdown",
                title=row.proposal.title,
                kind_label="proposal",
                icon="◆",
                source_path=row.proposal.plan_path,
            )
        if row.archive is not None:
            plan = row.archive.plan
            return PreviewPayload(
                content=archive_preview_markdown(row.archive),
                lexer="markdown",
                title=plan.title or plan.name,
                kind_label=f"{plan.kind} plan",
                icon="▤",
                source_path=plan.path,
            )
        if row.issue is not None:
            return PreviewPayload(
                content=bead_preview_markdown(
                    row.issue,
                    self._snapshot,
                    project=row.project,
                ),
                lexer="markdown",
                title=f"{row.issue.id} · {row.issue.title}",
                kind_label="bead",
                icon="◈",
                # A logical reference is not openable; hand external tools the
                # path the reference currently resolves to, or nothing.
                source_path=resolved_plan_path(
                    row.issue,
                    self._snapshot,
                    project=row.project,
                ),
            )
        return None

    def _update_detail(self) -> None:
        try:
            properties = self.query_one("#plans-detail-properties", Static)
            body = self.query_one("#plans-detail", Markdown)
        except Exception:
            return
        row = self.selected_row()
        if row is None:
            properties.display = False
            properties.update("")
            body.update(self._empty_detail())
        elif row.proposal is not None:
            properties.display = True
            properties.update(
                proposal_properties_header(
                    row.proposal,
                    project_name=self._project_name(row.project),
                )
            )
            body.update(row.proposal.body or "_No plan body._")
        elif row.issue is not None:
            properties.display = True
            properties.update(
                bead_properties_header(
                    row.issue,
                    self._snapshot,
                    project=row.project,
                    project_name=self._project_name(row.project),
                )
            )
            linked_plan = linked_plan_for_issue(
                row.issue, self._snapshot, project=row.project
            )
            body.update(bead_body_markdown(row.issue, linked_plan))
        elif row.archive is not None:
            properties.display = True
            properties.update(
                archive_properties_header(
                    row.archive,
                    project_name=self._project_name(row.project),
                )
            )
            body.update(row.archive.plan.body or "_No plan body._")

    def _project_name(self, project: str) -> str:
        snapshot = self._snapshot
        if snapshot is None:
            return project
        return snapshot.display_names.get(project, project)

    def _option_list(self) -> PlansOptionList | None:
        try:
            return self.query_one("#plans-list", PlansOptionList)
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
            snapshot = self._snapshot
            if (
                row is not None
                and row.issue is not None
                and row.issue.parent_id
                and snapshot is not None
            ):
                return self._option_index(
                    row_option_id(
                        snapshot,
                        "epic",
                        row.project,
                        row.issue.parent_id,
                    )
                )
        return None

    def _first_selectable_index(self) -> int | None:
        option_list = self._option_list()
        if option_list is None:
            return None
        for index in range(option_list.option_count):
            if not option_list.get_option_at_index(index).disabled:
                return index
        return None


__all__ = ["PlansNavigationMixin"]
