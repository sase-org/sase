"""Selection, entry navigation, and document detail behavior for Plans."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.sdd.plan_refs import PLAN_REFERENCE_KIND
from sase.sidecar_ref_config import sidecar_role_ref_kind

from .._prompt_preview_target import PreviewPayload
from .entry_navigation import ArtifactEntryNavigator, ArtifactEntryTarget
from .plans_data import PlansSnapshot
from .plans_detail import (
    active_plan_properties_header,
    archive_preview_markdown,
    archive_properties_header,
    provider_detail_fields,
    proposal_properties_header,
)
from .plans_list import PlanRow, plan_row_target

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = ArtifactEntryNavigator


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
    """Own plan selection, targets, previews, and detail content."""

    project_scope: str | None
    _snapshot: PlansSnapshot | None
    _rows: dict[str, PlanRow]
    _banner_target_by_option_id: dict[str, ArtifactEntryTarget]
    _detail_debouncer: DetailPanelDebouncer | None
    _syncing_options: bool
    _entry_jump_hints: dict[ArtifactEntryTarget, str]
    _entry_marks: set[ArtifactEntryTarget]
    _pending_entry_target: ArtifactEntryTarget | None
    provider_spec: Mapping[str, Any] | None

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
        self._banner_target_by_option_id = {}
        self._detail_debouncer = None
        self._syncing_options = False
        self._entry_jump_hints = {}
        self._entry_marks = set()
        self._pending_entry_target = None

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
        if (option_list := self._option_list()) is not None:
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
            option = option_list.get_option_at_index(index)
            if option.disabled:
                continue
            option_id = option.id or ""
            if (row := self._rows.get(option_id)) is not None:
                targets.append(plan_row_target(row))
            elif (
                banner_target := self._banner_target_by_option_id.get(option_id)
            ) is not None:
                targets.append(banner_target)
        return tuple(targets)

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        row = self.selected_row()
        if row is not None:
            return plan_row_target(row)
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            option_id = (
                option_list.get_option_at_index(option_list.highlighted).id or ""
            )
        except Exception:
            return None
        return self._banner_target_by_option_id.get(option_id)

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
            self._sync_artifacts_footer()
        return True

    def request_entry_target(self, target: ArtifactEntryTarget) -> bool:
        if self.select_entry_target(target):
            self._pending_entry_target = None
            return True
        self._pending_entry_target = target
        if self._snapshot is not None and self._snapshot.project == self.project_scope:
            self._refresh_options()
        return False

    def clear_pending_entry_target(self) -> None:
        self._pending_entry_target = None

    def conditional_footer_entries(self) -> tuple[tuple[str, str], ...]:
        row = self.selected_row()
        if row is None or row.bead_link is None:
            return ()
        return (("plans_open_bead", "linked bead"),)

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        self._entry_jump_hints = dict(hints)
        self._refresh_options(update_detail=False)

    def clear_entry_jump_hints(self) -> None:
        if self._entry_jump_hints:
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
        option_list = self._option_list()
        if option_list is None:
            return None
        for index in range(option_list.option_count):
            option_id = option_list.get_option_at_index(index).id or ""
            row = self._rows.get(option_id)
            if row is not None and plan_row_target(row) == target:
                return index
            if self._banner_target_by_option_id.get(option_id) == target:
                return index
        return None

    def preview_for_row(self, row: PlanRow) -> PreviewPayload | None:
        if row.proposal is not None:
            return PreviewPayload(
                content=row.proposal.content,
                lexer="markdown",
                title=row.proposal.title,
                kind_label="proposal",
                icon="◆",
                source_path=row.proposal.plan_path,
                default_view="rendered",
            )
        if row.active is not None:
            document = row.active.document
            return PreviewPayload(
                content=document.content,
                lexer="markdown",
                title=document.frontmatter.get("title") or row.bead_link.bead_title,  # type: ignore[union-attr]
                kind_label="active plan",
                icon="▤",
                source_path=document.path,
                reference=row.active.owner.reference,
                default_view="rendered",
            )
        if row.archive is not None:
            plan = row.archive.plan
            role = sidecar_role_ref_kind(row.archive_role or PLAN_REFERENCE_KIND)
            return PreviewPayload(
                content=archive_preview_markdown(row.archive, role=role),
                lexer="markdown",
                title=plan.title or plan.name,
                kind_label=f"{plan.kind} plan",
                icon="▤",
                source_path=plan.path,
                reference=f"{role}:{plan.relpath}",
                default_view="rendered",
            )
        return None

    def selected_preview(self) -> PreviewPayload | None:
        row = self.selected_row()
        return None if row is None else self.preview_for_row(row)

    def _update_detail(self) -> None:
        try:
            properties = self.query_one("#plans-detail-properties", Static)
            body = self.query_one("#plans-detail", Markdown)
        except Exception:
            return
        row = self.selected_row()
        detail_fields = provider_detail_fields(getattr(self, "provider_spec", None))
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
                    detail_fields=detail_fields,
                )
            )
            body.update(row.proposal.body or "_No plan body._")
        elif row.active is not None:
            properties.display = True
            properties.update(
                active_plan_properties_header(
                    row.active,
                    project_name=self._project_name(row.project),
                    detail_fields=detail_fields,
                )
            )
            body.update(row.active.document.body or "_No plan body._")
        elif row.archive is not None:
            properties.display = True
            properties.update(
                archive_properties_header(
                    row.archive,
                    project_name=self._project_name(row.project),
                    role=sidecar_role_ref_kind(row.archive_role or PLAN_REFERENCE_KIND),
                    owner=row.bead_link,
                    detail_fields=detail_fields,
                )
            )
            body.update(row.archive.plan.body or "_No plan body._")

    def _project_name(self, project: str) -> str:
        snapshot = self._snapshot
        return (
            project
            if snapshot is None
            else snapshot.display_names.get(project, project)
        )

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
        if option_id is None or (option_list := self._option_list()) is None:
            return None
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == option_id:
                return index
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
