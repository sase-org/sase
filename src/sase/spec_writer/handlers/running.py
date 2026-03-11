"""RUNNING field handlers for spec write operations."""

import os

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.running_field import (
    WorkspaceClaim,
    clean_orphaned_blank_lines,
    normalize_running_field_spacing,
)
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse


def handle_claim_workspace(request: SpecWriteRequest) -> SpecWriteResponse:
    """Claim a workspace by adding it to the RUNNING field."""
    workspace_num = request.params["workspace_num"]
    workflow = request.params["workflow"]
    pid = request.params["pid"]
    cl_name = request.params.get("cl_name")
    artifacts_timestamp = request.params.get("artifacts_timestamp")
    pinned = request.params.get("pinned", False)

    if not os.path.exists(request.project_file):
        return SpecWriteResponse(
            request_id=request.request_id,
            success=False,
            error="Project file does not exist",
        )

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")

        new_claim = WorkspaceClaim(
            workspace_num=workspace_num,
            workflow=workflow,
            cl_name=cl_name,
            pid=pid,
            artifacts_timestamp=artifacts_timestamp,
            pinned=pinned,
        )

        # Find RUNNING field
        running_field_idx = -1
        running_end_idx = -1

        for i, line in enumerate(lines):
            if line.startswith("RUNNING:"):
                running_field_idx = i
                # Find end of RUNNING field
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("  ") and (
                        lines[j].strip().startswith("#")
                        or lines[j].strip().startswith("|")
                    ):
                        running_end_idx = j
                    else:
                        if running_end_idx == -1:
                            running_end_idx = i
                        break
                else:
                    if running_end_idx == -1:
                        running_end_idx = i
                break

        if running_field_idx >= 0:
            # RUNNING field exists - add new claim
            insert_idx = running_end_idx + 1
            lines.insert(insert_idx, new_claim.to_line())
        else:
            # RUNNING field doesn't exist - create it at the beginning
            lines.insert(0, f"RUNNING:\n{new_claim.to_line()}\n")

        # Normalize blank lines around RUNNING field
        result_content = "\n".join(lines)
        result_content = normalize_running_field_spacing(result_content)

        # Write atomically
        cl_part = f" for {cl_name}" if cl_name else ""
        write_changespec_atomic(
            request.project_file,
            result_content,
            f"Claim workspace #{workspace_num} ({workflow}){cl_part}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_release_workspace(request: SpecWriteRequest) -> SpecWriteResponse:
    """Release a workspace by removing it from the RUNNING field."""
    workspace_num = request.params["workspace_num"]
    workflow = request.params.get("workflow")
    cl_name = request.params.get("cl_name")

    if not os.path.exists(request.project_file):
        return SpecWriteResponse(
            request_id=request.request_id,
            success=False,
            error="Project file does not exist",
        )

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            content = f.read()
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
                        continue
                    else:
                        has_remaining_claims = True
            else:
                in_running_field = False

            new_lines.append(line)

        # If RUNNING field is now empty, remove it entirely
        if running_field_idx >= 0 and not has_remaining_claims:
            del new_lines[running_field_idx]

        # Normalize blank lines
        result_content = "\n".join(new_lines)
        if has_remaining_claims:
            result_content = normalize_running_field_spacing(result_content)
        else:
            result_content = clean_orphaned_blank_lines(result_content)

        write_changespec_atomic(
            request.project_file,
            result_content,
            f"Release workspace #{workspace_num}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_update_running_cl_name(
    request: SpecWriteRequest,
) -> SpecWriteResponse:
    """Update the cl_name in RUNNING field entries."""
    old_cl_name = request.params["old_cl_name"]
    new_cl_name = request.params["new_cl_name"]

    if not os.path.exists(request.project_file):
        return SpecWriteResponse(
            request_id=request.request_id,
            success=False,
            error="Project file does not exist",
        )

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")

        new_lines: list[str] = []
        in_running_field = False
        updated = False

        for line in lines:
            if line.startswith("RUNNING:"):
                in_running_field = True
                new_lines.append(line)
                continue

            if in_running_field and line.startswith("  "):
                claim = WorkspaceClaim.from_line(line)
                if claim and claim.cl_name == old_cl_name:
                    updated_claim = WorkspaceClaim(
                        workspace_num=claim.workspace_num,
                        workflow=claim.workflow,
                        cl_name=new_cl_name,
                        pid=claim.pid,
                        artifacts_timestamp=claim.artifacts_timestamp,
                        pinned=claim.pinned,
                    )
                    new_lines.append(updated_claim.to_line())
                    updated = True
                    continue
            else:
                in_running_field = False

            new_lines.append(line)

        if not updated:
            return SpecWriteResponse(request_id=request.request_id, success=True)

        write_changespec_atomic(
            request.project_file,
            "\n".join(new_lines),
            f"Rename {old_cl_name} to {new_cl_name} in RUNNING field",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)
