"""Identity-checked, handoff-aware VCS workspace release.

The ``#git:`` / ``#gh:`` post-prompt release step used to drop a RUNNING
row by workspace number, workflow, and ``cl_name`` — not pid — and then
unconditionally delete the checkout occupant marker. A turn that handed
off to a monitor, gate, proc shell, pipe, or plan proposal still ran that
step, so a follow-up in the same checkout could have its claim erased.

This helper is the shared implementation both VCS release steps call:
skip both mutations when the workspace was handed off; otherwise release
only a claim this run's pid still owns and clear only an occupant record
that names this run. Refusals are no-ops plus a ledger record.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sase.agent.pending_handoff import has_pending_handoff
from sase.logs.workspace_claim_ledger import record_running_field_mutation
from sase.running_field import release_workspace
from sase.workspace_provider.occupant import (
    clear_owned_occupant_record,
    read_occupant_record,
)

SKIP_HANDOFF = "handoff"
SKIP_PID_MISMATCH = "pid-mismatch"
SKIP_NO_MATCHING_CLAIM = "no-matching-claim"


@dataclass(frozen=True)
class VcsReleaseResult:
    """Outcome of one identity-checked VCS release attempt."""

    released: bool
    occupant_cleared: bool
    skip_reason: str | None = None


def release_vcs_workspace(
    *,
    project_file: str,
    workspace_num: int,
    workspace_dir: str,
    workflow_name: str,
    cl_name: str | None,
    caller_tag: str,
    runner_pid: int | None = None,
    artifacts_dir: str | None = None,
) -> VcsReleaseResult:
    """Release a VCS claim only when this run still owns the checkout.

    Args:
        project_file: ProjectSpec whose RUNNING field holds the claim.
        workspace_num: Numbered workspace to release.
        workspace_dir: Checkout whose occupant marker may be cleared.
        workflow_name: Workflow label of the VCS claim.
        cl_name: Optional Patch name of the VCS claim.
        caller_tag: Ledger tag (``git-release`` / ``gh-release``).
        runner_pid: Owning runner pid. Defaults to ``os.getppid()`` because
            the release step runs as a short-lived subprocess of the runner.
        artifacts_dir: Agent artifacts directory used to detect a mechanical
            handoff. Defaults to ``SASE_ARTIFACTS_DIR``.
    """
    if runner_pid is None:
        runner_pid = os.getppid()
    if artifacts_dir is None:
        artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")

    if has_pending_handoff(artifacts_dir):
        _record_refusal(
            project_file=project_file,
            workspace_num=workspace_num,
            workflow=workflow_name,
            cl_name=cl_name,
            caller_tag=caller_tag,
            claim_pid=runner_pid,
            error="workspace handed off; family still holds the checkout",
        )
        return VcsReleaseResult(
            released=False,
            occupant_cleared=False,
            skip_reason=SKIP_HANDOFF,
        )

    claim_result = release_workspace(
        project_file,
        workspace_num,
        workflow_name,
        cl_name,
        caller_tag,
        expected_pid=runner_pid,
    )
    skip_reason = None
    if not claim_result.success:
        skip_reason = _skip_reason_for_release_error(claim_result.error)

    occupant_cleared = _clear_owned_occupant(
        project_file=project_file,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        workflow_name=workflow_name,
        cl_name=cl_name,
        caller_tag=caller_tag,
        runner_pid=runner_pid,
    )
    return VcsReleaseResult(
        released=claim_result.success,
        occupant_cleared=occupant_cleared,
        skip_reason=skip_reason,
    )


def _clear_owned_occupant(
    *,
    project_file: str,
    workspace_num: int,
    workspace_dir: str,
    workflow_name: str,
    cl_name: str | None,
    caller_tag: str,
    runner_pid: int,
) -> bool:
    occupant = read_occupant_record(workspace_dir)
    if occupant is not None and occupant.pid != runner_pid:
        _record_refusal(
            project_file=project_file,
            workspace_num=workspace_num,
            workflow=workflow_name,
            cl_name=cl_name,
            caller_tag=caller_tag,
            claim_pid=occupant.pid,
            error=f"occupant record pid {occupant.pid} != runner pid {runner_pid}",
        )
        return False
    return clear_owned_occupant_record(workspace_dir, runner_pid)


def _skip_reason_for_release_error(error: str | None) -> str:
    if error and "pid mismatch" in error:
        return SKIP_PID_MISMATCH
    if error and "no RUNNING claim" in error:
        return SKIP_NO_MATCHING_CLAIM
    return "release-refused"


def _record_refusal(
    *,
    project_file: str,
    workspace_num: int,
    workflow: str,
    cl_name: str | None,
    caller_tag: str,
    claim_pid: int | None,
    error: str,
) -> None:
    content = _read_project_content(project_file)
    record_running_field_mutation(
        operation="release",
        project_file=project_file,
        workspace_num=workspace_num,
        success=False,
        before_content=content,
        after_content=content,
        workflow=workflow,
        cl_name=cl_name,
        claim_pid=claim_pid,
        error=error,
        caller_tag=caller_tag,
    )


def _read_project_content(project_file: str) -> str:
    try:
        with open(project_file, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
