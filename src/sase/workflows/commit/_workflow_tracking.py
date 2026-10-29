"""Post-dispatch tracking behavior for the commit workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sase.ace.deltas import refresh_deltas_after_commits_change
from sase.output import print_status
from sase.vcs_provider import get_vcs_provider
from sase.workflows.commit.bead_hooks import (
    BeadActionPolicyError,
    close_assigned_bead_after_commit,
)
from sase.workflows.commit.checkpoint import (
    CommitCheckpoint,
    checkpoint_save,
    ensure_operation_id,
)
from sase.workflows.commit.commit_tracking import (
    append_commits_entry,
    cleanup_reservation,
    create_patch,
    write_result_marker,
)
from sase.workflows.commit.workflow_publication import run_agent_publication_step
from sase.workflows.commit.workflow_support import (
    classify_dispatch_failure,
    log_commit_failed,
    resolve_head_commit_sha,
    resolve_head_tree_id,
)
from sase.workflows.commit.workflow_types import RunResult

_logger = logging.getLogger(__name__)


def save_checkpoint(checkpoint: CommitCheckpoint) -> str | None:
    """Save a commit checkpoint through the shared patchable persistence seam."""
    return checkpoint_save(checkpoint)


@dataclass(frozen=True)
class _UnpushedCommitPersistence:
    commit_sha: str
    checkpoint_path: str | None
    marker_written: bool

    @property
    def durable(self) -> bool:
        return bool(self.checkpoint_path) or self.marker_written

    @property
    def failure_details(self) -> list[str]:
        details: list[str] = []
        if not self.checkpoint_path:
            details.append("commit_state.json checkpoint write failed")
        if not self.marker_written:
            details.append("commit_results.json unpushed marker write failed")
        return details


def emit_stitch_step(step: str, *, state: str, detail: str | None = None) -> None:
    """Emit a stitch step on the finalizer step channel; never raises."""

    try:
        from sase.finalizers.steps import emit_step

        emit_step(step, state=state, detail=detail)
    except Exception:  # noqa: BLE001 - observability is best-effort
        pass


class CommitWorkflowTrackingMixin:
    """Methods that persist and publish results after VCS dispatch."""

    _method: str
    _payload: dict[str, Any]
    _base_cl_name: str | None
    _reserved_name: str | None
    _parent_cl_name: str | None
    _diff_path: str | None
    _cl_name: str | None
    _project_file: str | None

    def _unpushed_persistence_detail(self, record: _UnpushedCommitPersistence) -> str:
        if record.durable:
            missing = record.failure_details
            if not missing:
                return " Run `sase stitch create --resume` to retry the push."
            return (
                " Recovery evidence was partially recorded; "
                + "; ".join(missing)
                + ". Run `sase stitch create --resume` to retry from the durable "
                "checkpoint or marker."
            )
        return (
            " Automatic recovery evidence could not be recorded: "
            + "; ".join(record.failure_details)
            + ". The local commit remains in the repository; inspect it manually "
            "before retrying."
        )

    def _record_unpushed_commit_marker_if_present(
        self,
        cp: CommitCheckpoint,
        provider: object,
        dispatch_error: str | None,
    ) -> _UnpushedCommitPersistence | None:
        """Persist recoverable local commits when dispatch failed during push."""
        if self._method not in ("create_commit", "create_pull_request"):
            return None
        if classify_dispatch_failure(dispatch_error) != "push_failed":
            return None

        head_sha = resolve_head_commit_sha(provider, cp.cwd)
        if not head_sha or head_sha == (
            cp.pre_dispatch_revision or cp.primary_revision
        ):
            return None

        cp.commit_sha = head_sha
        cp.commit_tree = resolve_head_tree_id(provider, cp.cwd)
        cp.dispatch_result = head_sha
        cp.pushed = False
        cp.dispatch_error = dispatch_error
        ensure_operation_id(cp)
        checkpoint_path = save_checkpoint(cp)
        marker_written = write_result_marker(
            self._method,
            self._payload,
            self._diff_path,
            head_sha,
            cp.cs_name,
            commit_sha=cp.commit_sha,
            commit_tree=cp.commit_tree,
            commit_cwd=cp.cwd,
            pushed=False,
            dispatch_error=dispatch_error,
            operation_id=cp.operation_id,
        )
        return _UnpushedCommitPersistence(
            commit_sha=head_sha,
            checkpoint_path=checkpoint_path,
            marker_written=marker_written,
        )

    def _run_file_hooks(self, cp: CommitCheckpoint, provider: object) -> None:
        """Capture a committed revision once without gating the workflow."""
        if self._method not in ("create_commit", "create_pull_request"):
            return
        if "file_hooks" in cp.completed_steps:
            return
        from sase.config.file_hooks import load_file_hooks
        from sase.file_hooks.producer import produce_commit_file_hooks

        try:
            hooks = load_file_hooks()
        except Exception:
            produce_commit_file_hooks(
                repo_root=cp.cwd,
                commit_sha=cp.commit_sha,
                provider=provider,  # type: ignore[arg-type]
                project_file=cp.project_file,
                producer="commit",
            )
            cp.completed_steps.append("file_hooks")
            save_checkpoint(cp)
            return
        commit_sha = cp.commit_sha
        if hooks and not commit_sha:
            try:
                commit_sha = provider.revision_id(  # type: ignore[attr-defined]
                    "HEAD", cp.cwd
                )
            except Exception:
                _logger.warning(
                    "File-hook commit SHA lookup failed; continuing",
                    exc_info=True,
                )
        produce_commit_file_hooks(
            repo_root=cp.cwd,
            commit_sha=commit_sha,
            provider=provider,  # type: ignore[arg-type]
            project_file=cp.project_file,
            producer="commit",
            hooks=hooks,
        )
        cp.completed_steps.append("file_hooks")
        save_checkpoint(cp)

    def _repoint_reservation_after_resuffix(self) -> None:
        """Move the Patch reservation to a re-suffixed PR branch name.

        When the VCS dispatch renames the branch to escape a remote collision
        it records the new name in ``payload["name"]``.  Drop the now-stale
        reservation stub and adopt the new name as ``_reserved_name`` so the
        Patch is created under the branch that was actually pushed.
        """
        new_name = self._payload.get("name")
        if not new_name or new_name == self._reserved_name:
            return
        try:
            from sase.workflows.commit.patch_operations import remove_reservation
            from sase.workflows.utils import get_project_from_workspace

            project_name = get_project_from_workspace()
            if project_name and self._reserved_name:
                remove_reservation(project_name, self._reserved_name)
        except Exception:
            pass  # Best-effort cleanup; the Patch still uses the new name.
        self._reserved_name = new_name

    def _run_tracking_steps(
        self, cp: CommitCheckpoint, result: str | None
    ) -> RunResult:
        """Run the post-dispatch tracking steps and update *cp* as each completes.

        Steps already listed in ``cp.completed_steps`` are skipped so this
        helper is reusable from the resume path.  Returns ``RunResult.OK``
        when every applicable step succeeds.
        """
        if self._method == "create_pull_request":
            if "create_patch" in cp.completed_steps:
                cs_name = cp.cs_name
            else:
                cs_name = create_patch(
                    self._payload,
                    self._base_cl_name,
                    self._parent_cl_name,
                    self._reserved_name,
                    pr_url=result,
                )
                if cs_name is None:
                    cleanup_reservation(self._reserved_name)
                else:
                    cp.cs_name = cs_name
                    cp.completed_steps.append("create_patch")
                    save_checkpoint(cp)
        else:
            cs_name = cp.cs_name

        if "write_result_marker" not in cp.completed_steps:
            write_result_marker(
                self._method,
                self._payload,
                self._diff_path,
                result,
                cs_name,
                commit_sha=cp.commit_sha,
                commit_tree=cp.commit_tree,
                commit_cwd=cp.cwd,
                pushed=cp.pushed,
                dispatch_error=cp.dispatch_error,
                operation_id=cp.operation_id,
            )
            cp.completed_steps.append("write_result_marker")
            save_checkpoint(cp)

        publication_result = self._run_agent_publication_step(cp)
        if publication_result != RunResult.OK:
            return publication_result

        if self._method in ("create_commit", "create_proposal"):
            if "append_commits_entry" in cp.completed_steps:
                entry_id = cp.entry_id
            else:
                entry_id = append_commits_entry(
                    self._project_file,
                    self._cl_name,
                    self._payload,
                    self._method,
                    self._diff_path,
                    expected_entry_id=cp.entry_id,
                )
                if entry_id:
                    cp.entry_id = entry_id
                    cp.completed_steps.append("append_commits_entry")
                    save_checkpoint(cp)

            if entry_id and "final_result_marker" not in cp.completed_steps:
                write_result_marker(
                    self._method,
                    self._payload,
                    self._diff_path,
                    result,
                    cs_name,
                    entry_id=entry_id,
                    commit_sha=cp.commit_sha,
                    commit_tree=cp.commit_tree,
                    commit_cwd=cp.cwd,
                    pushed=cp.pushed,
                    dispatch_error=cp.dispatch_error,
                    operation_id=cp.operation_id,
                )
                cp.completed_steps.append("final_result_marker")
                save_checkpoint(cp)

            project_file = self._project_file or cp.project_file
            cl_name = self._cl_name or cp.cl_name
            if project_file and cl_name:
                refresh_deltas_after_commits_change(project_file, cl_name, cp.cwd)

        if (
            self._method in ("create_commit", "create_pull_request")
            and "close_bead" not in cp.completed_steps
        ):
            try:
                close_completed = close_assigned_bead_after_commit(
                    cp.payload,
                    cp.cwd,
                    method=self._method,
                    strict=True,
                )
            except BeadActionPolicyError as exc:
                log_commit_failed(self._method, "other")
                print_status(str(exc), "error")
                return RunResult.FAILED
            if close_completed:
                cp.completed_steps.append("close_bead")
                save_checkpoint(cp)

        return RunResult.OK

    def _run_agent_publication_step(self, cp: CommitCheckpoint) -> RunResult:
        """Publish sidecars after the first durable result marker exists."""
        published = run_agent_publication_step(
            cp,
            self._method,
            checkpoint_save=save_checkpoint,
            get_vcs_provider=get_vcs_provider,
        )
        return RunResult.OK if published else RunResult.FAILED
