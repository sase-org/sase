"""Shared helpers for agent metadata enrichment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sase.agent.status_buckets import pending_plan_status_for_tier
from sase.core.time import to_local
from sase.core.artifact_file_helpers import select_canonical_plan_path
from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_phase_name,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
)

from ....agent_tribes import InvalidTribeError, validate_tribe_name
from ._json_cache import load_json_cached
from ..agent import Agent, LinkedRepoMetadata

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentMetaWire


ACTIVE_ENRICHMENT_STATUSES = {"STARTING", "RUNNING"}


def refresh_agent_plan_path(agent: Agent) -> None:
    """Refresh the compatibility plan path from retained source metadata."""
    agent.plan_path = select_canonical_plan_path(
        archived_plan_path=agent.archived_plan_path or agent.plan_path,
        sdd_plan_path=agent.sdd_plan_path,
        plan_committed=agent.plan_committed,
        plan_action=agent.plan_action,
    )


def parse_utc_to_local(iso_str: str) -> datetime:
    """Parse a UTC ISO 8601 timestamp and convert to configured-tz display time.

    Delegates to :func:`sase.core.time.to_local`, the shared aware→naive-local
    normalizer, so every model timestamp is a configured-tz wall time.
    """
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return to_local(dt)


def _parse_timestamp_field(raw_value: object) -> list[datetime]:
    values: list[str] = []
    if isinstance(raw_value, str):
        values = [raw_value]
    elif isinstance(raw_value, list):
        values = [v for v in raw_value if isinstance(v, str)]
    return _parse_timestamp_values(values)


def _parse_timestamp_values(values: list[str]) -> list[datetime]:
    parsed: list[datetime] = []
    for value in values:
        try:
            parsed.append(parse_utc_to_local(value))
        except ValueError:
            continue
    return parsed


def append_timestamp_field(
    raw_value: object,
    target: list[datetime],
) -> list[datetime]:
    parsed = _parse_timestamp_field(raw_value)
    target.extend(parsed)
    return parsed


def append_timestamp_values(
    values: list[str],
    target: list[datetime],
) -> list[datetime]:
    parsed = _parse_timestamp_values(values)
    target.extend(parsed)
    return parsed


def has_plan_submission_marker(raw_value: object) -> bool:
    if isinstance(raw_value, str):
        return bool(raw_value)
    if isinstance(raw_value, list):
        return any(isinstance(value, str) and value for value in raw_value)
    return False


def plan_enrichment_status(
    *,
    plan_approved: bool,
    plan_action: str | None,
    plan_submitted: bool,
    auto_approved: bool,
    plan_tier: str | None = None,
) -> str | None:
    if plan_approved:
        if plan_action == "commit":
            return "PLAN COMMITTED"
        if plan_action == "tale":
            return "TALE APPROVED"
        if plan_action == "epic":
            return "EPIC APPROVED"
        return "PLAN APPROVED"

    if plan_submitted and not auto_approved:
        return pending_plan_status_for_tier(plan_tier)

    return None


def pending_question_status_for_request_path(request_path: object) -> str:
    """Map a pending-question ``request_path`` to ``QUESTION`` or ``ANSWERED``.

    The pending-question marker's ``request_path`` points at the
    ``question_request.json`` written in the user-question session directory.
    The sibling ``question_response.json`` appears there once the user answers
    but before the runner consumes the response and clears the marker, so its
    presence is the transient ``ANSWERED`` signal. When no response is visible
    yet, the agent is still blocked and the status stays ``QUESTION``.
    """
    if isinstance(request_path, str) and request_path:
        response_path = Path(request_path).parent / "question_response.json"
        try:
            if response_path.exists():
                return "ANSWERED"
        except OSError:
            pass
    return "QUESTION"


def pending_question_status_from_marker(marker_path: Path) -> str:
    """Read a filesystem ``pending_question.json`` and map it to a status."""
    try:
        marker = load_json_cached(marker_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "QUESTION"
    request_path = marker.get("request_path") if isinstance(marker, dict) else None
    return pending_question_status_for_request_path(request_path)


def valid_meta_tribe(raw_value: object) -> str | None:
    if not isinstance(raw_value, str):
        return None
    try:
        return validate_tribe_name(raw_value)
    except InvalidTribeError:
        return None


def parse_linked_repos(raw_value: object) -> tuple[LinkedRepoMetadata, ...]:
    if not isinstance(raw_value, list):
        return ()

    parsed: list[LinkedRepoMetadata] = []
    from sase.linked_repos import is_legacy_static_linked_repo_record

    for item in raw_value:
        if not isinstance(item, dict):
            continue
        if is_legacy_static_linked_repo_record(item):
            continue
        raw_name = item.get("name")
        raw_workspace_dir = item.get("workspace_dir")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        if not isinstance(raw_workspace_dir, str) or not raw_workspace_dir:
            continue
        parsed.append(
            LinkedRepoMetadata(
                name=raw_name,
                workspace_dir=raw_workspace_dir,
            )
        )
    return tuple(parsed)


def meta_has_wait_directive(data: dict[str, object]) -> bool:
    return (
        bool(data.get("wait_for"))
        or bool(data.get("wait_for_beads"))
        or data.get("wait_duration") is not None
        or bool(data.get("wait_until"))
    )


def wire_meta_has_wait_directive(meta: AgentMetaWire) -> bool:
    return (
        bool(meta.wait_for)
        or bool(meta.wait_for_beads)
        or meta.wait_duration is not None
        or bool(meta.wait_until)
    )


def parent_timestamp_from_meta(
    agent: Agent,
    raw_value: object,
    *,
    workflow_child: bool,
) -> str | None:
    if not raw_value:
        return None
    parent_timestamp = str(raw_value)
    if (
        not workflow_child
        and agent.parent_workflow is None
        and agent.raw_suffix is not None
        and parent_timestamp == agent.raw_suffix
    ):
        return None
    return parent_timestamp


def is_main_workflow_agent_step(agent: Agent) -> bool:
    return (
        agent.parent_workflow is not None
        and agent.step_type == "agent"
        and agent.parent_step_index is None
    )


def _root_family_name_from_meta(data: dict[str, object]) -> str | None:
    role_suffix = canonical_plan_chain_suffix(data.get("role_suffix"))
    is_root = (
        data.get("plan_chain_root")
        or data.get("agent_family_role") == "root"
        or role_suffix == PLAN_CHAIN_PLAN_SUFFIX
    )
    if not is_root:
        return None
    family = data.get("agent_family")
    if isinstance(family, str) and family:
        return family
    name = data.get("name")
    if isinstance(name, str) and name:
        return name
    return None


def _root_child_suffix_from_meta(data: dict[str, object]) -> str:
    return (
        canonical_plan_chain_suffix(data.get("role_suffix")) or PLAN_CHAIN_PLAN_SUFFIX
    )


def apply_workflow_child_identity_from_meta(
    agent: Agent,
    data: dict[str, object],
) -> None:
    """Derive concrete family identity for the main agent workflow step."""
    if not is_main_workflow_agent_step(agent):
        return
    family = _root_family_name_from_meta(data)
    if family is None:
        return
    child_suffix = _root_child_suffix_from_meta(data)
    child_name = agent_family_phase_name(family, child_suffix)
    agent.agent_name = child_name
    agent.agent_family = family
    agent.agent_family_role = agent_family_role_for_suffix(child_suffix)
    agent.role_suffix = child_suffix
