"""Create reusable agent-session shell member artifacts."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)


def create_agent_session_turn_member(
    project_name: str,
    base_meta: dict[str, Any],
    *,
    agent_session: str,
    suffix: str,
    prev_artifacts_timestamp: str,
    workspace_num: int | None,
    shell_kind: str | None = None,
    turn_kind: str | None = None,
    agent_session_role: str,
    metadata: Mapping[str, Any] | None = None,
    inherited_metadata_fields: Sequence[str] = (),
) -> str:
    """Create an agent-session shell member and layer caller-supplied metadata on it.

    Does not stamp this process's pid onto the member: a gate has no
    process, and a monitor's pid is the detached supervisor's.
    """
    member_name = f"{agent_session}{suffix}"
    artifacts_dir = create_followup_artifacts(
        project_name,
        base_meta,
        suffix,
        prev_artifacts_timestamp,
        workspace_num=workspace_num,
        agent_name_override=member_name,
        workflow_name=agent_session,
        agent_session_role=agent_session_role,
        stamp_creating_process=False,
    )
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    if not isinstance(meta, dict):
        raise ValueError(f"agent_meta.json at {artifacts_dir!r} is not an object")

    from sase.plan_chain import (
        LEGACY_SHELL_KIND_KEY,
        TURN_KIND_KEY,
        normalize_turn_kind,
    )

    effective_kind = turn_kind if turn_kind is not None else shell_kind
    # legacy sase-shell spelling: the old ``proc`` value reads as ``monitor``.
    effective_kind = normalize_turn_kind(effective_kind)
    meta[TURN_KIND_KEY] = effective_kind
    meta.pop(LEGACY_SHELL_KIND_KEY, None)
    for key in inherited_metadata_fields:
        if _has_metadata_value(base_meta.get(key)):
            meta[key] = base_meta[key]
    if metadata:
        meta.update(metadata)

    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    return artifacts_dir


def _has_metadata_value(value: Any) -> bool:
    return value is not None and value != ""


__all__ = ["create_agent_session_turn_member"]
