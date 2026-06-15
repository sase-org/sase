"""Agent metadata and follow-up artifact helpers."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.artifacts import create_artifacts_directory
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    AGENT_FAMILY_ROLE_FIELD,
    PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
    PLAN_CHAIN_ROOT_FIELD,
    agent_family_base,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
    is_plan_chain_artifact_meta,
)

EPISODE_TRACE_MARKER = "episode_trace.json"
EPISODE_TRACE_SCHEMA_VERSION = 1


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as f:
            loaded = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _unique_sorted_strings(values: list[Any]) -> list[str]:
    return sorted({value for value in values if isinstance(value, str) and value})


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _first_string(*values: Any) -> str | None:
    for value in values:
        candidate = _string(value)
        if candidate is not None:
            return candidate
    return None


def _existing_artifact_path(artifacts_path: Path, filename: str) -> str | None:
    path = artifacts_path / filename
    return str(path) if path.exists() else None


def _compact_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, value in sorted(payload.items()):
        if value is None or value == "" or value == []:
            continue
        compacted[key] = value
    return compacted


def write_episode_trace_marker(
    artifacts_dir: str,
    *,
    chat_path: str | None = None,
    plan_path: str | None = None,
    root_timestamp: str | None = None,
    update_index: bool = True,
) -> bool:
    """Write stable episodic-memory linkage hints for an artifact directory."""

    artifacts_path = Path(artifacts_dir)
    trace_path = artifacts_path / EPISODE_TRACE_MARKER
    existing = _read_json_object(trace_path)
    meta = _read_json_object(artifacts_path / "agent_meta.json")
    done = _read_json_object(artifacts_path / "done.json")
    plan_marker = _read_json_object(artifacts_path / "plan_path.json")

    role_suffix = _first_string(meta.get("role_suffix"))
    agent_name = _first_string(meta.get("name"), done.get("name"))
    family_name = _first_string(
        meta.get(AGENT_FAMILY_FIELD),
        meta.get("workflow_name"),
        agent_family_base(agent_name),
    )
    agent_role = _first_string(
        meta.get(AGENT_FAMILY_ROLE_FIELD),
        agent_family_role_for_suffix(role_suffix),
    )
    trace_root_timestamp = _first_string(
        root_timestamp,
        os.environ.get("SASE_AGENT_ROOT_TIMESTAMP"),
        meta.get("root_timestamp"),
        meta.get("retry_chain_root_timestamp"),
        done.get("retry_chain_root_timestamp"),
        existing.get("root_timestamp"),
    )

    payload: dict[str, Any] = {
        "schema_version": EPISODE_TRACE_SCHEMA_VERSION,
        "artifact_timestamp": artifacts_path.name,
        "agent_name": agent_name,
        "agent_family": family_name,
        "agent_role": agent_role,
        "role_suffix": role_suffix,
        "run_started_at": _first_string(meta.get("run_started_at")),
        "parent_timestamp": _first_string(
            meta.get("parent_timestamp"),
            meta.get(PLAN_CHAIN_PARENT_TIMESTAMP_FIELD),
        ),
        "parent_agent_timestamp": _first_string(meta.get("parent_agent_timestamp")),
        "root_timestamp": trace_root_timestamp,
        "chat_path": _first_string(
            chat_path,
            done.get("response_path"),
            meta.get("chat_path"),
            existing.get("chat_path"),
        ),
        "plan_path": _first_string(
            plan_path,
            plan_marker.get("plan_path"),
            meta.get("plan_path"),
            done.get("plan_path"),
            existing.get("plan_path"),
        ),
        "sdd_prompt_path": _first_string(meta.get("sdd_prompt_path")),
        "sdd_plan_path": _first_string(meta.get("sdd_plan_path")),
        "question_request_path": _first_string(meta.get("question_request_path")),
        "question_response_path": _first_string(meta.get("question_response_path")),
        "question_session_id": _first_string(meta.get("question_session_id")),
        "retry_of_timestamp": _first_string(meta.get("retry_of_timestamp")),
        "retried_as_timestamp": _first_string(
            meta.get("retried_as_timestamp"),
            done.get("retried_as_timestamp"),
        ),
        "retry_chain_root_timestamp": _first_string(
            meta.get("retry_chain_root_timestamp"),
            done.get("retry_chain_root_timestamp"),
        ),
        "retry_error_category": _first_string(
            meta.get("retry_error_category"),
            done.get("retry_error_category"),
        ),
        "feedback_paths": _unique_sorted_strings(
            [
                _existing_artifact_path(artifacts_path, "plan_feedback.jsonl"),
                *_unique_sorted_strings([existing.get("feedback_path")]),
                *_string_list(existing.get("feedback_paths")),
            ]
        ),
        "qa_paths": _unique_sorted_strings(
            [
                _existing_artifact_path(artifacts_path, "qa_log.jsonl"),
                *_unique_sorted_strings([existing.get("qa_path")]),
                *_string_list(existing.get("qa_paths")),
            ]
        ),
        "changespec_names": _unique_sorted_strings(
            [
                meta.get("changespec_name"),
                meta.get("cl_name"),
                meta.get("commit_changespec_name"),
                done.get("cl_name"),
                *_string_list(existing.get("changespec_names")),
            ]
        ),
        "bead_ids": _unique_sorted_strings(
            [
                meta.get("bead_id"),
                meta.get("epic_bead_id"),
                meta.get("phase_bead_id"),
                meta.get("legend_bead_id"),
                *_string_list(existing.get("bead_ids")),
            ]
        ),
    }
    compacted = _compact_trace_payload(payload)

    if compacted == existing:
        return False

    try:
        artifacts_path.mkdir(parents=True, exist_ok=True)
        with trace_path.open("w", encoding="utf-8") as f:
            json.dump(compacted, f, indent=2, sort_keys=True)
            f.write("\n")
        if update_index:
            update_agent_artifact_index_for_marker_mutation(artifacts_dir)
        return True
    except OSError:
        return False


def append_meta_list_field(artifacts_dir: str, key: str, value: Any) -> None:
    """Read agent_meta.json, append *value* to the list at *key*, and write back."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        existing = meta.get(key)
        if isinstance(existing, list):
            existing.append(value)
        else:
            meta[key] = [value]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        write_episode_trace_marker(artifacts_dir, update_index=False)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def update_meta_field(artifacts_dir: str, key: str, value: Any) -> None:
    """Read agent_meta.json, set a single key, and write it back."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta[key] = value
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        write_episode_trace_marker(artifacts_dir, update_index=False)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def update_meta_suffix(artifacts_dir: str, suffix: str) -> None:
    """Read agent_meta.json, set role_suffix, and write it back."""
    canonical_suffix = canonical_plan_chain_suffix(suffix) or suffix
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["role_suffix"] = canonical_suffix
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        write_episode_trace_marker(artifacts_dir, update_index=False)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def promote_to_workflow(
    artifacts_dir: str,
    base_name: str,
    role_suffix: str,
) -> None:
    """Retroactively mark the initial agent as a plan-chain family root."""
    canonical_suffix = canonical_plan_chain_suffix(role_suffix) or role_suffix
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["name"] = base_name
        meta["workflow_name"] = base_name
        meta[PLAN_CHAIN_ROOT_FIELD] = True
        meta[AGENT_FAMILY_FIELD] = base_name
        meta[AGENT_FAMILY_ROLE_FIELD] = "root"
        meta["role_suffix"] = canonical_suffix
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        write_episode_trace_marker(artifacts_dir, update_index=False)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def create_followup_artifacts(
    project_name: str,
    base_meta: dict[str, Any],
    suffix: str,
    prev_artifacts_timestamp: str,
    *,
    workspace_num: int | None = None,
    agent_name_override: str | None = None,
    workflow_name: str | None = None,
    agent_family_role: str | None = None,
    relationships: dict[str, Any] | None = None,
) -> str:
    """Create a new timestamped artifacts directory for a follow-up agent.

    Inherits metadata fields from the previous agent's meta and adds
    role_suffix and parent_timestamp.
    """
    new_artifacts_dir = create_artifacts_directory("ace-run", project_name=project_name)
    canonical_suffix = canonical_plan_chain_suffix(suffix) or suffix

    followup_meta: dict[str, Any] = {"pid": os.getpid()}
    for key in (
        "model",
        "llm_provider",
        "vcs_provider",
        # Inherit the workspace the parent ran in: follow-up agents run in the
        # same workspace, and persisting it lets the TUI resolve the live diff
        # directly from agent_meta.json instead of re-deriving the path.
        "workspace_dir",
        "name",
        "approve",
        "changespec_name",
        "cl_name",
        "bead_id",
        "epic_bead_id",
        "phase_bead_id",
        "legend_bead_id",
    ):
        if base_meta.get(key):
            followup_meta[key] = base_meta[key]
    if agent_name_override is not None:
        followup_meta["name"] = agent_name_override
    if workflow_name is not None:
        followup_meta["workflow_name"] = workflow_name
    followup_meta["role_suffix"] = canonical_suffix
    family_name = (
        workflow_name
        or (
            str(base_meta[AGENT_FAMILY_FIELD])
            if base_meta.get(AGENT_FAMILY_FIELD)
            else None
        )
        or agent_family_base(agent_name_override)
    )
    if family_name:
        followup_meta[AGENT_FAMILY_FIELD] = family_name
    family_role = agent_family_role or agent_family_role_for_suffix(canonical_suffix)
    if family_role:
        followup_meta[AGENT_FAMILY_ROLE_FIELD] = family_role
    followup_meta["parent_timestamp"] = prev_artifacts_timestamp
    if is_plan_chain_artifact_meta(followup_meta):
        followup_meta[PLAN_CHAIN_PARENT_TIMESTAMP_FIELD] = prev_artifacts_timestamp
    if workspace_num is not None:
        followup_meta["workspace_num"] = workspace_num
    followup_meta["run_started_at"] = datetime.now(UTC).isoformat()
    if relationships:
        for key, value in relationships.items():
            if value or (isinstance(value, bool) and value is not None):
                followup_meta[key] = value

    with open(
        os.path.join(new_artifacts_dir, "agent_meta.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(followup_meta, f, indent=2)

    # Write initial workflow_state.json so the TUI can merge follow-up agents
    # as WORKFLOW entries immediately, before WorkflowExecutor overwrites it.
    initial_state: dict[str, object] = {
        "workflow_name": "run",
        "status": "running",
        "current_step_index": 0,
        "steps": [],
        "context": {"cl_name": followup_meta.get("name", "")},
        "artifacts_dir": new_artifacts_dir,
        "pid": os.getpid(),
        "appears_as_agent": True,
    }
    with open(
        os.path.join(new_artifacts_dir, "workflow_state.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(initial_state, f, indent=2)

    write_episode_trace_marker(new_artifacts_dir, update_index=False)
    update_agent_artifact_index_for_marker_mutation(new_artifacts_dir)
    return new_artifacts_dir
