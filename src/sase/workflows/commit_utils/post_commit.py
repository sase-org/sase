"""Post-commit utility for appending COMMITS entries after commit/proposal creation.

Used by #commit and #propose xprompt workflows to record entries in the
ChangeSpec after CommitWorkflow (or the stop-hook) writes commit_result.json.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PostCommitResult:
    """Result of a post-commit entry append."""

    success: bool
    entry_id: str | None = None


def _find_best_diff_path(artifacts_dir: str) -> str | None:
    """Scan prompt_step_*.json markers for the best diff_path.

    Iterates all markers and returns the diff_path from the last marker
    (by filename sort order) that has one set.
    """
    best: str | None = None
    for marker_path in sorted(Path(artifacts_dir).glob("prompt_step_*.json")):
        try:
            with open(marker_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and data.get("diff_path"):
            best = str(data["diff_path"])
    return best


def _find_best_response_path(artifacts_dir: str) -> str | None:
    """Scan prompt_step_*.json markers for the best response_path."""
    best: str | None = None
    for marker_path in sorted(Path(artifacts_dir).glob("prompt_step_*.json")):
        try:
            with open(marker_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and data.get("response_path"):
            best = str(data["response_path"])
    return best


def append_post_commit_entry(
    *,
    mode: str,
) -> PostCommitResult:
    """Append a COMMITS entry after a successful commit or proposal creation.

    Reads environment variables and ``commit_result.json`` to determine what
    happened, then delegates to :func:`add_commit_entry` or
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

    # Load commit_result.json
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

    # Locate diff_path and response_path from prompt_step markers
    diff_path = _find_best_diff_path(artifacts_dir)
    response_path = _find_best_response_path(artifacts_dir)

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
