"""Releasing workspace claims from the RUNNING field."""

import os

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.core.agent_launch_claims import list_workspace_claims_from_content
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

    Returns:
        ClaimResult.  ``success`` is True on a successful release; on
        failure ``error`` carries the reason (missing project file or a
        captured exception's ``repr``).
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
                            # Check if this is the claim to remove
                            should_remove = claim.workspace_num == workspace_num
                            if workflow and claim.workflow != workflow:
                                should_remove = False
                            if cl_name and claim.cl_name != cl_name:
                                should_remove = False

                            if should_remove:
                                # Skip this line (remove the claim)
                                continue
                            else:
                                has_remaining_claims = True
                    else:
                        in_running_field = False

                    new_lines.append(line)

                # If RUNNING field is now empty, remove it entirely
                if running_field_idx >= 0 and not has_remaining_claims:
                    # Remove the RUNNING: line
                    del new_lines[running_field_idx]

                # Normalize blank lines (clean up extra blanks after RUNNING field or where it was)
                result_content = "\n".join(new_lines)
                if has_remaining_claims:
                    # Normalize spacing around remaining RUNNING field
                    result_content = normalize_running_field_spacing(result_content)
                else:
                    # Clean up orphaned blank lines where RUNNING field was removed
                    result_content = clean_orphaned_blank_lines(result_content)

            # Write atomically
            write_patch_atomic(
                project_file,
                result_content,
                f"Release workspace #{workspace_num}",
            )
            released_claim = next(
                (
                    item
                    for item in list_workspace_claims_from_content(content)
                    if item.workspace_num == workspace_num
                    and (workflow is None or item.workflow == workflow)
                    and (cl_name is None or item.cl_name == cl_name)
                ),
                None,
            )
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
