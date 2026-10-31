"""Releasing workspace claims from the RUNNING field."""

import os

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.logs.workspace_claim_ledger import record_running_field_mutation
from sase.running_field._formatting import (
    clean_orphaned_blank_lines,
    normalize_running_field_spacing,
)
from sase.running_field._model import (
    ClaimResult,
    WorkspaceClaim,
)
from sase.telemetry.metrics import WORKSPACE_ACTIVE


def release_workspace(
    project_file: str,
    workspace_num: int,
    workflow: str | None = None,
    cl_name: str | None = None,
    caller_tag: str | None = None,
    *,
    expected_pid: int | None = None,
    artifacts_timestamp: str | None = None,
) -> ClaimResult:
    """Release a workspace by removing it from the RUNNING field.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        workspace_num: Workspace number to release
        workflow: Optional workflow name to match (for more specific release)
        cl_name: Optional Patch name to match (for more specific release)
        caller_tag: Optional short tag naming the calling code path, recorded
            in the workspace-claim mutation ledger.
        expected_pid: When set, refuse the release (no-op plus a ledger
            record) unless every matching RUNNING row still names this pid.
        artifacts_timestamp: When set, refuse the release unless the matching
            RUNNING row still names this artifacts identity.

    Returns:
        ClaimResult.  ``success`` is True on a successful release; on
        failure ``error`` carries the reason (missing project file, a pid
        mismatch when ``expected_pid`` is set, or a captured exception's
        ``repr``).
    """
    if not os.path.exists(project_file):
        return ClaimResult(
            success=False,
            error=f"project file does not exist: {project_file}",
        )

    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()

            matching = _matching_release_claims(
                content,
                workspace_num,
                workflow,
                cl_name,
                artifacts_timestamp=artifacts_timestamp,
            )
            if expected_pid is not None or artifacts_timestamp is not None:
                refused = _refuse_if_not_owned(
                    matching,
                    expected_pid=expected_pid,
                    artifacts_timestamp=artifacts_timestamp,
                    project_file=project_file,
                    workspace_num=workspace_num,
                    workflow=workflow,
                    cl_name=cl_name,
                    caller_tag=caller_tag,
                    content=content,
                )
                if refused is not None:
                    return refused

            if expected_pid is not None:
                from sase.core.agent_launch_claims import (
                    plan_checked_release_workspace_claim_from_content,
                )

                owner: dict[str, object] = {
                    "workspace_num": workspace_num,
                    "workflow": workflow or "",
                    "cl_name": cl_name or "",
                    "pid": expected_pid,
                }
                if artifacts_timestamp:
                    owner["artifacts_timestamp"] = artifacts_timestamp
                plan = plan_checked_release_workspace_claim_from_content(content, owner)
                outcome = dict(plan["outcome"])
                if not bool(outcome["success"]):
                    reason = outcome.get("error") or (
                        f"workspace #{workspace_num} claim ownership moved"
                    )
                    return _record_refused_release(
                        project_file=project_file,
                        workspace_num=workspace_num,
                        workflow=workflow,
                        cl_name=cl_name,
                        caller_tag=caller_tag,
                        content=content,
                        error=str(reason),
                        claim_pid=expected_pid,
                        artifacts_timestamp=artifacts_timestamp,
                    )
                result_content = str(plan["content"])
            else:
                from sase.core.agent_cleanup_execution import (
                    try_release_workspace_from_content,
                )

                rust_result = try_release_workspace_from_content(
                    content, workspace_num, workflow, cl_name
                )
                if rust_result is not None:
                    result_content = str(rust_result["content"])
                else:
                    lines = content.split("\n")
                    new_lines: list[str] = []
                    in_running_field = False
                    running_field_idx = -1
                    has_remaining_claims = False

                    for line in lines:
                        if line.startswith("RUNNING:"):
                            in_running_field = True
                            running_field_idx = len(new_lines)
                            new_lines.append(line)
                            continue

                        if in_running_field and line.startswith("  "):
                            claim = WorkspaceClaim.from_line(line)
                            if claim:
                                should_remove = claim.workspace_num == workspace_num
                                if workflow and claim.workflow != workflow:
                                    should_remove = False
                                if cl_name and claim.cl_name != cl_name:
                                    should_remove = False

                                if should_remove:
                                    continue
                                has_remaining_claims = True
                        else:
                            in_running_field = False

                        new_lines.append(line)

                    if running_field_idx >= 0 and not has_remaining_claims:
                        del new_lines[running_field_idx]

                    result_content = "\n".join(new_lines)
                    if has_remaining_claims:
                        result_content = normalize_running_field_spacing(result_content)
                    else:
                        result_content = clean_orphaned_blank_lines(result_content)

            # Write atomically
            write_patch_atomic(
                project_file,
                result_content,
                f"Release workspace #{workspace_num}",
            )
            released_claim = matching[0] if matching else None
            record_running_field_mutation(
                operation="release",
                project_file=project_file,
                workspace_num=workspace_num,
                success=True,
                before_content=content,
                after_content=result_content,
                workflow=workflow,
                cl_name=cl_name,
                artifacts_timestamp=(
                    released_claim.artifacts_timestamp if released_claim else None
                ),
                claim_pid=released_claim.pid if released_claim else None,
                caller_tag=caller_tag,
            )
            project = os.path.splitext(os.path.basename(project_file))[0]
            WORKSPACE_ACTIVE.labels(project=project).dec()
            return ClaimResult(success=True)
    except (OSError, BlockingIOError) as exc:
        return ClaimResult(success=False, error=repr(exc))


def _matching_release_claims(
    content: str,
    workspace_num: int,
    workflow: str | None,
    cl_name: str | None,
    *,
    artifacts_timestamp: str | None = None,
) -> list[WorkspaceClaim]:
    matching: list[WorkspaceClaim] = []
    in_running_field = False
    for line in content.split("\n"):
        if line.startswith("RUNNING:"):
            in_running_field = True
            continue
        if in_running_field and line.startswith("  "):
            claim = WorkspaceClaim.from_line(line)
            if not claim or claim.workspace_num != workspace_num:
                continue
            if workflow and claim.workflow != workflow:
                continue
            if cl_name and claim.cl_name != cl_name:
                continue
            if artifacts_timestamp and claim.artifacts_timestamp != artifacts_timestamp:
                continue
            matching.append(claim)
        elif in_running_field:
            in_running_field = False
    return matching


def _refuse_if_not_owned(
    matching: list[WorkspaceClaim],
    *,
    expected_pid: int | None,
    artifacts_timestamp: str | None,
    project_file: str,
    workspace_num: int,
    workflow: str | None,
    cl_name: str | None,
    caller_tag: str | None,
    content: str,
) -> ClaimResult | None:
    if not matching:
        owner = (
            f"pid {expected_pid}"
            if expected_pid is not None
            else f"artifacts {artifacts_timestamp}"
        )
        error = f"no RUNNING claim for workspace #{workspace_num} owned by {owner}"
        return _record_refused_release(
            project_file=project_file,
            workspace_num=workspace_num,
            workflow=workflow,
            cl_name=cl_name,
            caller_tag=caller_tag,
            content=content,
            error=error,
            claim_pid=None,
            artifacts_timestamp=artifacts_timestamp,
        )
    if expected_pid is not None:
        foreign = next((claim for claim in matching if claim.pid != expected_pid), None)
        if foreign is not None:
            error = (
                f"RUNNING row pid mismatch: claim pid {foreign.pid} "
                f"!= runner pid {expected_pid}"
            )
            return _record_refused_release(
                project_file=project_file,
                workspace_num=workspace_num,
                workflow=workflow,
                cl_name=cl_name,
                caller_tag=caller_tag,
                content=content,
                error=error,
                claim_pid=foreign.pid,
                artifacts_timestamp=foreign.artifacts_timestamp,
            )
    return None


def _record_refused_release(
    *,
    project_file: str,
    workspace_num: int,
    workflow: str | None,
    cl_name: str | None,
    caller_tag: str | None,
    content: str,
    error: str,
    claim_pid: int | None,
    artifacts_timestamp: str | None = None,
) -> ClaimResult:
    record_running_field_mutation(
        operation="release",
        project_file=project_file,
        workspace_num=workspace_num,
        success=False,
        before_content=content,
        after_content=content,
        workflow=workflow,
        cl_name=cl_name,
        artifacts_timestamp=artifacts_timestamp,
        claim_pid=claim_pid,
        error=error,
        caller_tag=caller_tag,
    )
    return ClaimResult(success=False, error=error)
