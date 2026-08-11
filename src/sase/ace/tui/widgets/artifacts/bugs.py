"""Tracker-backed Bugs pane for the Artifacts tab."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Literal, cast

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.artifacts_bugs import BugSnapshot, collect_bug_snapshot
from sase.bug_links import BugLinks
from sase.vcs_provider import IssueListState, IssueWire

from ...keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from ...util.debounce import DetailPanelDebouncer
from ...util.pump_tasks import spawn_pump_free_task
from .bugs_rendering import BUG_ACCENT, issue_meta, issue_row
from .entry_navigation import ArtifactEntryTarget
from .lifecycle import ArtifactsPaneLifecycle

_BUG_CACHE_TTL_S = 60.0
BugLinkKind = Literal["bead", "epic", "pr"]


class BugIssueList(OptionList):
    """Issue list whose programmatic highlights never echo as navigation."""

    class SelectionChanged(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

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
        """Assign a guarded highlight and synchronously reveal its row."""
        self.highlighted = index
        self.scroll_to_highlight()

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._programmatic_update:
            return
        super().watch_highlighted(highlighted)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if not self._programmatic_update and event.option_index is not None:
            self.post_message(self.SelectionChanged(event.option_index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index is not None:
            self.post_message(self.SelectionChanged(event.option_index))


class BugLinkList(OptionList):
    """Focusable local-work links rendered below the issue body."""

    BINDINGS = [
        ("j", "cursor_down", "Next"),
        ("k", "cursor_up", "Previous"),
        ("h", "focus_issue_list", "Issues"),
    ]

    def action_focus_issue_list(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.focus_issue_list()

    def _pane(self) -> ArtifactsBugsPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ArtifactsBugsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class ArtifactsBugsPane(ArtifactsPaneLifecycle, Vertical):
    """Lazy issue triage pane with cached list and debounced details."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self.state_filter: IssueListState = "open"
        self.snapshot = BugSnapshot(None, "", "", "", "open")
        self.issues: tuple[IssueWire, ...] = ()
        self.selected_index = 0
        self._registry = load_keymap_registry({})
        self._cache: dict[tuple[str, IssueListState], tuple[float, BugSnapshot]] = {}
        self._loading = False
        self._pending_load = False
        self._pending_force = False
        self._load_generation = 0
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._link_targets: list[tuple[BugLinkKind, str]] = []
        self._entry_jump_hints: dict[ArtifactEntryTarget, str] = {}
        self._entry_marks: set[ArtifactEntryTarget] = set()
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        yield Static(self._scope_text(), id="bugs-info", classes="artifacts-pane-info")
        with Horizontal(id="bugs-content"):
            with Vertical(id="bugs-list-container"):
                yield Static(self._list_header_text(), id="bugs-list-header")
                yield BugIssueList(id="bugs-list")
                yield Static("", id="bugs-list-message")
            with Vertical(id="bugs-detail-container"):
                yield Static("", id="bugs-detail-title")
                yield Static("", id="bugs-detail-meta")
                with VerticalScroll(id="bugs-body-scroll"):
                    yield Static("", id="bugs-body")
                yield Static("Linked work", id="bugs-links-title")
                yield BugLinkList(id="bugs-links")
        yield Static(self._footer_text(), id="bugs-footer")

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._paint_snapshot(self.snapshot)

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def on_activate(self) -> None:
        self.focus_issue_list()
        self.schedule_load()

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def on_refresh(self) -> None:
        # Auto-refresh respects the TTL. Explicit R refresh is a tracked task
        # routed through the app mixin.
        self.schedule_load()

    @property
    def selected_issue(self) -> IssueWire | None:
        if 0 <= self.selected_index < len(self.issues):
            return self.issues[self.selected_index]
        return None

    @property
    def project_file(self) -> str:
        return self.snapshot.project_file

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        self._registry = registry
        if self.is_mounted:
            self.query_one("#bugs-info", Static).update(self._scope_text())
            self.query_one("#bugs-footer", Static).update(self._footer_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        if self.is_mounted:
            self.query_one("#bugs-info", Static).update(self._scope_text())
        if changed:
            self.selected_index = 0
            self._load_generation += 1
            if project is None:
                self.accept_snapshot(BugSnapshot(None, "", "", "", self.state_filter))
            elif self.artifacts_active:
                self.schedule_load(force=True)

    def cycle_filter(self) -> None:
        order: tuple[IssueListState, ...] = ("open", "closed", "all")
        self.state_filter = order[(order.index(self.state_filter) + 1) % len(order)]
        self.selected_index = 0
        self._load_generation += 1
        if self.is_mounted:
            self.query_one("#bugs-list-header", Static).update(self._list_header_text())
        self.schedule_load(force=True)

    def schedule_load(self, *, force: bool = False) -> None:
        """Coalesce one off-thread issue load using last-request-wins state."""
        project = self.project_scope
        if project is None:
            self.accept_snapshot(BugSnapshot(None, "", "", "", self.state_filter))
            return
        key = (project, self.state_filter)
        cached = self._cache.get(key)
        if not force and cached is not None:
            loaded_at, snapshot = cached
            self.accept_snapshot(snapshot)
            if time.monotonic() - loaded_at < _BUG_CACHE_TTL_S:
                return
        if self._loading:
            self._pending_load = True
            self._pending_force = self._pending_force or force
            return

        self._loading = True
        generation = self._load_generation
        state_filter = self.state_filter
        patches = tuple(getattr(self.app, "artifacts", ()))
        self._set_loading_message()

        async def _runner() -> None:
            try:
                snapshot = await asyncio.to_thread(
                    collect_bug_snapshot,
                    project,
                    state_filter,
                    patches,
                )
                self._cache[(project, state_filter)] = (time.monotonic(), snapshot)
                if (
                    generation == self._load_generation
                    and self.project_scope == project
                    and self.state_filter == state_filter
                    and self.artifacts_active
                ):
                    self.accept_snapshot(snapshot)
            finally:
                self._loading = False
                if self._pending_load:
                    pending_force = self._pending_force
                    self._pending_load = False
                    self._pending_force = False
                    self.schedule_load(force=pending_force)

        task = spawn_pump_free_task(
            self.app,
            _runner(),
            name="sase-artifacts-bugs-auto-load",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            # Keep automatic loading retryable when called without a running
            # event loop (notably narrow fallback and unit-test callers).
            self._loading = False

    def accept_snapshot(self, snapshot: BugSnapshot) -> None:
        """Cache and paint a snapshot on the UI thread when it is current."""
        if snapshot.project_key is not None:
            self._cache[(snapshot.project_key, snapshot.state_filter)] = (
                time.monotonic(),
                snapshot,
            )
        if snapshot.state_filter != self.state_filter:
            return
        previous_target = self.selected_entry_target()
        cancel_jump = getattr(
            self.app, "_cancel_artifacts_jump_mode_for_model_change", None
        )
        if callable(cancel_jump):
            cancel_jump("bugs")
        self.snapshot = snapshot
        self.issues = snapshot.issues
        if self.issues:
            selected_index = self._index_for_target(previous_target)
            self.selected_index = (
                selected_index
                if selected_index is not None
                else min(self.selected_index, len(self.issues) - 1)
            )
        else:
            self.selected_index = 0
        if self.is_mounted:
            self._paint_snapshot(snapshot)

    def invalidate_cache(self) -> None:
        if self.project_scope is None:
            return
        self._cache.pop((self.project_scope, self.state_filter), None)

    def apply_issue(self, issue: IssueWire) -> None:
        """Apply a completed mutation without waiting for a full reload."""
        issues = list(self.issues)
        existing = next(
            (
                index
                for index, candidate in enumerate(issues)
                if candidate.number == issue.number
            ),
            None,
        )
        belongs = self.state_filter == "all" or issue.state == self.state_filter
        if existing is None and belongs:
            issues.insert(0, issue)
            self.selected_index = 0
        elif existing is not None and belongs:
            issues[existing] = issue
            self.selected_index = existing
        elif existing is not None:
            issues.pop(existing)
            self.selected_index = min(self.selected_index, max(0, len(issues) - 1))
        old_links = dict(self.snapshot.links)
        links = tuple(
            (
                candidate.number,
                old_links.get(
                    candidate.number, BugLinks(str(candidate.number), (), ())
                ),
            )
            for candidate in issues
        )
        self.invalidate_cache()
        self.accept_snapshot(
            replace(self.snapshot, issues=tuple(issues), links=links, error="")
        )

    def move_selection(self, step: int) -> None:
        if not self.issues:
            return
        self.selected_index = (self.selected_index + step) % len(self.issues)
        issue_list = self.query_one("#bugs-list", BugIssueList)
        issue_list.set_highlight(self.selected_index)
        self._schedule_detail_paint()

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return tuple(self._issue_target(issue) for issue in self.issues)

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        issue = self.selected_issue
        return None if issue is None else self._issue_target(issue)

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        index = self._index_for_target(target)
        if index is None or not self.is_mounted:
            return False
        changed = index != self.selected_index
        self.selected_index = index
        issue_list = self.query_one("#bugs-list", BugIssueList)
        issue_list.focus()
        issue_list.set_highlight(index)
        if changed:
            self._schedule_detail_paint()
        return True

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        self._entry_jump_hints = dict(hints)
        self._paint_issue_options()

    def clear_entry_jump_hints(self) -> None:
        if not self._entry_jump_hints:
            return
        self._entry_jump_hints = {}
        self._paint_issue_options()

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        self._entry_marks = set(marks)
        self._paint_issue_options()

    def _issue_target(self, issue: IssueWire) -> ArtifactEntryTarget:
        scope = self.snapshot.project_key or self.project_scope or ""
        return ("bug", scope, str(issue.number))

    def _index_for_target(self, target: ArtifactEntryTarget | None) -> int | None:
        if target is None:
            return None
        return next(
            (
                index
                for index, issue in enumerate(self.issues)
                if self._issue_target(issue) == target
            ),
            None,
        )

    def focus_issue_list(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#bugs-list", BugIssueList).focus()

    def focus_links(self) -> None:
        if not self._link_targets:
            self.app.notify("No linked beads or PRs for this bug", severity="warning")
            return
        links = self.query_one("#bugs-links", BugLinkList)
        links.focus()
        if links.highlighted is None:
            links.highlighted = 0

    def open_highlighted_link(self, index: int | None = None) -> None:
        links = self.query_one("#bugs-links", BugLinkList)
        if index is None:
            index = links.highlighted
        if index is None or not 0 <= index < len(self._link_targets):
            return
        kind, target = self._link_targets[index]
        opener = getattr(self.app, "_open_bug_link", None)
        if callable(opener):
            opener(kind, target)

    def _paint_snapshot(self, snapshot: BugSnapshot) -> None:
        self.query_one("#bugs-info", Static).update(self._scope_text())
        self.query_one("#bugs-list-header", Static).update(self._list_header_text())
        self._paint_issue_options()
        self.query_one("#bugs-list-message", Static).update(
            self._snapshot_message(snapshot)
        )
        self._paint_detail()

    def _paint_issue_options(self) -> None:
        if not self.is_mounted:
            return
        issue_list = self.query_one("#bugs-list", BugIssueList)
        issue_list.replace_options(
            [
                Option(
                    issue_row(
                        issue,
                        jump_hint=self._entry_jump_hints.get(self._issue_target(issue)),
                        marked=self._issue_target(issue) in self._entry_marks,
                    ),
                    id=f"bug-{issue.number}",
                )
                for issue in self.issues
            ],
            highlighted=self.selected_index if self.issues else None,
        )

    def _set_loading_message(self) -> None:
        if self.is_mounted and not self.issues:
            self.query_one("#bugs-list-message", Static).update(
                Text("Loading issues…", style="dim italic")
            )

    def _snapshot_message(self, snapshot: BugSnapshot) -> Text:
        if snapshot.project_key is None:
            return Text(
                "Pick a project to establish the tracker scope.", style="dim italic"
            )
        if not snapshot.supported:
            return Text(
                "Bugs needs a tracker-capable provider (GitHub) for this project.",
                style="bold #FFAF5F",
            )
        if snapshot.error:
            return Text(f"Tracker error: {snapshot.error}", style="bold red")
        if not snapshot.issues:
            return Text(f"No {self.state_filter} issues.", style="dim italic")
        if snapshot.warning:
            return Text(snapshot.warning, style="dim #FFAF5F")
        return Text()

    def _schedule_detail_paint(self) -> None:
        if self._detail_debouncer is None:
            self._paint_detail()
            return
        self._detail_debouncer.schedule(self._paint_detail)

    def _paint_detail(self) -> None:
        issue = self.selected_issue
        title = self.query_one("#bugs-detail-title", Static)
        meta = self.query_one("#bugs-detail-meta", Static)
        body = self.query_one("#bugs-body", Static)
        links_title = self.query_one("#bugs-links-title", Static)
        links = self.query_one("#bugs-links", BugLinkList)
        links.clear_options()
        self._link_targets = []
        if issue is None:
            title.update(Text("No issue selected", style="dim italic"))
            meta.update("")
            body.update("")
            links_title.display = False
            links.display = False
            return
        links_title.display = True
        links.display = True

        heading = Text()
        heading.append(f"#{issue.number} ", style=f"bold {BUG_ACCENT}")
        heading.append(issue.title, style="bold white")
        title.update(heading)
        meta.update(issue_meta(issue))
        body.update(Markdown(issue.body or "*No description provided.*"))

        bug_links = self.snapshot.links_for(issue.number)
        options: list[Option] = []
        for epic in bug_links.epics:
            self._link_targets.append(("epic", epic.id))
            options.append(
                Option(
                    Text.assemble(
                        (" Epic  ", "bold #AF87FF"),
                        (epic.id, "bold white"),
                        (f"  {epic.title}", "dim"),
                    ),
                    id=f"epic-{epic.id}",
                )
            )
        for bead in bug_links.beads:
            self._link_targets.append(("bead", bead.id))
            kind = bead.issue_type.value.title()
            options.append(
                Option(
                    Text.assemble(
                        (f" {kind:<5} ", "bold #FFD166"),
                        (bead.id, "bold white"),
                        (f"  {bead.title}", "dim"),
                    ),
                    id=f"bead-{bead.id}",
                )
            )
        for patch in bug_links.patches:
            self._link_targets.append(("pr", patch.name))
            options.append(
                Option(
                    Text.assemble(
                        (" PR    ", "bold #00D7AF"),
                        (patch.name, "bold white"),
                        (f"  {patch.status}", "dim"),
                    ),
                    id=f"pr-{patch.name}",
                )
            )
        links.add_options(options)

    def _scope_text(self) -> Text:
        scope = self._project_display_name or self.project_scope or "Pick a project"
        text = Text()
        text.append(" Bugs ", style=f"bold #1a1a1a on {BUG_ACCENT}")
        text.append("  Project scope  ", style="dim")
        text.append(f" {scope} ", style=f"bold {BUG_ACCENT}")
        text.append("  ·  ", style="dim")
        text.append(
            f"{key_display_name(self._registry.app.pick_artifacts_project)} change",
            style="dim",
        )
        return text

    def _list_header_text(self) -> Text:
        text = Text()
        text.append("Issues", style="bold white")
        text.append("  ", style="dim")
        text.append(f" {self.state_filter} ", style=f"bold {BUG_ACCENT}")
        text.append(f"  {len(self.issues)}", style="dim")
        return text

    def _footer_text(self) -> Text:
        a = self._registry.app
        actions = (
            (a.next_bug, "next"),
            (a.prev_bug, "prev"),
            (a.cycle_bug_filter, "state"),
            (a.create_bug, "create"),
            (a.edit_bug, "edit"),
            (a.toggle_bug_state, "close/reopen"),
            (a.open_bug, "browser"),
            (a.copy_bug, "copy"),
            (a.start_agent_from_bug, "agent"),
            (a.focus_bug_links, "links"),
            (a.refresh_bugs, "refresh"),
        )
        text = Text(justify="center")
        for index, (key, label) in enumerate(actions):
            if index:
                text.append("  ·  ", style="dim")
            text.append(key_display_name(key), style=f"bold {BUG_ACCENT}")
            text.append(f" {label}", style="dim")
        return text

    def on_bug_issue_list_selection_changed(
        self, event: BugIssueList.SelectionChanged
    ) -> None:
        event.stop()
        if 0 <= event.index < len(self.issues):
            self.selected_index = event.index
            self._schedule_detail_paint()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "bugs-links":
            event.stop()
            self.open_highlighted_link(event.option_index)


__all__ = ["ArtifactsBugsPane", "BugIssueList", "BugLinkList"]
