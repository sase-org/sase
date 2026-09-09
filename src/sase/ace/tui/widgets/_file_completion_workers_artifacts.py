"""Path and commit inventory workers for prompt artifact-ref completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.artifact_refs import ArtifactRefContext
from sase.ace.tui.widgets._file_completion_context import FileCompletionContextMixin
from sase.ace.tui.widgets._file_completion_worker_results import (
    PromptCommitInventoryWorkerResult,
    PromptPathInventoryWorkerResult,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
)
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


class FileCompletionArtifactInventoryWorkerMixin(FileCompletionContextMixin):
    """Mixin providing path and commit inventory loading."""

    if TYPE_CHECKING:
        _file_completion_active: bool
        _completion_kind: str
        _prompt_path_snapshots: dict[str, PromptPathSnapshot]
        _prompt_path_inflight: set[str]
        _prompt_path_completion_directory_key: str | None
        _prompt_commit_snapshots: dict[str | None, PromptCommitSnapshot]
        _prompt_commit_inflight: set[str | None]
        _prompt_commit_worker_projects: dict[str, str | None]

        def _refresh_file_completion_from_cursor(self) -> None: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...

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

        def task() -> PromptPathInventoryWorkerResult:
            snapshot = (
                load_prompt_path_snapshot(directory_key)
                if previous is None
                else revalidate_prompt_path_snapshot(directory_key, previous)
            )
            return PromptPathInventoryWorkerResult(
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
        result: PromptPathInventoryWorkerResult,
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

        def task() -> PromptCommitInventoryWorkerResult:
            snapshot = (
                load_prompt_commit_snapshot(project, context)
                if previous is None
                else revalidate_prompt_commit_snapshot(previous, project, context)
            )
            return PromptCommitInventoryWorkerResult(
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
        result: PromptCommitInventoryWorkerResult,
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
