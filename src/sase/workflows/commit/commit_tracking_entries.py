"""COMMITS drawer updates after a successful commit or proposal."""

from __future__ import annotations

import os
import re

from sase.ace.patch.section_order import PROJECT_SPEC_SECTION_HEADERS
from sase.ace.patch.storage import is_stitch_section_header
from sase.workflows.commit.plan_paths import format_sase_plan_reference


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
        if is_stitch_section_header(line):
            in_commits = True
            continue
        if line.startswith(PROJECT_SPEC_SECTION_HEADERS):
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

    # Compute display path for plan.
    plan_display: str | None = None
    raw_plan = os.environ.get("SASE_PLAN", "")
    if raw_plan:
        plan_display = format_sase_plan_reference(raw_plan, repo_root=os.getcwd())

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
