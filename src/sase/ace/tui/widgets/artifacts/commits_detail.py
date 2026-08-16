"""Timeline selection and detail loading for the commits pane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

from rich.console import RenderableType
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.vcs_log.models import VcsLogResult

from .commits_rendering import build_commit_detail, build_commit_view_spec
from .commits_timeline import CommitsTimeline
from .entry_navigation import ArtifactEntryNavigator, ArtifactEntryTarget

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = ArtifactEntryNavigator


CommitDiffLoader = Callable[[CommitViewSpec], str | None]


class CommitsDetailMixin(_MixinBase):
    """Own timeline selection, modal opening, and async diff details."""

    result: VcsLogResult | None
    _diff_loader: CommitDiffLoader
    _selected_commit_index: int | None
    _detail_debouncer: DetailPanelDebouncer | None
    _diff_worker: Worker[tuple[tuple[str, str], str | None]] | None
    _diff_cache: dict[tuple[str, str], str | None]
    _diff_loading_key: tuple[str, str] | None
    _syntax_render_cache: LazySyntaxRenderCache
    _pending_entry_target: ArtifactEntryTarget | None

    if TYPE_CHECKING:

        def _refresh_info(self) -> None: ...

        def _refresh_position_badge(self) -> None: ...

        def _sync_timeline_grouping(self, timeline: CommitsTimeline) -> None: ...

        def refresh_relation_panel(self, *, refresh_footer: bool = True) -> Any: ...

        def relation_footer_entries(
            self, keymap: Any = None
        ) -> tuple[tuple[str, str], ...]: ...

    def _init_commits_detail(self, diff_loader: CommitDiffLoader) -> None:
        self._diff_loader = diff_loader
        self._selected_commit_index = None
        self._detail_debouncer = None
        self._diff_worker = None
        self._diff_cache = {}
        self._diff_loading_key = None
        self._syntax_render_cache = LazySyntaxRenderCache()
        self._pending_entry_target = None

    def move_selection(self, step: int) -> None:
        timeline = self.query_one("#stitches-timeline", CommitsTimeline)
        timeline.focus()
        timeline.ensure_render_cache_warmed()
        if step > 0:
            timeline.action_cursor_down()
        else:
            timeline.action_cursor_up()
        # Keep this synchronous even if Textual changes when it delivers the
        # corresponding OptionHighlighted message.
        self._sync_timeline_selection(timeline.selected_commit_index)

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        timeline = self.query_one("#stitches-timeline", CommitsTimeline)
        return timeline.entry_targets

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        timeline = self.query_one("#stitches-timeline", CommitsTimeline)
        return timeline.selected_entry_target

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Select a loaded commit by repository + full SHA identity."""
        timeline = self.query_one("#stitches-timeline", CommitsTimeline)
        if not timeline.select_entry_target(target):
            return False
        self._sync_timeline_selection(timeline.selected_commit_index)
        return True

    def request_entry_target(self, target: ArtifactEntryTarget) -> bool:
        if self.select_entry_target(target):
            self._pending_entry_target = None
            return True
        self._pending_entry_target = target
        return False

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
        if self.result is None:
            return
        self.query_one("#stitches-timeline", CommitsTimeline).apply_jump_hints(
            hints, self.result
        )

    def clear_entry_jump_hints(self) -> None:
        if self.result is None:
            return
        self.query_one("#stitches-timeline", CommitsTimeline).clear_jump_hints(
            self.result
        )

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        if self.result is None:
            return
        self.query_one("#stitches-timeline", CommitsTimeline).apply_marks(
            marks, self.result
        )

    def _display_result(
        self,
        result: VcsLogResult,
        *,
        live_preview: bool = False,
    ) -> None:
        cancel_jump = getattr(
            self.app, "_cancel_artifacts_jump_mode_for_model_change", None
        )
        if callable(cancel_jump):
            cancel_jump("stitches")
        self.result = result
        timeline = self.query_one("#stitches-timeline", CommitsTimeline)
        sync_grouping = getattr(self, "_sync_timeline_grouping", None)
        if callable(sync_grouping):
            sync_grouping(timeline)
        self._selected_commit_index = timeline.update_result(result)
        pending = self._pending_entry_target
        if pending is not None:
            if timeline.select_entry_target(pending):
                self._pending_entry_target = None
                self._selected_commit_index = timeline.selected_commit_index
            else:
                self._pending_entry_target = None
                notify = getattr(self, "notify", None)
                if callable(notify):
                    notify(
                        "Linked commit is no longer visible in Stitches",
                        severity="warning",
                    )
        self._refresh_info()
        self.refresh_relation_panel()
        if self._selected_commit_index is not None:
            if live_preview and self._detail_debouncer is not None:
                index = self._selected_commit_index

                def _render() -> None:
                    self._render_selected_detail(index)

                self._detail_debouncer.schedule(_render)
            else:
                self._render_selected_detail(self._selected_commit_index)

    def on_commits_timeline_selection_changed(
        self, event: CommitsTimeline.SelectionChanged
    ) -> None:
        self._sync_timeline_selection(event.commit_index)

    def _sync_timeline_selection(self, commit_index: int | None) -> None:
        """Publish a position change before debouncing the heavier detail pane."""
        if commit_index == self._selected_commit_index:
            return
        self._selected_commit_index = commit_index
        self._refresh_position_badge()
        self.refresh_relation_panel()
        if commit_index is None:
            return
        if self._detail_debouncer is None:
            self._render_selected_detail(commit_index)
            return

        def _render() -> None:
            self._render_selected_detail(commit_index)

        self._detail_debouncer.schedule(_render)

    def on_commits_timeline_open_requested(
        self, event: CommitsTimeline.OpenRequested
    ) -> None:
        event.stop()
        self.open_commit(event.commit_index)

    def copy_selected_sha(self) -> None:
        from sase.ace.tui.actions.clipboard import schedule_copy_delivery

        entry = self._selected_entry()
        if entry is None:
            return
        schedule_copy_delivery(
            self,
            entry.commit.full_id,
            copied_label="commit SHA",
            task_name="sase-copy-commit-detail-sha",
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

    def open_selected_commit(self) -> None:
        if self._selected_commit_index is not None:
            self.open_commit(self._selected_commit_index)

    def _view_spec(self, entry: AggregatedCommitWire) -> CommitViewSpec:
        return build_commit_view_spec(entry, self.result)

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
            lambda key=key, spec=spec: (key, self._diff_loader(spec)),
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
        self.query_one("#stitches-detail", Static).update(
            self._build_detail(entry, diff_text, loading=loading)
        )

    def _build_detail(
        self,
        entry: AggregatedCommitWire,
        diff_text: str | None,
        *,
        loading: bool,
    ) -> RenderableType:
        return build_commit_detail(
            entry,
            diff_text,
            loading=loading,
            result=self.result,
            render_cache=self._syntax_render_cache,
        )


__all__ = ["CommitDiffLoader", "CommitsDetailMixin"]
