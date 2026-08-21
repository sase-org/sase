"""Background workers for manual prompt completion inventories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.worker import Worker, WorkerState

from sase.artifact_refs import ArtifactRefContext
from sase.ace.tui.widgets._file_completion_context import FileCompletionContextMixin
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_commit_inventory import (
    PromptCommitSnapshot,
    load_prompt_commit_snapshot,
    prompt_commit_snapshot_expired,
    revalidate_prompt_commit_snapshot,
)
from sase.ace.tui.widgets.prompt_path_inventory import (
    PromptPathSnapshot,
    load_prompt_path_snapshot,
    prompt_path_directory_key,
    revalidate_prompt_path_snapshot,
)
from sase.ace.tui.widgets.vcs_repo_completion import (
    VCS_REPO_COMPLETION_KIND,
    vcs_repo_completion_candidates,
)
from sase.xprompt.vcs_repo_completion import (
    VcsRepoFetchResult,
    VcsRepoTrigger,
    fetch_repo_candidates,
)


@dataclass(frozen=True)
class _VcsRepoCompletionWorkerResult:
    """Result returned by a repository completion fetch worker."""

    workflow: str
    namespace: str
    result: VcsRepoFetchResult

    @property
    def key(self) -> tuple[str, str]:
        return (self.workflow, self.namespace)


@dataclass(frozen=True)
class _PromptPathInventoryWorkerResult:
    """Result returned by a prompt path inventory worker."""

    snapshot: PromptPathSnapshot
    changed: bool


@dataclass(frozen=True)
class _PromptCommitInventoryWorkerResult:
    """Result returned by a prompt commit inventory worker."""

    snapshot: PromptCommitSnapshot
    changed: bool


@dataclass(frozen=True)
class _WaitBeadInventoryWorkerResult:
    """Result returned by a prompt wait-bead inventory worker."""

    project_key: str
    rows: tuple[dict[str, str], ...]
    available: bool


@dataclass(frozen=True)
class _FinalizerInventoryWorkerResult:
    """Result returned by a prompt finalizer-catalog worker."""

    rows: tuple[dict[str, object], ...]
    available: bool


class FileCompletionWorkerMixin(FileCompletionContextMixin):
    """Mixin providing background inventory loading and result routing."""

    if TYPE_CHECKING:
        _file_completion_candidates: list[CompletionCandidate]
        _file_completion_index: int
        _file_completion_active: bool
        _completion_kind: str
        _vcs_repo_completion_key: tuple[str, str] | None
        _vcs_repo_completion_result: VcsRepoFetchResult | None
        _vcs_repo_completion_inflight: set[tuple[str, str]]
        _prompt_path_snapshots: dict[str, PromptPathSnapshot]
        _prompt_path_inflight: set[str]
        _prompt_path_completion_directory_key: str | None
        _prompt_commit_snapshots: dict[str | None, PromptCommitSnapshot]
        _prompt_commit_inflight: set[str | None]
        _prompt_commit_worker_projects: dict[str, str | None]
        _wait_bead_inventory: tuple[dict[str, str], ...] | None
        _wait_bead_available: bool
        _wait_bead_project: str | None
        _wait_bead_inflight: set[str]
        _finalizer_inventory: tuple[dict[str, object], ...] | None
        _finalizer_available: bool
        _finalizer_inflight: bool

        def _clear_file_completion(
            self,
            *,
            clear_xprompt_arg_hint: bool = True,
        ) -> None: ...

        def _refresh_file_completion_from_cursor(self) -> None: ...
        def _update_file_completion_panel(self, token: str) -> None: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...
        def _wait_bead_project_key(self) -> str | None: ...

    def _schedule_vcs_repo_completion_fetch(self, trigger: VcsRepoTrigger) -> None:
        """Fetch repo candidates in a background worker with key dedupe."""
        key = (trigger.workflow, trigger.namespace)
        if key in self._vcs_repo_completion_inflight:
            return
        self._vcs_repo_completion_inflight.add(key)

        def task() -> _VcsRepoCompletionWorkerResult:
            return _VcsRepoCompletionWorkerResult(
                workflow=trigger.workflow,
                namespace=trigger.namespace,
                result=fetch_repo_candidates(trigger.workflow, trigger.namespace),
            )

        self.run_worker(
            task,
            name=f"prompt-vcs-repo:{trigger.workflow}:{trigger.namespace}",
            group="prompt-vcs-repo",
            thread=True,
        )

    def _prompt_path_directory_key(self, directory: str = "") -> str:
        """Resolve a caller-visible prompt directory to its cache key."""
        return prompt_path_directory_key(self.text, directory)

    def _get_warm_prompt_path_snapshot(
        self,
        directory_key: str,
    ) -> PromptPathSnapshot | None:
        """Return a snapshot using a pure in-memory lookup."""
        return self._prompt_path_snapshots.get(directory_key)

    def _open_prompt_path_directory(
        self,
        directory: str,
    ) -> PromptPathSnapshot | None:
        """Mark a menu directory active and revalidate it off-thread."""
        directory_key = self._prompt_path_directory_key(directory)
        self._prompt_path_completion_directory_key = directory_key
        snapshot = self._get_warm_prompt_path_snapshot(directory_key)
        self._schedule_prompt_path_inventory_load(directory_key, snapshot)
        return snapshot

    def _schedule_prompt_path_inventory_load(
        self,
        directory_key: str,
        previous: PromptPathSnapshot | None = None,
    ) -> None:
        """Coalesce one directory revalidation on a background worker."""
        if directory_key in self._prompt_path_inflight:
            return
        self._prompt_path_inflight.add(directory_key)

        def task() -> _PromptPathInventoryWorkerResult:
            snapshot = (
                load_prompt_path_snapshot(directory_key)
                if previous is None
                else revalidate_prompt_path_snapshot(directory_key, previous)
            )
            return _PromptPathInventoryWorkerResult(
                snapshot=snapshot,
                changed=snapshot is not previous,
            )

        self.run_worker(
            task,
            name=f"prompt-path-inventory:{directory_key}",
            group="prompt-path-inventory",
            thread=True,
        )

    def _apply_prompt_path_inventory_result(
        self,
        result: _PromptPathInventoryWorkerResult,
    ) -> None:
        """Store a worker result and refresh the matching open menu."""
        snapshot = result.snapshot
        self._prompt_path_snapshots[snapshot.directory_key] = snapshot
        if not result.changed:
            return
        if (
            not self._file_completion_active
            or self._completion_kind != ARTIFACT_REF_COMPLETION_KIND
            or self._prompt_path_completion_directory_key != snapshot.directory_key
        ):
            return
        self._refresh_file_completion_from_cursor()

    def _schedule_prompt_commit_inventory_load(
        self,
        project: str | None,
        context: ArtifactRefContext,
        previous: PromptCommitSnapshot | None = None,
    ) -> None:
        """Coalesce one target-project commit revalidation off the UI thread."""
        if project in self._prompt_commit_inflight:
            return
        if previous is not None and not prompt_commit_snapshot_expired(previous):
            return
        self._prompt_commit_inflight.add(project)
        # One worker per project is in flight at a time, so the project keys the
        # name uniquely and a finished worker can never retire a live one.
        worker_name = f"prompt-commit-inventory:{'' if project is None else project}"
        self._prompt_commit_worker_projects[worker_name] = project

        def task() -> _PromptCommitInventoryWorkerResult:
            snapshot = (
                load_prompt_commit_snapshot(project, context)
                if previous is None
                else revalidate_prompt_commit_snapshot(previous, project, context)
            )
            return _PromptCommitInventoryWorkerResult(
                snapshot=snapshot,
                changed=snapshot is not previous,
            )

        self.run_worker(
            task,
            name=worker_name,
            group="prompt-commit-inventory",
            thread=True,
        )

    def _apply_prompt_commit_inventory_result(
        self,
        result: _PromptCommitInventoryWorkerResult,
    ) -> None:
        """Store a commit snapshot and refresh only its matching open menu."""
        snapshot = result.snapshot
        self._prompt_commit_snapshots[snapshot.project] = snapshot
        if not result.changed:
            return
        context = self._get_artifact_ref_completion_context()
        if (
            not self._file_completion_active
            or self._completion_kind != ARTIFACT_REF_COMPLETION_KIND
            or context is None
            or context.stage != "payload"
            or (context.kind or "").casefold() != "commit"
            or self._xprompt_arg_assist_project_from_text() != snapshot.project
        ):
            return
        self._refresh_file_completion_from_cursor()

    def _schedule_wait_bead_inventory_load(self, project_key: str) -> None:
        """Coalesce one bead-store read on a background worker."""
        if project_key in self._wait_bead_inflight:
            return
        self._wait_bead_inflight.add(project_key)

        def task() -> _WaitBeadInventoryWorkerResult:
            from sase.ace.tui.models.wait_bead_catalog import raw_wait_bead_inventory

            try:
                rows, available = raw_wait_bead_inventory(project_key)
            except Exception:  # noqa: BLE001 - degrade rather than freeze the prompt.
                rows, available = (), False
            return _WaitBeadInventoryWorkerResult(
                project_key=project_key,
                rows=rows,
                available=available,
            )

        self.run_worker(
            task,
            name=f"prompt-wait-beads:{project_key}",
            group="prompt-wait-beads",
            thread=True,
        )

    def _apply_wait_bead_inventory_result(
        self,
        result: _WaitBeadInventoryWorkerResult,
    ) -> None:
        """Store a warm bead inventory and refresh a matching open menu."""
        self._wait_bead_inventory = result.rows
        self._wait_bead_available = result.available
        self._wait_bead_project = result.project_key
        if not self._file_completion_active or self._completion_kind != "directive_arg":
            return
        if self._wait_bead_project_key() != result.project_key:
            return
        self._refresh_file_completion_from_cursor()

    def on_mount(self) -> None:
        """Warm the finalizer catalog as soon as a prompt pane is live."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._schedule_finalizer_inventory_load()

    def _prompt_app_or_none(self) -> object | None:
        """Return the hosting app when one is active."""
        try:
            return self.app
        except Exception:
            return None

    def _schedule_finalizer_inventory_load(self) -> None:
        """Coalesce one finalizer-config replay on a background worker."""
        if callable(getattr(self._prompt_app_or_none(), "finalizer_inventory", None)):
            return
        if self._finalizer_inflight:
            return
        self._finalizer_inflight = True

        def task() -> _FinalizerInventoryWorkerResult:
            from sase.finalizers.catalog import build_finalizer_completion_catalog

            try:
                catalog = build_finalizer_completion_catalog()
            except Exception:  # noqa: BLE001 - degrade rather than freeze the prompt.
                return _FinalizerInventoryWorkerResult(rows=(), available=False)
            if not catalog.ok:
                return _FinalizerInventoryWorkerResult(rows=(), available=False)
            return _FinalizerInventoryWorkerResult(
                rows=catalog.wire_entries(),
                available=True,
            )

        self.run_worker(
            task,
            name="prompt-finalizers",
            group="prompt-finalizers",
            thread=True,
        )

    def _apply_finalizer_inventory_result(
        self,
        result: _FinalizerInventoryWorkerResult,
    ) -> None:
        """Store a warm catalog and refresh a still-current ``%final`` menu."""
        self._finalizer_inventory = result.rows
        self._finalizer_available = result.available
        if not self._file_completion_active or self._completion_kind != "directive_arg":
            return
        clause_ctx = self._directive_clause_at_cursor()
        if clause_ctx is None:
            return
        from sase.ace.tui.widgets.directive_completion import (
            clause_needs_finalizer_inventory,
        )

        _row, clause = clause_ctx
        if not clause_needs_finalizer_inventory(clause):
            return
        self._refresh_file_completion_from_cursor()

    def _apply_vcs_repo_completion_result(
        self,
        worker_result: _VcsRepoCompletionWorkerResult,
    ) -> None:
        """Refresh an active repo menu from a completed worker result."""
        trigger = self._get_vcs_repo_trigger()
        if (
            trigger is None
            or (trigger.workflow, trigger.namespace) != worker_result.key
        ):
            return
        if (
            not self._file_completion_active
            or self._completion_kind != VCS_REPO_COMPLETION_KIND
        ):
            return

        candidates, used_placeholder = vcs_repo_completion_candidates(
            worker_result.result,
            trigger.query,
            trigger.namespace,
        )
        if not candidates and not used_placeholder:
            self._clear_file_completion()
            return

        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].name
        self._vcs_repo_completion_key = worker_result.key
        self._vcs_repo_completion_result = worker_result.result
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        if previous is not None:
            for i, candidate in enumerate(candidates):
                if candidate.name == previous:
                    self._file_completion_index = i
                    break
        self._update_file_completion_panel(trigger.query)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle completion inventory worker results."""
        if event.worker.group == "prompt-commit-inventory":
            # Pending and running transitions must leave the inflight marker in
            # place, or the loading row vanishes and every keystroke spawns
            # another git scan for the same project.
            if event.state in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            ):
                project = self._prompt_commit_worker_projects.pop(
                    event.worker.name,
                    None,
                )
                self._prompt_commit_inflight.discard(project)
            if event.state == WorkerState.SUCCESS:
                result = event.worker.result
                if isinstance(result, _PromptCommitInventoryWorkerResult):
                    self._apply_prompt_commit_inventory_result(result)
                    return

            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.worker.group == "prompt-path-inventory":
            if event.state == WorkerState.SUCCESS:
                result = event.worker.result
                if isinstance(result, _PromptPathInventoryWorkerResult):
                    directory_key = result.snapshot.directory_key
                    self._prompt_path_inflight.discard(directory_key)
                    self._apply_prompt_path_inventory_result(result)
                    return
            elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
                directory_key = event.worker.name.removeprefix("prompt-path-inventory:")
                self._prompt_path_inflight.discard(directory_key)

            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.worker.group == "prompt-wait-beads":
            if event.state in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            ):
                project_key = event.worker.name.removeprefix("prompt-wait-beads:")
                self._wait_bead_inflight.discard(project_key)
            if event.state == WorkerState.SUCCESS:
                result = event.worker.result
                if isinstance(result, _WaitBeadInventoryWorkerResult):
                    self._apply_wait_bead_inventory_result(result)
                    return
            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.worker.group == "prompt-finalizers":
            if event.state in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            ):
                self._finalizer_inflight = False
            if event.state == WorkerState.SUCCESS:
                result = event.worker.result
                if isinstance(result, _FinalizerInventoryWorkerResult):
                    self._apply_finalizer_inventory_result(result)
                    return
            if event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
                if self._finalizer_inventory is None:
                    self._apply_finalizer_inventory_result(
                        _FinalizerInventoryWorkerResult(rows=(), available=False)
                    )
                return
            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.worker.group != "prompt-vcs-repo":
            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, _VcsRepoCompletionWorkerResult):
                self._vcs_repo_completion_inflight.discard(result.key)
                self._apply_vcs_repo_completion_result(result)
                return
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            # The key is encoded in the worker name after the first prefix.
            suffix = event.worker.name.removeprefix("prompt-vcs-repo:")
            workflow, sep, namespace = suffix.partition(":")
            if sep:
                self._vcs_repo_completion_inflight.discard((workflow, namespace))

        handler = getattr(super(), "on_worker_state_changed", None)
        if callable(handler):
            handler(event)
