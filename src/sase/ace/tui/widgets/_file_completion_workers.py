"""Background workers for manual prompt completion inventories.

Path, commit, and directive inventory schedule/apply helpers live in sibling
modules. This module keeps model-alias and VCS-repo workers, routes every
inventory worker result, and preserves the original import surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.ace.tui.widgets._file_completion_worker_results import (
    FinalizerInventoryWorkerResult,
    MachineInventoryWorkerResult,
    ModelCompletionCatalogWorkerResult,
    PromptCommitInventoryWorkerResult,
    PromptPathInventoryWorkerResult,
    VcsRepoCompletionWorkerResult,
    WaitBeadInventoryWorkerResult,
)
from sase.ace.tui.widgets._file_completion_workers_directives import (
    FileCompletionDirectiveInventoryWorkerMixin,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.model_alias_completion import MODEL_ALIAS_COMPLETION_KIND
from sase.ace.tui.widgets.model_explicit_completion import (
    MODEL_EXPLICIT_COMPLETION_KIND,
)
from sase.ace.tui.widgets.vcs_repo_completion import (
    VCS_REPO_COMPLETION_KIND,
    vcs_repo_completion_candidates,
)
from sase.xprompt.model_completion import build_model_completion_catalog
from sase.xprompt.vcs_repo_completion import (
    VcsRepoTrigger,
    fetch_repo_candidates,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_commit_inventory import PromptCommitSnapshot
    from sase.ace.tui.widgets.prompt_path_inventory import PromptPathSnapshot
    from sase.xprompt.vcs_repo_completion import VcsRepoFetchResult


class FileCompletionWorkerMixin(FileCompletionDirectiveInventoryWorkerMixin):
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
        _machine_inventory: tuple[dict[str, str], ...] | None
        _machine_available: bool
        _machine_inflight: bool
        _model_completion_catalog_loaded: bool
        _model_completion_catalog_available: bool
        _model_completion_catalog_inflight: bool
        _model_completion_catalog_request: tuple[str, str | None, str, int, str] | None
        _vim_mode: str

        def _clear_file_completion(
            self,
            *,
            clear_xprompt_arg_hint: bool = True,
        ) -> None: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _find_prompt_bar(self) -> Any: ...
        def _refresh_file_completion_from_cursor(self) -> None: ...
        def _update_file_completion_panel(self, token: str) -> None: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...
        def _wait_bead_project_key(self) -> str | None: ...

    def _schedule_model_completion_catalog_load(
        self,
        *,
        force: bool = False,
    ) -> None:
        """Coalesce one model catalog warm on a background worker."""
        if callable(
            getattr(self._prompt_app_or_none(), "model_completion_catalog", None)
        ):
            return
        if self._model_completion_catalog_inflight:
            return
        if (
            not force
            and self._model_completion_catalog_loaded
            and not self._model_completion_catalog_available
        ):
            return
        self._model_completion_catalog_inflight = True

        def task() -> ModelCompletionCatalogWorkerResult:
            try:
                rows = tuple(build_model_completion_catalog())
            except Exception:  # noqa: BLE001 - degrade rather than freeze the prompt.
                return ModelCompletionCatalogWorkerResult(rows=(), available=False)
            return ModelCompletionCatalogWorkerResult(rows=rows, available=True)

        self.run_worker(
            task,
            name="prompt-model-catalog",
            group="prompt-model-catalog",
            thread=True,
        )

    def _apply_model_completion_catalog_result(
        self,
        result: ModelCompletionCatalogWorkerResult,
    ) -> None:
        """Record catalog availability and refresh a matching open star menu."""
        request_current = self._model_completion_catalog_request_is_current()
        self._model_completion_catalog_loaded = True
        self._model_completion_catalog_available = result.available
        if (
            not self._file_completion_active
            or self._completion_kind
            not in {
                MODEL_ALIAS_COMPLETION_KIND,
                MODEL_EXPLICIT_COMPLETION_KIND,
            }
            or not request_current
        ):
            return
        self._refresh_file_completion_from_cursor()

    def _model_completion_catalog_request_is_current(self) -> bool:
        """Consume the latest alias catalog request and validate it still applies."""
        request = self._model_completion_catalog_request
        self._model_completion_catalog_request = None
        if request is None or not self.is_mounted:
            return False

        completion_kind, pane_id, text, cursor_offset, vim_mode = request
        if completion_kind != self._completion_kind:
            return False
        if pane_id != self.id:
            return False
        if text != self.text:
            return False
        if cursor_offset != self._absolute_offset(self.cursor_location):
            return False
        if vim_mode != self._vim_mode:
            return False

        try:
            bar = self._find_prompt_bar()
        except Exception:  # noqa: BLE001 - stale workers should degrade silently.
            return False
        active_text_area = getattr(bar, "active_text_area", None)
        if callable(active_text_area):
            try:
                if active_text_area() is not self:
                    return False
            except Exception:  # noqa: BLE001 - stale workers should degrade silently.
                return False
        return True

    def _schedule_vcs_repo_completion_fetch(self, trigger: VcsRepoTrigger) -> None:
        """Fetch repo candidates in a background worker with key dedupe."""
        key = (trigger.workflow, trigger.namespace)
        if key in self._vcs_repo_completion_inflight:
            return
        self._vcs_repo_completion_inflight.add(key)

        def task() -> VcsRepoCompletionWorkerResult:
            return VcsRepoCompletionWorkerResult(
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

    def _apply_vcs_repo_completion_result(
        self,
        worker_result: VcsRepoCompletionWorkerResult,
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
                if isinstance(result, PromptCommitInventoryWorkerResult):
                    self._apply_prompt_commit_inventory_result(result)
                    return

            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.worker.group == "prompt-path-inventory":
            if event.state == WorkerState.SUCCESS:
                result = event.worker.result
                if isinstance(result, PromptPathInventoryWorkerResult):
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
                if isinstance(result, WaitBeadInventoryWorkerResult):
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
                if isinstance(result, FinalizerInventoryWorkerResult):
                    self._apply_finalizer_inventory_result(result)
                    return
            if event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
                if self._finalizer_inventory is None:
                    self._apply_finalizer_inventory_result(
                        FinalizerInventoryWorkerResult(rows=(), available=False)
                    )
                return
            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.worker.group == "prompt-dispatch-machines":
            if event.state in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            ):
                self._machine_inflight = False
            if event.state == WorkerState.SUCCESS:
                result = event.worker.result
                if isinstance(result, MachineInventoryWorkerResult):
                    self._apply_machine_inventory_result(result)
                    return
            if event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
                if self._machine_inventory is None:
                    self._apply_machine_inventory_result(
                        MachineInventoryWorkerResult(rows=(), available=False)
                    )
                return
            handler = getattr(super(), "on_worker_state_changed", None)
            if callable(handler):
                handler(event)
            return

        if event.worker.group == "prompt-model-catalog":
            if event.state in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            ):
                self._model_completion_catalog_inflight = False
            if event.state == WorkerState.SUCCESS:
                result = event.worker.result
                if isinstance(result, ModelCompletionCatalogWorkerResult):
                    self._apply_model_completion_catalog_result(result)
                    return
            if event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
                if not self._model_completion_catalog_loaded:
                    self._apply_model_completion_catalog_result(
                        ModelCompletionCatalogWorkerResult(rows=(), available=False)
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
            if isinstance(result, VcsRepoCompletionWorkerResult):
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
