"""Agent metadata and follow-up artifact helpers."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sase.artifacts import create_artifacts_directory
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_launch_facade import reserve_launch_timestamp_batch
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    AGENT_FAMILY_ROLE_FIELD,
    PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
    agent_family_base,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
    is_plan_chain_artifact_meta,
)


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
        write_agent_meta_atomic(
            artifacts_dir,
            meta,
            index_updater=update_agent_artifact_index_for_marker_mutation,
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def update_meta_field(artifacts_dir: str, key: str, value: Any) -> None:
    """Read agent_meta.json, set a single key, and write it back."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta[key] = value
        write_agent_meta_atomic(
            artifacts_dir,
            meta,
            index_updater=update_agent_artifact_index_for_marker_mutation,
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def update_meta_fields(
    artifacts_dir: str,
    fields: dict[str, Any],
    *,
    remove_keys: Sequence[str] = (),
) -> None:
    """Read agent_meta.json, set/remove multiple keys, and write back once."""
    if not fields and not remove_keys:
        return
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        for key in remove_keys:
            meta.pop(key, None)
        meta.update(fields)
        write_agent_meta_atomic(
            artifacts_dir,
            meta,
            index_updater=update_agent_artifact_index_for_marker_mutation,
        )
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
        write_agent_meta_atomic(
            artifacts_dir,
            meta,
            index_updater=update_agent_artifact_index_for_marker_mutation,
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def promote_to_workflow(
    artifacts_dir: str,
    base_name: str,
    role_suffix: str,
) -> None:
    """Rename the initial agent into the first plan-chain family member."""
    from sase.agent._family_promotion import (
        normalized_family_root_role_suffix,
        promote_agent_to_family,
    )

    promote_agent_to_family(
        artifacts_dir,
        base_name,
        root_role_suffix=normalized_family_root_role_suffix(role_suffix),
    )


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
    reserved_timestamp = reserve_launch_timestamp_batch(1)[0]
    new_artifacts_dir = create_artifacts_directory(
        "ace-run",
        project_name=project_name,
        timestamp=reserved_timestamp,
    )
    canonical_suffix = canonical_plan_chain_suffix(suffix) or suffix

    followup_meta: dict[str, Any] = {"pid": os.getpid()}
    for key in (
        "model",
        "llm_provider",
        "reasoning_effort",
        "model_alias_overrides",
        "vcs_provider",
        # Inherit the workspace the parent ran in: follow-up agents run in the
        # same workspace, and persisting it lets the TUI resolve the live diff
        # directly from agent_meta.json instead of re-deriving the path.
        "workspace_dir",
        "name",
        "approve",
        "patch_name",
        "changespec_name",
        "cl_name",
        "bead_id",
        "sdd_plan_path",
        "epic_plan_ref",
        "plan_committed",
        "epic_bead_id",
        "phase_bead_id",
        "tribe",
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

    write_agent_meta_atomic(new_artifacts_dir, followup_meta, update_index=False)

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

    update_agent_artifact_index_for_marker_mutation(new_artifacts_dir)
    return new_artifacts_dir
