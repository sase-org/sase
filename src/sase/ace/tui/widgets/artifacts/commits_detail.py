"""Timeline selection and detail loading for the commits pane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

from rich.console import RenderableType
from textual.css.query import NoMatches
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.vcs_log.models import VcsLogResult

from .commits_rendering import build_commit_detail, build_commit_view_spec
from .commits_timeline import CommitsTimeline, commit_row_target
from .entry_navigation import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    HydrationOutcome,
    HydrationResult,
    LinkRequestState,
)

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
    _pending_entry_generation: int | None
    _stitch_repo_info_cache: dict[str, tuple[str, tuple[str, ...]]]
    _stitch_inventory_kinds_cache: dict[str, tuple[str, tuple[str, ...]]]

    if TYPE_CHECKING:

        def _refresh_info(self) -> None: ...

        def _refresh_position_badge(self) -> None: ...

        def _sync_timeline_grouping(self, timeline: CommitsTimeline) -> None: ...

        def refresh_relation_panel(self, *, refresh_footer: bool = True) -> Any: ...

        def relation_footer_entries(
            self, keymap: Any = None
        ) -> tuple[tuple[str, str], ...]: ...

        def _complete_entry_request(
            self, state: LinkRequestState
        ) -> LinkRequestState: ...

    def _init_commits_detail(self, diff_loader: CommitDiffLoader) -> None:
        self._diff_loader = diff_loader
        self._selected_commit_index = None
        self._detail_debouncer = None
        self._diff_worker = None
        self._diff_cache = {}
        self._diff_loading_key = None
        self._syntax_render_cache = LazySyntaxRenderCache()
        self._pending_entry_target = None
        self._pending_entry_generation = None
        self._stitch_repo_info_cache = {}
        self._stitch_inventory_kinds_cache = {}

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
        if self._collection_in_flight():
            return LinkRequestState.PENDING
        return self._complete_entry_request(LinkRequestState.MISSING)

    def _collection_in_flight(self) -> bool:
        """Return whether a Stitches collection or query evaluation is outstanding.

        A collection counts from the tick it is scheduled until its
        results are applied: a scheduled-but-not-yet-running worker and a
        finished-but-undelivered one both still count, so the link-follow
        Context step's same-tick re-request — and any later _display_result
        racing delivery — waits instead of reporting a premature miss.
        """
        if getattr(self, "_collection_generation", None) is not None:
            return True
        if getattr(self, "_collection_pending", False):
            return True
        return bool(getattr(self, "_query_result_pending", False))

    def hydrate_ref(self, kind: str, payload: str) -> HydrationResult:
        """Resolve one ``stitch:repo@sha`` commit directly, bypassing collection.

        Requests exactly this revision through the repo's own VCS
        provider -- no ``since``/``until``/sidecar/merges window, no
        remote-ref resolution -- so it never grows the collected inventory.
        The checkout resolves from the project's full repo inventory
        (primary, linked, and sidecar repos), not only from repos in the
        displayed result, so sidecar and linked repos hydrate even when
        the current window excludes them.
        """
        if kind != "stitch":
            return HydrationResult(HydrationOutcome.UNSUPPORTED)
        repo, sep, sha = payload.partition("@")
        if not sep or not repo or not sha:
            return HydrationResult(HydrationOutcome.UNSUPPORTED)
        checkout = self._stitch_repo_checkout(repo)
        if checkout is None:
            return HydrationResult(HydrationOutcome.UNSUPPORTED)
        checkout_path, repo_kind, repo_labels = checkout
        from sase.vcs_provider import VCSOperationError, get_vcs_provider

        try:
            provider = get_vcs_provider(checkout_path)
            full_sha = provider.revision_id(f"{sha}^{{commit}}", checkout_path)
        except VCSOperationError:
            return HydrationResult(HydrationOutcome.ABSENT)
        except Exception as exc:  # noqa: BLE001 - reported as FAILED below
            return HydrationResult(HydrationOutcome.FAILED, error=str(exc))
        normalized = full_sha.strip().lower()
        if len(normalized) != 40 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            return HydrationResult(HydrationOutcome.ABSENT)
        try:
            commits = provider.log(checkout_path, 1, revs=(normalized,), merges="show")
        except Exception as exc:  # noqa: BLE001 - reported as FAILED below
            return HydrationResult(HydrationOutcome.FAILED, error=str(exc))
        if not commits:
            return HydrationResult(HydrationOutcome.ABSENT)
        self._remember_stitch_repo_info(repo, repo_kind, repo_labels)
        return HydrationResult(
            HydrationOutcome.FETCHED,
            payload=AggregatedCommitWire(repo=repo, commit=commits[0]),
        )

    def _stitch_repo_checkout(
        self, repo: str
    ) -> tuple[str, str, tuple[str, ...]] | None:
        """Return ``(checkout path, kind, labels)`` for *repo*.

        Reads the displayed result first, then the project's full repo
        inventory, so checkouts resolve even when the current collection
        window excludes their repo.
        """
        result = self.result
        if result is not None:
            for log_repo in result.repos:
                if log_repo.name == repo or repo in log_repo.aliases:
                    return (
                        log_repo.path,
                        log_repo.kind,
                        tuple(dict.fromkeys((log_repo.name, *log_repo.aliases))),
                    )
        cached = getattr(self, "_stitch_repo_info_cache", None)
        if isinstance(cached, dict) and repo in cached:
            kind, labels = cached[repo]
            path = self._stitch_inventory_checkout(repo)
            if path is not None:
                return (path, kind, labels)
        path = self._stitch_inventory_checkout(repo)
        if path is None:
            return None
        info = self._stitch_inventory_repo_info(repo)
        if info is None:
            return (path, "primary", (repo,))
        return (path, *info)

    def _stitch_checkout_path(self, repo: str) -> str | None:
        checkout = self._stitch_repo_checkout(repo)
        return None if checkout is None else checkout[0]

    def _remember_stitch_repo_info(
        self, repo: str, kind: str, labels: tuple[str, ...]
    ) -> None:
        """Cache one repo's kind and labels beside the acquired facts.

        Runs off the UI thread inside :meth:`hydrate_ref`; the cache lets
        the UI-thread install recover sidecar/kind facts for repos the
        displayed result never contained, with no inventory I/O of its own.
        """
        cache = getattr(self, "_stitch_repo_info_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._stitch_repo_info_cache = cache
        cache[repo] = (kind, tuple(labels) or (repo,))

    def _stitch_inventory_checkout(self, repo: str) -> str | None:
        """Return *repo*'s checkout path from the project repo inventory."""
        info = self._stitch_inventory_repos()
        if info is None:
            return None
        return info.get(repo) or info.get(repo.casefold())

    def _stitch_inventory_repo_info(
        self, repo: str
    ) -> tuple[str, tuple[str, ...]] | None:
        """Return ``(kind, labels)`` for *repo* from the repo inventory."""
        kinds = getattr(self, "_stitch_inventory_kinds_cache", None)
        if isinstance(kinds, dict) and repo in kinds:
            return kinds[repo]
        return None

    def _stitch_inventory_repos(self) -> dict[str, str] | None:
        """Return checkout paths by repo name and alias for the pane scope.

        Resolves through the same project inventory the collector uses,
        always including sidecars, so hydration is not limited to repos
        the displayed window happens to contain.
        """
        import os

        from sase.vcs_log.resolve import resolve_log_repos

        filters = getattr(self, "filters", None)
        project = getattr(filters, "project", None)
        try:
            resolved = resolve_log_repos(
                cwd=os.getcwd(),
                all_projects=project is None,
                project_scope=project,
                include_sidecars=True,
            )
        except Exception:  # noqa: BLE001 - fall back to the displayed result
            return None
        by_label: dict[str, str] = {}
        kinds: dict[str, tuple[str, tuple[str, ...]]] = {}
        for log_repo in resolved.repos:
            labels = tuple(dict.fromkeys((log_repo.name, *log_repo.aliases)))
            for label in (log_repo.name, *log_repo.aliases):
                by_label.setdefault(label, log_repo.path)
                by_label.setdefault(label.casefold(), log_repo.path)
            kinds[log_repo.name] = (log_repo.kind, labels)
            for alias in log_repo.aliases:
                kinds.setdefault(alias, (log_repo.kind, labels))
        self._stitch_inventory_kinds_cache = kinds
        return by_label

    def install_hydrated_row(self, payload: Any) -> ArtifactEntryTarget | None:
        """Store one fetched commit's facts without touching the display.

        The row is deliberately not injected into the displayed timeline:
        the link-follow Context step that follows builds a repo-and-day
        window whose re-collection fetches the commit through the normal
        collection path and reports ``SELECTED`` when it completes.
        """
        if not isinstance(payload, AggregatedCommitWire):
            return None
        remember = getattr(self, "remember_acquired_stitch_facts", None)
        if not callable(remember):
            return None
        kinds = getattr(self, "_stitch_inventory_kinds_cache", None)
        kind: str = "primary"
        labels: tuple[str, ...] = (payload.repo,)
        if isinstance(kinds, dict) and payload.repo in kinds:
            kind, labels = kinds[payload.repo]
        else:
            result = self.result
            if result is not None:
                for log_repo in result.repos:
                    if (
                        log_repo.name == payload.repo
                        or payload.repo in log_repo.aliases
                    ):
                        kind = log_repo.kind
                        labels = tuple(
                            dict.fromkeys((log_repo.name, *log_repo.aliases))
                        )
                        break
        cached = getattr(self, "_stitch_repo_info_cache", None)
        if isinstance(cached, dict) and payload.repo in cached:
            kind, labels = cached[payload.repo]
        remember(payload, repo_kind=kind, repo_labels=labels)
        return commit_row_target(payload)

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
        if result.commits or not self._collection_in_flight():
            # While a collection or query evaluation is still outstanding,
            # an empty intermediate result must not wipe the timeline:
            # dropping the selection to None reads as user navigation to
            # the link-trail watcher and cancels the very follow the load
            # belongs to. The load's own completion re-renders.
            self._selected_commit_index = timeline.update_result(result)
        pending = self._pending_entry_target
        if pending is not None:
            if timeline.select_entry_target(pending):
                self._selected_commit_index = timeline.selected_commit_index
                self._complete_entry_request(LinkRequestState.SELECTED)
            elif not self._collection_in_flight():
                self._complete_entry_request(LinkRequestState.MISSING)
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
        try:
            self.query_one("#stitches-detail", Static).update(
                self._build_detail(entry, diff_text, loading=loading)
            )
        except NoMatches:
            return

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
