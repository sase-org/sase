"""Interactive cross-repository commit timeline for the Artifacts tab."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from typing import TYPE_CHECKING, Any, Literal, cast

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache, lazy_renderable
from sase.ace.tui.widgets.prompt_panel._agent_commits import load_commit_diff_text
from sase.ace.tui.widgets.prompt_panel._agent_deltas import (
    parse_unified_diff_deltas,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.repo_inventory import RepoKind
from sase.vcs_log import run_vcs_log
from sase.vcs_log.models import VcsLogResult
from sase.vcs_log.render import (
    build_pretty_legend,
    build_timeline_commit,
    build_timeline_day,
)
from sase.vcs_log.tags import commit_tag_view
from sase.vcs_log._style import GOLD, repo_colors
from sase.vcs_log._tag_style import full_tag_lines

from .commit_filters import CommitLogFilterValues
from .panes import ArtifactsPaneLifecycle
from .types import ARTIFACTS_ACCENTS

if TYPE_CHECKING:
    from sase.ace.tui.actions.task_actions import TrackedTaskCompletion

CommitCollector = Callable[..., VcsLogResult]
_TimelineAction = Literal[
    "copy",
    "fetch",
    "filters",
    "refresh",
    "toggle_all",
    "toggle_sdd",
]


@dataclass(frozen=True)
class _CollectionSpec:
    generation: int
    project_scope: str | None
    all_projects: bool
    include_sdd: bool
    filters: CommitLogFilterValues


class CommitsTimeline(OptionList):
    """Day-grouped commit rows with local vim-style actions."""

    BINDINGS = [
        *OptionList.BINDINGS,
        Binding("j", "cursor_down", "Next commit", show=False),
        Binding("k", "cursor_up", "Previous commit", show=False),
        Binding("y", "copy_sha", "Copy SHA", show=False),
        Binding("f", "filters", "Filters", show=False),
        Binding("d", "toggle_sdd", "Toggle SDD", show=False),
        Binding("a", "toggle_all", "Toggle all projects", show=False),
        Binding("F", "fetch", "Fetch", show=False),
        Binding("R", "refresh", "Refresh", show=False),
    ]

    class SelectionChanged(Message):
        def __init__(self, commit_index: int) -> None:
            self.commit_index = commit_index
            super().__init__()

    class ActionRequested(Message):
        def __init__(self, action: _TimelineAction) -> None:
            self.action = action
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._commit_index_by_option: list[int | None] = []
        self._commits: tuple[AggregatedCommitWire, ...] = ()
        self._programmatic_update = False

    @property
    def selected_commit_index(self) -> int | None:
        highlighted = self.highlighted
        if highlighted is None or not (
            0 <= highlighted < len(self._commit_index_by_option)
        ):
            return None
        return self._commit_index_by_option[highlighted]

    def update_result(self, result: VcsLogResult) -> int | None:
        """Replace timeline rows while preserving the selected SHA."""
        selected_index = self.selected_commit_index
        selected_sha = (
            self._commits[selected_index].commit.full_id
            if selected_index is not None and selected_index < len(self._commits)
            else None
        )
        self._commits = tuple(result.commits)

        options: list[Option] = []
        mapping: list[int | None] = []
        current_day: str | None = None
        for commit_index, entry in enumerate(self._commits):
            day, banner = build_timeline_day(entry.commit.timestamp)
            if day != current_day:
                options.append(
                    Option(banner, id=f"commit-day-{commit_index}", disabled=True)
                )
                mapping.append(None)
                current_day = day
            options.append(
                Option(
                    build_timeline_commit(entry, result),
                    id=f"commit-{commit_index}",
                )
            )
            mapping.append(commit_index)

        if not options:
            message = "No commits match the current scope and filters."
            if result.warnings:
                message = result.warnings[0]
            options.append(Option(Text(f"  {message}", style="dim"), disabled=True))
            mapping.append(None)

        self._programmatic_update = True
        try:
            self.clear_options()
            self._commit_index_by_option = mapping
            self.add_options(options)
            target = self._option_for_sha(selected_sha)
            if target is None:
                target = next(
                    (
                        option_index
                        for option_index, index in enumerate(mapping)
                        if index is not None
                    ),
                    None,
                )
            self.highlighted = target
        finally:
            self._programmatic_update = False
        return self.selected_commit_index

    def _option_for_sha(self, sha: str | None) -> int | None:
        if sha is None:
            return None
        for option_index, commit_index in enumerate(self._commit_index_by_option):
            if (
                commit_index is not None
                and self._commits[commit_index].commit.full_id == sha
            ):
                return option_index
        return None

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._programmatic_update:
            return
        super().watch_highlighted(highlighted)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._programmatic_update or event.option_index is None:
            return
        index = self._commit_index_by_option[event.option_index]
        if index is not None:
            self.post_message(self.SelectionChanged(index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index is None:
            return
        index = self._commit_index_by_option[event.option_index]
        if index is not None:
            self.post_message(self.SelectionChanged(index))
            self.post_message(CommitsPane.OpenRequested(index))

    def _request(self, action: _TimelineAction) -> None:
        self.post_message(self.ActionRequested(action))

    def action_copy_sha(self) -> None:
        self._request("copy")

    def action_filters(self) -> None:
        self._request("filters")

    def action_toggle_sdd(self) -> None:
        self._request("toggle_sdd")

    def action_toggle_all(self) -> None:
        self._request("toggle_all")

    def action_fetch(self) -> None:
        self._request("fetch")

    def action_refresh(self) -> None:
        self._request("refresh")


class CommitsPane(ArtifactsPaneLifecycle, Vertical):
    """Lazy, cached, interactive view over the existing VCS-log backend."""

    class OpenRequested(Message):
        def __init__(self, commit_index: int) -> None:
            self.commit_index = commit_index
            super().__init__()

    def __init__(
        self,
        *,
        collector: CommitCollector | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self._collector = collector or run_vcs_log
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._project_file: str = ""
        self.all_projects = False
        self.include_sdd = False
        self.filters = CommitLogFilterValues()
        self.result: VcsLogResult | None = None
        self._generation = 0
        self._collection_worker: Worker[VcsLogResult] | None = None
        self._collection_generation: int | None = None
        self._collection_pending = False
        self._selected_commit_index: int | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._diff_worker: Worker[tuple[tuple[str, str], str | None]] | None = None
        self._diff_cache: dict[tuple[str, str], str | None] = {}
        self._diff_loading_key: tuple[str, str] | None = None
        self._syntax_render_cache = LazySyntaxRenderCache()

    def compose(self) -> ComposeResult:
        yield Static(self._build_info(), id="commits-info")
        with Horizontal(id="commits-main"):
            with Vertical(id="commits-list-container"):
                yield CommitsTimeline(id="commits-timeline")
                yield Static(
                    "j/k navigate  enter view  y copy  f filters  d SDD  "
                    "a all  F fetch  R refresh  p project",
                    id="commits-footer",
                )
            with Vertical(id="commits-detail-container"):
                with VerticalScroll(id="commits-detail-scroll"):
                    yield Static(
                        Text(
                            "Select a commit to inspect its message and diff.",
                            style="dim italic",
                        ),
                        id="commits-detail",
                    )

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        self._cancel_worker(self._collection_worker)
        self._cancel_worker(self._diff_worker)

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
        project_file: str | None = None,
    ) -> None:
        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._project_file = project_file or ""
        self._refresh_info()
        if changed:
            self._state_changed()

    def on_activate(self) -> None:
        if self.is_mounted:
            self.query_one("#commits-timeline", CommitsTimeline).focus()
        self._schedule_collection()

    def on_deactivate(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def on_refresh(self) -> None:
        self._schedule_collection()

    def _state_changed(self) -> None:
        self._generation += 1
        if self.artifacts_active:
            self._schedule_collection()

    def _collection_spec(self) -> _CollectionSpec:
        return _CollectionSpec(
            generation=self._generation,
            project_scope=self.project_scope,
            all_projects=self.all_projects,
            include_sdd=self.include_sdd,
            filters=self.filters,
        )

    def _collect(self, spec: _CollectionSpec, *, force_fetch: bool) -> VcsLogResult:
        return self._collector(
            cwd=os.getcwd(),
            limit=spec.filters.limit,
            filters=spec.filters.backend_filters(),
            repo_filters=spec.filters.repos,
            all_projects=spec.all_projects,
            project_scope=None if spec.all_projects else spec.project_scope,
            include_sdd=spec.include_sdd,
            no_fetch=not force_fetch,
            force_fetch=force_fetch,
        )

    def _schedule_collection(self) -> None:
        if not self.artifacts_active or not self.is_mounted:
            return
        worker = self._collection_worker
        if worker is not None and worker.is_running:
            self._collection_pending = True
            self._refresh_info()
            return
        spec = self._collection_spec()
        self._collection_generation = spec.generation
        self._collection_worker = self.run_worker(
            lambda spec=spec: self._collect(spec, force_fetch=False),
            thread=True,
            group="artifacts-commits-collection",
            exclusive=True,
            exit_on_error=False,
        )
        self._refresh_info()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._collection_worker:
            self._on_collection_worker_changed(event)
        elif event.worker is self._diff_worker:
            self._on_diff_worker_changed(event)

    def _on_collection_worker_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        generation = self._collection_generation
        self._collection_worker = None
        self._collection_generation = None
        stale = generation != self._generation
        pending = self._collection_pending or stale
        if event.state == WorkerState.SUCCESS and not pending:
            self._apply_result(cast(VcsLogResult, event.worker.result))
        elif event.state == WorkerState.ERROR and not pending:
            self._show_collection_error(event.worker.error)

        self._collection_pending = False
        self._refresh_info()
        if pending and self.artifacts_active:
            self._schedule_collection()

    def _apply_result(self, result: VcsLogResult) -> None:
        self.result = result
        timeline = self.query_one("#commits-timeline", CommitsTimeline)
        self._selected_commit_index = timeline.update_result(result)
        self._refresh_info()
        if self._selected_commit_index is not None:
            self._render_selected_detail(self._selected_commit_index)

    def _show_collection_error(self, error: BaseException | None) -> None:
        message = str(error).strip() if error is not None else "unknown error"
        self.query_one("#commits-timeline", CommitsTimeline).update_result(
            VcsLogResult((), (), (f"Unable to load commits: {message}",))
        )
        self.notify(f"Unable to load commits: {message}", severity="error")

    def _refresh_info(self) -> None:
        if self.is_mounted:
            self.query_one("#commits-info", Static).update(self._build_info())

    def _build_info(self) -> Text:
        accent = ARTIFACTS_ACCENTS["commits"]
        scope = (
            "All projects"
            if self.all_projects
            else self._project_display_name or self.project_scope or "Current project"
        )
        text = Text()
        text.append(" Commits ", style=f"bold #1a1a1a on {accent}")
        text.append("  Scope ", style="dim")
        text.append(scope, style=f"bold {accent}")
        text.append("  ·  ", style="dim")
        text.append(
            "SDD on" if self.include_sdd else "SDD off",
            style="bold" if self.include_sdd else "dim",
        )
        for chip in self._filter_chips():
            text.append("  ·  ", style="dim")
            text.append(chip, style="dim #87D7FF")
        worker = self._collection_worker
        if worker is not None and worker.is_running:
            text.append("  ·  refreshing…", style="italic #FFD700")
        if self.result is not None:
            text.append("\n")
            text.append_text(
                build_pretty_legend(self.result, filters=self.filters.backend_filters())
            )
            if self.result.warnings:
                text.append(
                    f"  ·  ⚠ {len(self.result.warnings)} warning(s)",
                    style="dim #FFAF5F",
                )
        else:
            text.append(
                "\n  Timeline loads lazily on first activation.", style="dim italic"
            )
        return text

    def _filter_chips(self) -> tuple[str, ...]:
        chips: list[str] = []
        if self.filters.authors:
            chips.append(f"author={','.join(self.filters.authors)}")
        if self.filters.since_text:
            chips.append(f"since={self.filters.since_text}")
        if self.filters.until_text:
            chips.append(f"until={self.filters.until_text}")
        if self.filters.repos:
            chips.append(f"repo={','.join(self.filters.repos)}")
        chips.append(f"limit={self.filters.limit or 'all'}")
        return tuple(chips)

    def on_commits_timeline_selection_changed(
        self, event: CommitsTimeline.SelectionChanged
    ) -> None:
        self._selected_commit_index = event.commit_index
        if self._detail_debouncer is None:
            self._render_selected_detail(event.commit_index)
            return
        index = event.commit_index

        def _render() -> None:
            self._render_selected_detail(index)

        self._detail_debouncer.schedule(_render)

    def on_commits_timeline_action_requested(
        self, event: CommitsTimeline.ActionRequested
    ) -> None:
        event.stop()
        actions: dict[_TimelineAction, Callable[[], None]] = {
            "copy": self.action_copy_sha,
            "fetch": self.action_fetch,
            "filters": self.action_filters,
            "refresh": self.action_refresh_commits,
            "toggle_all": self.action_toggle_all_projects,
            "toggle_sdd": self.action_toggle_sdd,
        }
        actions[event.action]()

    def on_commits_pane_open_requested(self, event: OpenRequested) -> None:
        event.stop()
        self.open_commit(event.commit_index)

    def action_copy_sha(self) -> None:
        from sase.ace.tui.actions.clipboard import copy_to_system_clipboard

        entry = self._selected_entry()
        if entry is None:
            return
        if copy_to_system_clipboard(entry.commit.full_id):
            self.notify("Copied commit SHA to clipboard")
        else:
            self.notify("Failed to copy to clipboard", severity="error")

    def action_filters(self) -> None:
        from sase.ace.tui.modals.commit_filters_modal import CommitFiltersModal

        repo_names = (
            tuple(repo.name for repo in self.result.repos)
            if self.result is not None
            else ()
        )

        def _apply(values: CommitLogFilterValues | None) -> None:
            if values is None or values == self.filters:
                return
            self.filters = values
            self._state_changed()

        self.app.push_screen(CommitFiltersModal(self.filters, repo_names), _apply)

    def action_toggle_sdd(self) -> None:
        self.include_sdd = not self.include_sdd
        self._state_changed()

    def action_toggle_all_projects(self) -> None:
        self.all_projects = not self.all_projects
        self._state_changed()

    def action_refresh_commits(self) -> None:
        self._schedule_collection()

    def action_fetch(self) -> None:
        from sase.ace.tui.actions.task_actions import TrackedTaskResult

        spec = self._collection_spec()
        submit = getattr(self.app, "_submit_tracked_task", None)
        if not callable(submit):
            self._schedule_collection()
            return

        def _task() -> TrackedTaskResult[VcsLogResult]:
            try:
                result = self._collect(spec, force_fetch=True)
            except Exception as exc:
                return TrackedTaskResult(
                    success=False,
                    message=f"Commit fetch failed: {exc}",
                    error=str(exc),
                )
            return TrackedTaskResult(
                success=True,
                message="Commit refs fetched",
                payload=result,
            )

        def _complete(completion: TrackedTaskCompletion[VcsLogResult]) -> None:
            if not completion.success or completion.payload is None:
                return
            if spec.generation == self._generation:
                self._apply_result(completion.payload)
            elif self.artifacts_active:
                self._schedule_collection()

        scope = "all" if spec.all_projects else spec.project_scope or "current"
        submit(
            "commit-fetch",
            f"commits:{scope}",
            self._project_file,
            _task,
            display_name=f"Fetch commits ({scope})",
            dedup_key=f"commit-fetch:{scope}",
            duplicate_message="A commit fetch is already running for this scope",
            on_complete=_complete,
            reload_on_complete=False,
        )

    def _selected_entry(self) -> AggregatedCommitWire | None:
        result = self.result
        index = self._selected_commit_index
        if result is None or index is None or not (0 <= index < len(result.commits)):
            return None
        return result.commits[index]

    def open_commit(self, commit_index: int) -> None:
        from sase.ace.tui.modals.commit_view_modal import CommitViewModal

        result = self.result
        if result is None or not (0 <= commit_index < len(result.commits)):
            return
        specs = tuple(self._view_spec(entry) for entry in result.commits)
        self.app.push_screen(CommitViewModal(specs, initial_index=commit_index))

    def _view_spec(self, entry: AggregatedCommitWire) -> CommitViewSpec:
        repo = (
            next((repo for repo in self.result.repos if repo.name == entry.repo), None)
            if self.result is not None
            else None
        )
        repo_kind: RepoKind = "linked"
        if repo is not None:
            repo_kind = (
                "primary"
                if repo.kind == "primary"
                else "sidecar"
                if repo.kind == "sdd"
                else "linked"
            )
        message = entry.commit.subject
        if entry.commit.body:
            message = f"{message}\n\n{entry.commit.body}"
        return CommitViewSpec(
            short_sha=entry.commit.short_id,
            sha=entry.commit.full_id,
            repo_name=entry.repo,
            cwd=repo.path if repo is not None else None,
            subject=entry.commit.subject,
            message=message,
            diff_path=None,
            is_primary=repo_kind == "primary",
            repo_kind=repo_kind,
        )

    def _render_selected_detail(self, commit_index: int) -> None:
        result = self.result
        if result is None or not (0 <= commit_index < len(result.commits)):
            return
        if commit_index != self._selected_commit_index:
            return
        entry = result.commits[commit_index]
        key = (entry.repo, entry.commit.full_id)
        if key in self._diff_cache:
            self._update_detail(entry, self._diff_cache[key], loading=False)
            return
        self._update_detail(entry, None, loading=True)
        self._start_diff_load(entry)

    def _start_diff_load(self, entry: AggregatedCommitWire) -> None:
        key = (entry.repo, entry.commit.full_id)
        worker = self._diff_worker
        if worker is not None and worker.is_running:
            if self._diff_loading_key == key:
                return
            worker.cancel()
        spec = self._view_spec(entry)
        self._diff_loading_key = key
        self._diff_worker = self.run_worker(
            lambda key=key, spec=spec: (key, load_commit_diff_text(spec)),
            thread=True,
            group="artifacts-commit-diff",
            exclusive=True,
            exit_on_error=False,
        )

    def _on_diff_worker_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        self._diff_worker = None
        self._diff_loading_key = None
        if event.state != WorkerState.SUCCESS:
            return
        key, diff_text = cast(tuple[tuple[str, str], str | None], event.worker.result)
        self._diff_cache[key] = diff_text
        entry = self._selected_entry()
        if entry is not None and key == (entry.repo, entry.commit.full_id):
            self._update_detail(entry, diff_text, loading=False)

    def _update_detail(
        self,
        entry: AggregatedCommitWire,
        diff_text: str | None,
        *,
        loading: bool,
    ) -> None:
        if not self.is_mounted:
            return
        self.query_one("#commits-detail", Static).update(
            self._build_detail(entry, diff_text, loading=loading)
        )

    def _build_detail(
        self,
        entry: AggregatedCommitWire,
        diff_text: str | None,
        *,
        loading: bool,
    ) -> RenderableType:
        commit = entry.commit
        colors = repo_colors(self.result.repos if self.result is not None else ())
        header = Text()
        header.append(entry.repo, style=f"bold {colors.get(entry.repo, '#87D7FF')}")
        header.append("  ")
        header.append(commit.short_id, style=GOLD)
        if commit.author_name:
            header.append(f"  ·  {commit.author_name}", style="dim")

        message = Text()
        message.append("Message\n", style="bold #87D7FF")
        message.append(commit.subject or "(message unavailable)", style="bold #D7D7FF")
        tag_view = commit_tag_view(commit)
        if tag_view.body:
            message.append("\n")
            message.append(tag_view.body.rstrip(), style="#D7D7FF")

        parts: list[RenderableType] = [header, message]
        parts.extend(full_tag_lines(tag_view.tags))
        summary = _change_summary(diff_text)
        if summary is not None:
            parts.append(summary)
        parts.append(Text("─" * 72, style="dim"))
        if loading:
            parts.append(Text("Loading diff…", style="dim italic #87D7FF"))
        elif diff_text:
            parts.append(
                lazy_renderable(
                    diff_text,
                    "diff",
                    line_numbers=True,
                    theme="monokai",
                    render_cache=self._syntax_render_cache,
                )
            )
        else:
            parts.append(
                Text("Diff unavailable for this commit.", style="dim italic #87D7FF")
            )
        return Group(*parts)

    @staticmethod
    def _cancel_worker(worker: Worker[Any] | None) -> None:
        if worker is not None and worker.is_running:
            worker.cancel()


def _change_summary(diff_text: str | None) -> Text | None:
    if not diff_text:
        return None
    entries = parse_unified_diff_deltas(diff_text)
    if not entries:
        return None
    added = modified = removed = 0
    for entry in entries:
        if entry.line_stats is None:
            continue
        added += entry.line_stats.added
        modified += entry.line_stats.modified
        removed += entry.line_stats.removed
    suffix = "file" if len(entries) == 1 else "files"
    text = Text("Changes: ", style="bold #87D7FF")
    text.append(f"+{added}", style="bold #5FD787")
    text.append(f"  ~{modified}", style="bold #FFD787")
    text.append(f"  -{removed}", style="bold #FF5F5F")
    text.append(f"  ·  {len(entries)} {suffix}", style="dim #87D7FF")
    return text


__all__ = ["CommitsPane", "CommitsTimeline"]
