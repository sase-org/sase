"""Recovery path for checkpointed commit workflows."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from sase.output import print_status
from sase.telemetry.metrics import VCS_OPERATIONS
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow_types import RunResult

if TYPE_CHECKING:
    from sase.workflows.commit.workflow import CommitWorkflow


def resume_commit_workflow(
    workflow_type: type[CommitWorkflow],
    *,
    checkpoint_load: Callable[[], CommitCheckpoint | None],
    checkpoint_save: Callable[[CommitCheckpoint], str | None],
    checkpoint_delete: Callable[[], None],
    get_vcs_provider: Callable[[str], object],
    is_conflict_state: Callable[[object, str], bool],
) -> RunResult:
    """Resume a checkpoint after manual conflict resolution."""
    cp = checkpoint_load()
    if cp is None:
        print_status("No commit checkpoint found — nothing to resume", "error")
        return RunResult.FAILED

    wf = workflow_type(payload=cp.payload, method=cp.method)
    wf._base_cl_name = cp.base_cl_name
    wf._reserved_name = cp.reserved_name
    wf._parent_cl_name = cp.parent_cl_name
    wf._diff_path = cp.diff_path
    wf._cl_name = cp.cl_name
    wf._project_file = cp.project_file

    provider = get_vcs_provider(cp.cwd)
    provider_name = getattr(provider, "_provider_name", "unknown")

    if is_conflict_state(provider, cp.cwd):
        print_status(
            "Conflicts are still in progress — complete the rebase/merge "
            "first, then re-run sase commit --resume",
            "error",
        )
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="conflict",
        ).inc()
        return RunResult.CONFLICT

    expected_subject = (cp.payload.get("message", "").splitlines() or [""])[0].strip()
    actual_subject = _get_head_subject(provider, cp.cwd)
    if expected_subject and (
        actual_subject is None or actual_subject.strip() != expected_subject
    ):
        print_status(
            "Could not find the expected commit at HEAD (subject mismatch). "
            "Re-run sase commit from scratch.",
            "error",
        )
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="failed",
        ).inc()
        return RunResult.FAILED

    if (
        cp.method in ("create_commit", "create_pull_request")
        and "dispatch" not in cp.completed_steps
    ):
        try:
            ok, err = provider.finalize_commit(  # type: ignore[attr-defined]
                cp.payload, cp.cwd
            )
        except NotImplementedError:
            print_status(
                "finalize_commit not supported by this VCS provider; "
                "skipping push/amend and replaying tracking only.",
                "warning",
            )
        else:
            if not ok:
                print_status(f"finalize_commit failed: {err}", "error")
                VCS_OPERATIONS.labels(
                    provider=provider_name,
                    operation="commit_resume",
                    status="failed",
                ).inc()
                return RunResult.FAILED
        cp.completed_steps.append("dispatch")
        checkpoint_save(cp)

    if not wf._run_after_hook(cp):
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="failed",
        ).inc()
        return RunResult.FAILED

    _reconcile_changespec_from_project_file(wf, cp, checkpoint_save)

    tracking_result = wf._run_tracking_steps(cp, cp.dispatch_result)
    if tracking_result != RunResult.OK:
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="failed",
        ).inc()
        return tracking_result

    checkpoint_delete()
    VCS_OPERATIONS.labels(
        provider=provider_name,
        operation="commit_resume",
        status="ok",
    ).inc()
    return RunResult.OK


def _get_head_subject(provider: object, cwd: str) -> str | None:
    """Return the subject line of the HEAD commit, or None if unavailable."""
    try:
        ok, desc = provider.get_description(  # type: ignore[attr-defined]
            "HEAD", cwd, short=True
        )
    except NotImplementedError:
        return None
    except Exception:
        return None
    if not ok or not desc:
        return None
    return desc.strip().splitlines()[0] if desc.strip() else ""


def _reconcile_changespec_from_project_file(
    wf: CommitWorkflow,
    cp: CommitCheckpoint,
    checkpoint_save: Callable[[CommitCheckpoint], str | None],
) -> None:
    """Checkpoint a ChangeSpec already recorded by a prior attempt."""
    if wf._method != "create_pull_request":
        return
    if "create_changespec" in cp.completed_steps:
        return
    candidate = cp.cs_name or wf._reserved_name
    if not candidate or not wf._project_file:
        return
    if _changespec_name_in_project_file(wf._project_file, candidate):
        cp.cs_name = candidate
        cp.completed_steps.append("create_changespec")
        checkpoint_save(cp)


def _changespec_name_in_project_file(project_file: str, cl_name: str) -> bool:
    if not os.path.isfile(project_file):
        return False
    try:
        with open(project_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME: ") and line[6:].strip() == cl_name:
                    return True
    except OSError:
        return False
    return False
