"""Create reusable family shell member artifacts."""

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


def create_family_shell_member(
    project_name: str,
    base_meta: dict[str, Any],
    *,
    family: str,
    suffix: str,
    prev_artifacts_timestamp: str,
    workspace_num: int | None,
    shell_kind: str,
    family_role: str,
    metadata: Mapping[str, Any] | None = None,
    inherited_metadata_fields: Sequence[str] = (),
) -> str:
    """Create a family shell member and layer caller-supplied metadata on it."""
    member_name = f"{family}{suffix}"
    artifacts_dir = create_followup_artifacts(
        project_name,
        base_meta,
        suffix,
        prev_artifacts_timestamp,
        workspace_num=workspace_num,
        agent_name_override=member_name,
        workflow_name=family,
        agent_family_role=family_role,
    )
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    if not isinstance(meta, dict):
        raise ValueError(f"agent_meta.json at {artifacts_dir!r} is not an object")

    meta["shell_kind"] = shell_kind
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


__all__ = ["create_family_shell_member"]
