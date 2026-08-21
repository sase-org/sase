"""Artifact status helpers for wait-dependency resolution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.dismissed_agent_completion import effective_done_outcome
from sase.monitor_state import is_monitor_member_role
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    AGENT_FAMILY_ROLE_FIELD,
    agent_family_base,
    is_plan_chain_artifact_meta,
)

from ._json_io import read_json_dict
from ._types import (
    FAILURE_OUTCOMES,
    HANDOFF_TERMINAL_STEP_STATUSES,
    IDENTITY_SUCCESS_OUTCOMES,
    SUCCESS_OUTCOME,
    SUCCESSFUL_MONITOR_FOLLOWUP_OUTCOMES,
    WAIT_SUCCESS_OUTCOMES,
)

_TERMINAL_MONITOR_STATES = frozenset(
    {"completed", "failed", "timeout", "stopped", "lost"}
)


def done_outcome(artifact_dir: Path) -> str | None:
    done_data = read_json_dict(artifact_dir / "done.json")
    return done_outcome_from_data(done_data)


def done_outcome_from_data(done_data: Mapping[str, Any] | None) -> str | None:
    if done_data is None:
        return None
    return effective_done_outcome(done_data)


def monitor_followup_handoff_agent(
    meta: Mapping[str, Any],
    done_data: Mapping[str, Any] | None,
) -> str | None:
    if done_data is None or done_data.get("outcome") != "monitored":
        return None

    monitor_state = done_data.get("monitor_state") or meta.get("monitor_state")
    if (
        not isinstance(monitor_state, str)
        or monitor_state not in _TERMINAL_MONITOR_STATES
    ):
        return None

    followup_outcome = done_data.get("monitor_followup_outcome") or meta.get(
        "monitor_followup_outcome"
    )
    if followup_outcome not in SUCCESSFUL_MONITOR_FOLLOWUP_OUTCOMES:
        return None

    followup_agent = done_data.get("monitor_followup_agent") or meta.get(
        "monitor_followup_agent"
    )
    if not isinstance(followup_agent, str):
        return None
    followup_agent = followup_agent.strip()
    return followup_agent or None


def artifact_failed_for_identity(done_data: Mapping[str, Any] | None) -> bool:
    if done_data is None:
        return False
    if bool(done_data.get("repeat_stopped")):
        return True
    outcome = done_outcome_from_data(done_data)
    return outcome in FAILURE_OUTCOMES


def artifact_succeeded_for_identity(done_data: Mapping[str, Any] | None) -> bool:
    if done_data is None or bool(done_data.get("repeat_stopped")):
        return False
    outcome = done_outcome_from_data(done_data)
    return outcome in IDENTITY_SUCCESS_OUTCOMES


def same_artifact_dir(left: str, right: str | Path | None) -> bool:
    if right is None:
        return False
    return _artifact_dir_key(left) == _artifact_dir_key(str(right))


def _artifact_dir_key(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return value


def artifact_is_resolved(
    artifact_dir: Path,
    meta: dict[str, Any],
    outcome: str | None,
) -> bool:
    if outcome is not None:
        return outcome in WAIT_SUCCESS_OUTCOMES
    if not is_plan_chain_artifact_meta(meta):
        return False
    if _is_monitor_member_meta(meta):
        return False
    return _completed_handoff_workflow_state(artifact_dir)


def _is_monitor_member_meta(meta: Mapping[str, Any]) -> bool:
    return is_monitor_member_role(
        _str_or_none(meta.get(AGENT_FAMILY_ROLE_FIELD)),
        _str_or_none(meta.get("role_suffix")),
    )


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _completed_handoff_workflow_state(artifact_dir: Path) -> bool:
    state_data = read_json_dict(artifact_dir / "workflow_state.json")
    if state_data is None or state_data.get("status") != SUCCESS_OUTCOME:
        return False
    if _has_failure_fields(state_data):
        return False

    steps_data = state_data.get("steps", [])
    if not isinstance(steps_data, list):
        return False

    for step_data in steps_data:
        if not isinstance(step_data, dict):
            return False
        if step_data.get("status") not in HANDOFF_TERMINAL_STEP_STATUSES:
            return False
        if _has_failure_fields(step_data):
            return False

    return not _has_blocking_prompt_step_marker(artifact_dir)


def _has_failure_fields(data: dict[str, Any]) -> bool:
    return bool(data.get("error") or data.get("traceback"))


def _has_blocking_prompt_step_marker(artifact_dir: Path) -> bool:
    for marker_path in artifact_dir.glob("prompt_step_*.json"):
        marker_data = read_json_dict(marker_path)
        if marker_data is None:
            return True
        if marker_data.get("status") not in HANDOFF_TERMINAL_STEP_STATUSES:
            return True
        if _has_failure_fields(marker_data):
            return True
    return False


def family_base_from_meta(meta: dict[str, Any]) -> str | None:
    family = meta.get(AGENT_FAMILY_FIELD)
    if isinstance(family, str) and family:
        return family

    workflow_name = meta.get("workflow_name")
    if not isinstance(workflow_name, str) or not workflow_name:
        return None

    if is_plan_chain_artifact_meta(meta):
        return workflow_name

    name = meta.get("name")
    if isinstance(name, str) and agent_family_base(name) == workflow_name:
        return workflow_name

    return None
