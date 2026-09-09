"""Best-effort Patch creation and reservation cleanup after a PR flow."""

from __future__ import annotations

import os

from sase.output import print_status


def create_patch(
    payload: dict,
    base_cl_name: str | None,
    parent_cl_name: str | None,
    reserved_name: str | None,
    pr_url: str | None,
) -> str | None:
    """Best-effort Patch creation after a successful PR flow."""
    try:
        from sase.workflows.utils import (
            get_project_file_path,
            get_project_from_workspace,
        )
        from sase.workspace_provider.patch import (
            create_patch_for_workflow,
        )

        project_name = get_project_from_workspace()
        if not project_name:
            print_status("Skipping Patch: could not detect project name.", "info")
            return None

        project_file = get_project_file_path(project_name)
        branch_name = payload.get("name", "")
        checkout_target = payload.get("checkout_target", "HEAD~1")

        bug_id = (
            payload.get("bug_id", "") or os.environ.get("SASE_BUG_ID", "")
        ).strip()
        bug = f"http://b/{bug_id}" if bug_id and bug_id != "0" else None

        status_map = {"wip": "WIP", "draft": "Draft", "ready": "Ready"}
        raw_status = (
            payload.get("status", "") or os.environ.get("SASE_PR_STATUS", "")
        ).strip()
        status = status_map.get(raw_status.lower(), "Draft")

        cs_name = create_patch_for_workflow(
            project_name=project_name,
            project_file=project_file,
            checkout_target=checkout_target,
            branch_name=branch_name,
            prompt="",
            response="",
            workflow_name="sase_commit",
            pr_url=pr_url,
            cl_name=base_cl_name or payload.get("name"),
            commit_description=payload.get("message", ""),
            parent=parent_cl_name,
            bug=bug,
            pr_origin="sase",
            reserved_name=reserved_name,
            status=status,
        )
        if cs_name:
            print_status(f"Created Patch: {cs_name}", "success")
        else:
            print_status("Skipping Patch: no new commits detected.", "info")
        return cs_name
    except Exception as exc:
        print_status(f"Skipping Patch: {exc}", "warning")
        return None


def cleanup_reservation(reserved_name: str | None) -> None:
    """Remove the reservation entry on VCS failure (best-effort)."""
    if not reserved_name:
        return
    try:
        from sase.workflows.commit.patch_operations import remove_reservation
        from sase.workflows.utils import get_project_from_workspace

        project_name = get_project_from_workspace()
        if project_name:
            remove_reservation(project_name, reserved_name)
    except Exception:
        pass
