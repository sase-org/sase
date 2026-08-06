"""Workflow-state helpers for the agent runner."""

from __future__ import annotations

import json
import os
from typing import Any

from sase.ace.tui.models._loaders._diff_path import diff_path_from_step_output


def is_workflow_noop(artifacts_dir: str) -> bool:
    """Check if a completed workflow launched zero agents.

    Reads agents_launched from workflow_state.json. A workflow that completed
    successfully but never invoked an LLM agent (e.g. a for-loop with an empty
    list) is considered a noop.
    """
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    return data.get("agents_launched", -1) == 0


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _committed_at_text(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return str(parsed) if parsed >= 0 else None
    return None


def read_commit_result_metadata(artifacts_dir: str | None) -> dict[str, str]:
    """Read commit_result.json and return workflow metadata fields."""
    if not artifacts_dir:
        return {}

    commit_result_path = os.path.join(artifacts_dir, "commit_result.json")
    try:
        with open(commit_result_path, encoding="utf-8") as f:
            commit_result = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    if not isinstance(commit_result, dict):
        return {}

    metadata: dict[str, str] = {}
    if message := _text(commit_result.get("message")):
        metadata["meta_commit_message"] = message
    if result := _text(commit_result.get("result")):
        metadata["meta_new_commit"] = result
    if cwd := _text(commit_result.get("cwd")):
        metadata["meta_commit_cwd"] = cwd
    if changespec := (
        _text(commit_result.get("changespec_name")) or _text(commit_result.get("name"))
    ):
        metadata["meta_changespec"] = changespec
    if diff_path := _text(commit_result.get("diff_path")):
        metadata["diff_path"] = diff_path
    if committed_at := _committed_at_text(commit_result.get("committed_at")):
        metadata["meta_commit_committed_at"] = committed_at
    return metadata


def _commit_result_list_record(item: dict[str, Any]) -> dict[str, str] | None:
    record: dict[str, str] = {}
    if message := _text(item.get("message")):
        record["message"] = message
    if sha := (_text(item.get("result")) or _text(item.get("commit_result"))):
        record["sha"] = sha
    if cwd := _text(item.get("cwd")):
        record["cwd"] = cwd
    if repo_name := _text(item.get("repo_name")):
        record["repo_name"] = repo_name
    if changespec_name := (
        _text(item.get("changespec_name")) or _text(item.get("commit_changespec_name"))
    ):
        record["changespec_name"] = changespec_name
    if diff_path := (
        _text(item.get("diff_path")) or _text(item.get("commit_diff_path"))
    ):
        record["diff_path"] = os.path.expanduser(diff_path)
    if committed_at := _committed_at_text(item.get("committed_at")):
        record["committed_at"] = committed_at
    return record or None


def read_commit_results_metadata(artifacts_dir: str | None) -> list[dict[str, str]]:
    """Read commit_results.json and return compact commit metadata records."""
    if not artifacts_dir:
        return []

    commit_results_path = os.path.join(artifacts_dir, "commit_results.json")
    try:
        with open(commit_results_path, encoding="utf-8") as f:
            commit_results = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    if not isinstance(commit_results, list):
        return []

    records: list[dict[str, str]] = []
    for item in commit_results:
        if not isinstance(item, dict):
            continue
        record = _commit_result_list_record(item)
        if record:
            records.append(record)
    return records


def extract_step_output_and_diff_path(
    artifacts_dir: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract step_output and diff_path from workflow_state.json.

    Reads the workflow state written by execute_workflow() and extracts:
    - step_output: the last completed step's output dict
    - diff_path: an explicit ``diff_path`` output field (searched backward
      through steps), falling back to commit_result.json's diff_path
    """
    commit_metadata = read_commit_result_metadata(artifacts_dir)
    commit_results = read_commit_results_metadata(artifacts_dir)
    commit_step_metadata: dict[str, Any] = {
        key: value for key, value in commit_metadata.items() if key != "diff_path"
    }
    if commit_results:
        commit_step_metadata["meta_commits"] = commit_results

    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        commit_diff_path = commit_metadata.get("diff_path")
        if commit_diff_path:
            commit_diff_path = os.path.expanduser(commit_diff_path)
        return commit_step_metadata or None, commit_diff_path

    if not isinstance(data, dict):
        commit_diff_path = commit_metadata.get("diff_path")
        if commit_diff_path:
            commit_diff_path = os.path.expanduser(commit_diff_path)
        return commit_step_metadata or None, commit_diff_path

    step_output: dict[str, Any] | None = None
    for step_data in reversed(data.get("steps", [])):
        output = step_data.get("output")
        if output and isinstance(output, dict):
            step_output = output
            break

    # Search backward through all steps for an explicit "diff_path" output
    # (embedded workflows may produce the diff in a non-last step).  Arbitrary
    # "path"-typed outputs (e.g. a #sshot screenshot) are NOT diffs and must
    # not be persisted into the done marker.
    diff_path: str | None = None
    for step_data in reversed(data.get("steps", [])):
        diff_path = diff_path_from_step_output(step_data.get("output"))
        if diff_path:
            break

    if commit_step_metadata:
        if step_output is None:
            step_output = commit_step_metadata
        else:
            step_output.update(commit_step_metadata)

    if not diff_path and commit_metadata.get("diff_path"):
        diff_path = commit_metadata["diff_path"]

    if diff_path:
        diff_path = os.path.expanduser(diff_path)

    return step_output, diff_path


def read_and_delete_marker(artifacts_dir: str, filename: str) -> dict[str, Any] | None:
    """Read a JSON marker file, delete it, and return parsed data.

    Returns None if the file doesn't exist or can't be parsed.
    """
    path = os.path.join(artifacts_dir, filename)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        os.unlink(path)
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
