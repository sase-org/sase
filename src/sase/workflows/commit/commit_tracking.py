"""Post-commit tracking: diff capture, COMMITS entries, result markers, ChangeSpec."""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

from sase.output import print_status

if TYPE_CHECKING:
    from sase.vcs_provider._base import VCSProvider


def resolve_cl_name() -> str | None:
    """Resolve the CL name from env var or current branch."""
    cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    if cl_name:
        return cl_name
    try:
        from sase.workflows.utils import get_cl_name_from_branch

        return get_cl_name_from_branch()
    except Exception:
        return None


def resolve_project_file() -> str | None:
    """Resolve the project file path from env var or workspace detection."""
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if project_file:
        return project_file
    try:
        from sase.workflows.utils import (
            get_project_file_path,
            get_project_from_workspace,
        )

        project_name = get_project_from_workspace()
        if not project_name:
            return None
        return get_project_file_path(project_name)
    except Exception:
        return None


def capture_pre_commit_diff(
    provider: VCSProvider, cwd: str, cl_name: str | None
) -> str | None:
    """Capture VCS diff before committing and save it for the COMMITS entry.

    After the VCS commit the working-tree diff is empty, so this must run
    beforehand.  When ``SASE_ARTIFACTS_DIR`` is set (agent context), the
    diff is saved there.  Otherwise it falls back to
    ``~/.sase/diffs/<cl_name>-<timestamp>.diff`` so human CLI commits get
    diffs too.

    Returns the path to the saved diff file, or ``None`` on failure.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        diff_path = os.path.join(artifacts_dir, "commit_diff.diff")
    else:
        if not cl_name:
            return None
        from sase.core.time import generate_timestamp

        diffs_dir = os.path.expanduser("~/.sase/diffs")
        os.makedirs(diffs_dir, exist_ok=True)
        diff_path = os.path.join(diffs_dir, f"{cl_name}-{generate_timestamp()}.diff")

    try:
        ok, diff_text = provider.diff(cwd)  # type: ignore[union-attr]
    except Exception:
        return None
    if not ok or not diff_text:
        return None
    try:
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(diff_text)
        return diff_path
    except Exception:
        return None


def _commits_drawer_has_entry_id(
    project_file: str, cl_name: str, entry_id: str
) -> bool:
    """Return True if *cl_name*'s COMMITS drawer already contains *entry_id*."""
    try:
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    in_target = False
    in_commits = False
    pattern = re.compile(rf"^\s*\({re.escape(entry_id)}\)\s+")
    for line in lines:
        if line.startswith("NAME: "):
            in_target = line[6:].strip() == cl_name
            in_commits = False
            continue
        if not in_target:
            continue
        if line.startswith("COMMITS:"):
            in_commits = True
            continue
        if line.startswith(
            (
                "DESCRIPTION:",
                "PARENT:",
                "CL:",
                "STATUS:",
                "TEST TARGETS:",
                "KICKSTART:",
            )
        ):
            in_commits = False
            continue
        if in_commits and pattern.match(line):
            return True
    return False


def append_commits_entry(
    project_file: str | None,
    cl_name: str | None,
    payload: dict,
    method: str,
    diff_path: str | None,
    *,
    expected_entry_id: str | None = None,
) -> str | None:
    """Append a COMMITS entry after successful commit/proposal. Returns entry_id.

    When *expected_entry_id* is provided, the COMMITS drawer is scanned first
    for a line that begins with ``(<expected_entry_id>) ``; if found, that ID
    is returned without modifying the file (idempotent resume).
    """
    if not project_file or not cl_name or not os.path.isfile(project_file):
        return None

    if expected_entry_id and _commits_drawer_has_entry_id(
        project_file, cl_name, expected_entry_id
    ):
        return expected_entry_id

    # Build note + body from the commit message.
    # The header is the first line; everything after the first blank line is
    # the body.
    message = payload.get("message", "")
    parts = message.split("\n\n", 1)
    note = (parts[0].split("\n")[0]) or "Manual changes"
    body: list[str] | None = None
    if len(parts) > 1 and parts[1].strip():
        body = parts[1].splitlines()

    # For proposals, prepend workflow identifier if available
    if method == "create_proposal":
        who = os.environ.get("SASE_AGENT_WHO")
        if who:
            note = f"[{who}] {note}"

    chat_path = os.environ.get("SASE_AGENT_CHAT_PATH")

    # Compute display path for plan (replace $HOME with ~)
    plan_display: str | None = None
    raw_plan = os.environ.get("SASE_PLAN", "")
    if raw_plan:
        home = os.path.expanduser("~")
        plan_display = (
            raw_plan.replace(home, "~") if raw_plan.startswith(home) else raw_plan
        )

    from sase.workflows.commit_utils.entries import (
        add_commit_entry_with_id,
        add_proposed_commit_entry,
    )

    if method == "create_proposal":
        ok, entry_id = add_proposed_commit_entry(
            project_file=project_file,
            cl_name=cl_name,
            note=note,
            diff_path=diff_path,
            chat_path=chat_path,
            body=body,
            plan_path=plan_display,
        )
    else:
        ok, entry_id = add_commit_entry_with_id(
            project_file=project_file,
            cl_name=cl_name,
            note=note,
            diff_path=diff_path,
            chat_path=chat_path,
            body=body,
            plan_path=plan_display,
        )
    return entry_id if ok else None


def write_result_marker(
    method: str,
    payload: dict,
    diff_path: str | None,
    result: str | None,
    changespec_name: str | None,
    *,
    entry_id: str | None = None,
) -> None:
    """Write commit result to a marker file for xprompt post-steps."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    marker = {
        "method": method,
        "result": result,
        "message": payload.get("message", ""),
        "name": payload.get("name", ""),
        "bead_id": payload.get("bead_id", ""),
        "changespec_name": changespec_name,
        "entry_id": entry_id,
        "diff_path": diff_path,
    }
    marker_path = os.path.join(artifacts_dir, "commit_result.json")
    with open(marker_path, "w") as f:
        json.dump(marker, f)


def create_changespec(
    payload: dict,
    base_cl_name: str | None,
    parent_cl_name: str | None,
    reserved_name: str | None,
    cl_url: str | None,
) -> str | None:
    """Best-effort ChangeSpec creation after a successful PR flow."""
    try:
        from sase.workflows.utils import (
            get_project_file_path,
            get_project_from_workspace,
        )
        from sase.workspace_provider.changespec import (
            create_changespec_for_workflow,
        )

        project_name = get_project_from_workspace()
        if not project_name:
            print_status("Skipping ChangeSpec: could not detect project name.", "info")
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

        cs_name = create_changespec_for_workflow(
            project_name=project_name,
            project_file=project_file,
            checkout_target=checkout_target,
            branch_name=branch_name,
            prompt="",
            response="",
            workflow_name="sase_commit",
            cl_url=cl_url,
            cl_name=base_cl_name or payload.get("name"),
            commit_description=payload.get("message", ""),
            parent=parent_cl_name,
            bug=bug,
            reserved_name=reserved_name,
            status=status,
        )
        if cs_name:
            print_status(f"Created ChangeSpec: {cs_name}", "success")
        else:
            print_status("Skipping ChangeSpec: no new commits detected.", "info")
        return cs_name
    except Exception as exc:
        print_status(f"Skipping ChangeSpec: {exc}", "warning")
        return None


def cleanup_reservation(reserved_name: str | None) -> None:
    """Remove the reservation entry on VCS failure (best-effort)."""
    if not reserved_name:
        return
    try:
        from sase.workflows.commit.changespec_operations import remove_reservation
        from sase.workflows.utils import get_project_from_workspace

        project_name = get_project_from_workspace()
        if project_name:
            remove_reservation(project_name, reserved_name)
    except Exception:
        pass
