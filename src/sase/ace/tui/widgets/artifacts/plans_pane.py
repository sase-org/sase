"""Interactive plan pipeline and bead DAG pane for ACE Artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.bead.model import Issue, Status
from sase.plan_search.model import PlanSearchMatch

from ...keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from .._prompt_preview_target import PreviewPayload
from .panes import ArtifactsPaneLifecycle
from .plans_data import PlanProposal, PlansSnapshot, load_plans_snapshot
from .types import ARTIFACTS_ACCENTS

if TYPE_CHECKING:
    from ...app import AceApp


PlanRowKind = Literal["proposal", "epic", "phase", "archive"]


@dataclass(frozen=True)
class PlanRow:
    """Identity-preserving row backing one selectable OptionList entry."""

    kind: PlanRowKind
    row_id: str
    proposal: PlanProposal | None = None
    issue: Issue | None = None
    archive: PlanSearchMatch | None = None


class ArtifactsPlansPane(ArtifactsPaneLifecycle, Vertical):
    """Browse proposals, epic phase trees, and committed plan markdown."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._snapshot: PlansSnapshot | None = None
        self._rows: dict[str, PlanRow] = {}
        self._expanded_epics: set[str] = set()
        self._loading = False
        self._reload_pending = False
        self._force_pending = False
        self._load_error: str | None = None
        self._worker: Worker[Any] | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._syncing_options = False

    def compose(self) -> ComposeResult:
        yield Static(self._scope_text(), classes="artifacts-pane-info", id="plans-info")
        with Horizontal(id="plans-panels"):
            list_panel = Vertical(id="plans-list-panel")
            list_panel.border_title = "Plan pipeline"
            with list_panel:
                yield Static(self._status_text(), id="plans-status")
                yield OptionList(id="plans-list")
            detail_panel = Vertical(id="plans-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="plans-detail-scroll"):
                    yield Markdown(self._empty_detail(), id="plans-detail")
        yield Static(self._hints_text(), id="plans-hints")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_options()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()

    def on_first_activate(self) -> None:
        self._request_load(force=False)

    def on_activate(self) -> None:
        self.focus_list()
        if self.project_scope is not None and (
            self._snapshot is None or self._snapshot.project != self.project_scope
        ):
            self._request_load(force=False)

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def on_refresh(self) -> None:
        self._request_load(force=True)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        self._registry = registry
        self._update_static("#plans-info", self._scope_text())
        self._update_static("#plans-hints", self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#plans-info", self._scope_text())
        if not changed:
            return
        self._load_error = None
        if project is None:
            self._snapshot = None
            self._refresh_options()
            return
        if self.artifacts_active:
            self._request_load(force=False)

    @property
    def snapshot(self) -> PlansSnapshot | None:
        return self._snapshot

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

    def set_selected_epic_expanded(self, expanded: bool) -> None:
        row = self.selected_row()
        if row is None or row.issue is None:
            return
        epic_id = row.issue.id if row.kind == "epic" else row.issue.parent_id
        if epic_id is None:
            return
        if expanded:
            if epic_id in self._expanded_epics:
                return
            self._expanded_epics.add(epic_id)
        else:
            if epic_id not in self._expanded_epics:
                return
            self._expanded_epics.discard(epic_id)
        self._refresh_options(preferred_id=f"epic:{epic_id}")

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
                content=_archive_markdown(row.archive),
                lexer="markdown",
                title=plan.title or plan.name,
                kind_label=f"{plan.kind} plan",
                icon="▤",
                source_path=plan.path,
            )
        if row.issue is not None:
            return PreviewPayload(
                content=self._bead_markdown(row.issue),
                lexer="markdown",
                title=f"{row.issue.id} · {row.issue.title}",
                kind_label="bead",
                icon="◈",
                source_path=row.issue.design or None,
            )
        return None

    def _request_load(self, *, force: bool) -> None:
        project = self.project_scope
        if project is None:
            self._refresh_options()
            return
        if self._loading:
            self._reload_pending = True
            self._force_pending = self._force_pending or force
            return
        self._loading = True
        self._load_error = None
        self._update_status()
        previous = (
            self._snapshot
            if self._snapshot is not None and self._snapshot.project == project
            else None
        )

        def task() -> PlansSnapshot:
            return load_plans_snapshot(project, previous=previous, force=force)

        self._worker = self.run_worker(
            task,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        terminal = event.state in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            if (
                isinstance(result, PlansSnapshot)
                and result.project == self.project_scope
            ):
                preferred = self._selected_option_id()
                self._snapshot = result
                self._load_error = result.error
                self._refresh_options(preferred_id=preferred)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._load_error = str(event.worker.error or "Plans load failed")
            self._update_status()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False

        if terminal and self._reload_pending:
            force = self._force_pending
            self._reload_pending = False
            self._force_pending = False
            self.call_later(lambda: self._request_load(force=force))

    def _refresh_options(self, *, preferred_id: str | None = None) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        if preferred_id is None:
            preferred_id = self._selected_option_id()
        options, rows = self._build_options()
        self._rows = rows
        self._syncing_options = True
        try:
            option_list.clear_options()
            option_list.add_options(options)
            target_index = self._option_index(preferred_id)
            if target_index is None:
                target_index = self._first_selectable_index()
            option_list.highlighted = target_index
        finally:
            self._syncing_options = False
        self._update_status()
        self._update_detail()

    def _build_options(self) -> tuple[list[Option], dict[str, PlanRow]]:
        options: list[Option] = []
        rows: dict[str, PlanRow] = {}
        snapshot = self._snapshot
        if self.project_scope is None:
            options.append(Option("Pick a project to browse plans.", disabled=True))
            return options, rows
        if snapshot is None or snapshot.project != self.project_scope:
            label = "Loading plans…" if self._loading else "Plans have not loaded yet."
            options.append(Option(label, disabled=True))
            return options, rows

        options.append(_section_option("Proposals", len(snapshot.proposals)))
        for proposal in snapshot.proposals:
            option_id = f"proposal:{proposal.notification.id}"
            rows[option_id] = PlanRow(
                "proposal",
                option_id,
                proposal=proposal,
            )
            options.append(Option(_proposal_text(proposal), id=option_id))
        if not snapshot.proposals:
            options.append(
                Option(Text("  No pending proposals", style="dim"), disabled=True)
            )

        options.append(_section_option("Epics", len(snapshot.epics)))
        for epic in snapshot.epics:
            option_id = f"epic:{epic.id}"
            rows[option_id] = PlanRow("epic", option_id, issue=epic)
            phases = snapshot.phases_by_epic.get(epic.id, ())
            options.append(
                Option(
                    _epic_text(
                        epic,
                        phases,
                        expanded=epic.id in self._expanded_epics,
                        ready_ids=snapshot.ready_ids,
                        blocked_ids=snapshot.blocked_ids,
                    ),
                    id=option_id,
                )
            )
            if epic.id not in self._expanded_epics:
                continue
            for phase in phases:
                phase_option_id = f"phase:{phase.id}"
                rows[phase_option_id] = PlanRow(
                    "phase",
                    phase_option_id,
                    issue=phase,
                )
                options.append(
                    Option(
                        _phase_text(
                            phase,
                            ready_ids=snapshot.ready_ids,
                            blocked_ids=snapshot.blocked_ids,
                        ),
                        id=phase_option_id,
                    )
                )
        if not snapshot.epics:
            options.append(Option(Text("  No epic beads", style="dim"), disabled=True))

        options.append(_section_option("Plan archive", len(snapshot.archive)))
        for match in snapshot.archive:
            plan = match.plan
            option_id = f"archive:{plan.path}"
            rows[option_id] = PlanRow("archive", option_id, archive=match)
            options.append(Option(_archive_text(match), id=option_id))
        if not snapshot.archive:
            options.append(
                Option(Text("  No committed plans", style="dim"), disabled=True)
            )
        return options, rows

    @on(OptionList.OptionHighlighted, "#plans-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return
        if self._detail_debouncer is None:
            self._update_detail()
        else:
            self._detail_debouncer.schedule(self._update_detail)

    @on(OptionList.OptionSelected, "#plans-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        cast("AceApp", self.app).action_plans_view_selected()

    def _update_detail(self) -> None:
        try:
            detail = self.query_one("#plans-detail", Markdown)
        except Exception:
            return
        row = self.selected_row()
        if row is None:
            detail.update(self._empty_detail())
        elif row.proposal is not None:
            detail.update(_proposal_markdown(row.proposal))
        elif row.issue is not None:
            detail.update(self._bead_markdown(row.issue))
        elif row.archive is not None:
            detail.update(_archive_markdown(row.archive))

    def _bead_markdown(self, issue: Issue) -> str:
        snapshot = self._snapshot
        state = _readiness_label(issue, snapshot)
        lines = [
            f"# {issue.id} · {issue.title}",
            "",
            f"**Status:** `{issue.status.value}`  ",
            f"**Readiness:** {state}  ",
            f"**Type:** `{issue.issue_type.value}`  ",
        ]
        if issue.model:
            lines.append(f"**Model:** `{issue.model}`  ")
        if issue.assignee:
            lines.append(f"**Assignee:** {issue.assignee}  ")
        if issue.changespec_name:
            lines.append(f"**ChangeSpec:** `{issue.changespec_name}`  ")
        if issue.changespec_bug_id:
            lines.append(f"**External bug:** `#{issue.changespec_bug_id}`  ")
        if issue.design:
            lines.append(f"**Design:** `{issue.design}`  ")
        lines.extend(
            ["", "## Description", "", issue.description or "_No description._"]
        )
        if issue.dependencies:
            lines.extend(["", "## Dependencies", ""])
            for dependency in issue.dependencies:
                dependency_state = self._dependency_state(dependency.depends_on_id)
                lines.append(f"- `{dependency.depends_on_id}` — {dependency_state}")
        if issue.notes:
            lines.extend(["", "## Notes", "", issue.notes])
        lines.extend(
            [
                "",
                "## History",
                "",
                f"- Created: {issue.created_at or '—'}",
                f"- Updated: {issue.updated_at or '—'}",
            ]
        )
        if issue.closed_at:
            lines.append(f"- Closed: {issue.closed_at}")
        if issue.close_reason:
            lines.append(f"- Close reason: {issue.close_reason}")
        return "\n".join(lines)

    def _dependency_state(self, issue_id: str) -> str:
        snapshot = self._snapshot
        if snapshot is None:
            return "unknown"
        for phases in snapshot.phases_by_epic.values():
            for phase in phases:
                if phase.id == issue_id:
                    return phase.status.value
        for epic in snapshot.epics:
            if epic.id == issue_id:
                return epic.status.value
        return "unknown"

    def _scope_text(self) -> Text:
        text = Text()
        text.append(
            " Plans ",
            style=f"bold #1a1a1a on {ARTIFACTS_ACCENTS['plans']}",
        )
        text.append("  Project scope  ", style="dim")
        label = self._project_display_name or self.project_scope or "Pick a project"
        text.append(f" {label} ", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
        text.append("  ·  ", style="dim")
        text.append(
            f"{key_display_name(self._registry.app.pick_artifacts_project)} change",
            style="dim",
        )
        return text

    def _status_text(self) -> Text:
        text = Text()
        if self._loading:
            text.append("Loading…", style="bold #FFD700")
        elif self._load_error:
            text.append(self._load_error, style="bold #FF5F5F")
        elif self._snapshot is None:
            text.append("Select a project", style="dim")
        else:
            snapshot = self._snapshot
            phase_count = sum(
                len(phases) for phases in snapshot.phases_by_epic.values()
            )
            text.append(f"{len(snapshot.proposals)} proposals", style="#FFD700")
            text.append("  ·  ", style="dim")
            text.append(
                f"{len(snapshot.epics)} epics", style=ARTIFACTS_ACCENTS["plans"]
            )
            text.append("  ·  ", style="dim")
            text.append(f"{phase_count} phases", style="#87D7FF")
            text.append("  ·  ", style="dim")
            text.append(f"{len(snapshot.archive)} archived", style="#00D7AF")
        return text

    def _hints_text(self) -> Text:
        km = self._registry.app
        parts = (
            (km.plans_next, "next"),
            (km.plans_prev, "prev"),
            (km.plans_view_selected, "view"),
            (km.plans_expand, "expand"),
            (km.plans_collapse, "collapse"),
            (km.plans_cycle_status, "status"),
            (km.plans_edit_bead, "edit"),
            (km.plans_launch_epic, "work"),
            (km.plans_approve, "approve"),
            (km.plans_reject, "reject"),
            (km.plans_open_bug, "bug"),
            (km.plans_refresh, "refresh"),
        )
        text = Text(justify="center")
        for index, (key, label) in enumerate(parts):
            if index:
                text.append("  ", style="dim")
            text.append(
                key_display_name(key), style=f"bold {ARTIFACTS_ACCENTS['plans']}"
            )
            text.append(f" {label}", style="dim")
        return text

    def _empty_detail(self) -> str:
        if self.project_scope is None:
            return "# Plans\n\nPick a project to browse its plan pipeline."
        if self._loading:
            return "# Plans\n\nLoading proposals, beads, and committed plans…"
        if self._load_error:
            return f"# Plans unavailable\n\n{self._load_error}"
        return "# Plans\n\nSelect a proposal, bead, or archived plan."

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one("#plans-list", OptionList)
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
            issue = self._rows.get(option_id)
            if issue is not None and issue.issue is not None and issue.issue.parent_id:
                return self._option_index(f"epic:{issue.issue.parent_id}")
        return None

    def _first_selectable_index(self) -> int | None:
        option_list = self._option_list()
        if option_list is None:
            return None
        for index in range(option_list.option_count):
            if not option_list.get_option_at_index(index).disabled:
                return index
        return None

    def _update_status(self) -> None:
        self._update_static("#plans-status", self._status_text())

    def _update_static(self, selector: str, content: Any) -> None:
        if not self.is_mounted:
            return
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass


def _section_option(label: str, count: int) -> Option:
    text = Text()
    text.append(f"── {label} ", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
    text.append(f"({count}) ", style="dim")
    text.append("─" * 8, style="dim #5F5F87")
    return Option(
        text, id=f"header:{label.casefold().replace(' ', '-')}", disabled=True
    )


def _proposal_text(proposal: PlanProposal) -> Text:
    text = Text()
    text.append("◆ ", style="bold #FFD700")
    text.append(proposal.title, style="bold white")
    text.append(f"  {proposal.tier}", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
    text.append(f"  {proposal.age}", style="dim")
    if proposal.agent != "-":
        text.append(f"  {proposal.agent}", style="dim #87D7FF")
    return text


def _epic_text(
    epic: Issue,
    phases: tuple[Issue, ...],
    *,
    expanded: bool,
    ready_ids: frozenset[str],
    blocked_ids: frozenset[str],
) -> Text:
    text = Text()
    text.append(
        "▾ " if expanded else "▸ ",
        style=f"bold {ARTIFACTS_ACCENTS['plans']}",
    )
    text.append(_status_glyph(epic.status), style=_status_style(epic.status))
    text.append(f" {epic.id} ", style="bold #FFD700")
    text.append(epic.title, style="bold white")
    closed = sum(phase.status == Status.CLOSED for phase in phases)
    text.append(f"  {closed}/{len(phases)} phases", style="#87D7FF")
    if epic.id in blocked_ids:
        text.append("  BLOCKED", style="bold #FF5F5F")
    elif epic.id in ready_ids:
        text.append("  READY", style="bold #5FD787")
    elif epic.is_ready_to_work:
        text.append("  LAUNCHED", style="bold #00D7AF")
    if epic.changespec_name:
        text.append(f"  {epic.changespec_name}", style="bold #00D7AF")
    if epic.changespec_bug_id:
        text.append(f"  #{epic.changespec_bug_id}", style="bold #FF875F")
    return text


def _phase_text(
    phase: Issue,
    *,
    ready_ids: frozenset[str],
    blocked_ids: frozenset[str],
) -> Text:
    text = Text("   ↳ ", style=f"dim {ARTIFACTS_ACCENTS['plans']}")
    text.append(_status_glyph(phase.status), style=_status_style(phase.status))
    text.append(f" {phase.id} ", style="bold #FFD700")
    text.append(phase.title, style="white")
    if phase.id in blocked_ids:
        text.append("  blocked", style="bold #FF5F5F")
    elif phase.id in ready_ids:
        text.append("  ready", style="bold #5FD787")
    elif phase.status == Status.IN_PROGRESS:
        text.append("  active", style="bold #FFD700")
    if phase.model:
        text.append(f"  {phase.model}", style="dim #87D7FF")
    return text


def _archive_text(match: PlanSearchMatch) -> Text:
    plan = match.plan
    text = Text("▤ ", style="bold #00D7AF")
    text.append(plan.title or plan.name, style="white")
    text.append(f"  {plan.kind}", style=f"bold {ARTIFACTS_ACCENTS['plans']}")
    if plan.status:
        status_style = "#5FD787" if plan.status in {"done", "approved"} else "#FFD700"
        text.append(f"  {plan.status}", style=f"bold {status_style}")
    if plan.created_at:
        text.append(f"  {plan.created_at[:10]}", style="dim")
    return text


def _proposal_markdown(proposal: PlanProposal) -> str:
    return "\n".join(
        [
            f"# {proposal.title}",
            "",
            "**State:** pending approval  ",
            f"**Tier:** `{proposal.tier}`  ",
            f"**Agent:** {proposal.agent}  ",
            f"**Model:** `{proposal.provider_model}`  ",
            f"**Age:** {proposal.age}  ",
            f"**Path:** `{proposal.plan_path}`",
            "",
            proposal.content,
        ]
    )


def _archive_markdown(match: PlanSearchMatch) -> str:
    plan = match.plan
    lines = [
        f"# {plan.title or plan.name}",
        "",
        f"**Tier:** `{plan.kind}`  ",
        f"**Status:** `{plan.status or 'unknown'}`  ",
        f"**Created:** {plan.created_at or '—'}  ",
        f"**Path:** `{plan.path}`",
        "",
    ]
    if plan.summary:
        lines.extend(["> " + plan.summary.replace("\n", "\n> "), ""])
    lines.append(plan.body or "_No plan body._")
    return "\n".join(lines)


def _readiness_label(issue: Issue, snapshot: PlansSnapshot | None) -> str:
    if issue.status == Status.CLOSED:
        return "closed"
    if issue.status == Status.IN_PROGRESS:
        return "in progress"
    if snapshot is None:
        return "unknown"
    if issue.id in snapshot.blocked_ids:
        return "**blocked**"
    if issue.id in snapshot.ready_ids:
        return "**ready**"
    return "waiting"


def _status_glyph(status: Status) -> str:
    return {
        Status.OPEN: "○",
        Status.IN_PROGRESS: "◐",
        Status.CLOSED: "●",
    }[status]


def _status_style(status: Status) -> str:
    return {
        Status.OPEN: "bold #87D7FF",
        Status.IN_PROGRESS: "bold #FFD700",
        Status.CLOSED: "bold #5FD787",
    }[status]


__all__ = ["ArtifactsPlansPane", "PlanRow"]
