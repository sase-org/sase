"""Post-commit utility for appending COMMITS entries after commit/proposal creation.

Called by CommitWorkflow after a successful commit or proposal to record the
entry in the ChangeSpec.  Reads ``commit_result.json`` (written by
CommitWorkflow) for the diff path and ``SASE_AGENT_CHAT_PATH`` for the chat
transcript path.
"""

import json
import os
from dataclasses import dataclass


@dataclass
class PostCommitResult:
    """Result of a post-commit entry append."""

    success: bool
    entry_id: str | None = None


def append_post_commit_entry(
    *,
    mode: str,
) -> PostCommitResult:
    """Append a COMMITS entry after a successful commit or proposal creation.

    Reads environment variables and ``commit_result.json`` to determine what
    happened, then delegates to :func:`add_commit_entry_with_id` or
    :func:`add_proposed_commit_entry`.

    Args:
        mode: Either ``"commit"`` or ``"proposal"``.

    Returns:
        A :class:`PostCommitResult` with ``success`` and optional ``entry_id``.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE", "")
    cl_name = os.environ.get("SASE_AGENT_CL_NAME", "")

    if not artifacts_dir or not project_file or not cl_name:
        return PostCommitResult(success=False)

    if not os.path.isfile(project_file):
        return PostCommitResult(success=False)

    # Load commit_result.json (written by CommitWorkflow._write_result_marker)
    result_path = os.path.join(artifacts_dir, "commit_result.json")
    if not os.path.isfile(result_path):
        return PostCommitResult(success=False)

    try:
        with open(result_path, encoding="utf-8") as f:
            commit_result = json.load(f)
    except (json.JSONDecodeError, OSError):
        return PostCommitResult(success=False)

    if not isinstance(commit_result, dict):
        return PostCommitResult(success=False)

    # Build note from commit message
    note = (commit_result.get("message") or "Agent changes").split("\n")[0]

    # diff_path comes from commit_result.json (captured pre-commit by
    # CommitWorkflow._capture_pre_commit_diff)
    diff_path = commit_result.get("diff_path")

    # chat_path comes from SASE_AGENT_CHAT_PATH env var
    response_path = os.environ.get("SASE_AGENT_CHAT_PATH")

    from sase.workflows.commit_utils.entries import (
        add_commit_entry_with_id,
        add_proposed_commit_entry,
    )

    if mode == "proposal":
        ok, entry_id = add_proposed_commit_entry(
            project_file=project_file,
            cl_name=cl_name,
            note=note,
            diff_path=diff_path,
            chat_path=response_path,
        )
        return PostCommitResult(success=ok, entry_id=entry_id)
    else:
        ok, entry_id = add_commit_entry_with_id(
            project_file=project_file,
            cl_name=cl_name,
            note=note,
            diff_path=diff_path,
            chat_path=response_path,
        )
        return PostCommitResult(success=ok, entry_id=entry_id)
