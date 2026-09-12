"""Status, timestamp, and plan helpers for agent enrichment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sase.agent.status_buckets import pending_plan_status_for_tier
from sase.core.artifact_file_helpers import select_canonical_plan_path
from sase.core.time import to_local

from ....hooks.processes import is_process_running
from ._json_cache import load_json_cached
from ..agent import Agent


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

    Delegates to :func:`sase.core.time.to_local`, the shared aware->naive-local
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


def pending_review_window_active(
    *,
    plan_submitted: bool,
    plan_approved: bool,
    plan_action: str | None,
    auto_approved: bool,
    gate_id: str | None,
    gate_member_agent_name: str | None,
    stopped_at: str | None,
    has_done_marker: bool,
    pid: int | None,
) -> bool:
    """Whether a finalized ``DONE`` row is still in the propose-to-gate window.

    A planner's runner rewrites its workflow markers to ``completed`` (hence
    ``DONE``) the moment a plan is submitted, before the review gate shell
    exists to carry the pending status itself. This predicate reopens
    pending-review enrichment for that row while the handoff is still in
    flight. It is self-healing: any settled row (approved, actioned,
    auto-approved, handed to a gate, stopped, or already carrying a done
    marker) or one whose runner has died stays ineligible, so no historical
    or orphaned row is ever reclassified.
    """
    if not plan_submitted:
        return False
    if plan_approved or plan_action:
        return False
    if auto_approved:
        return False
    if gate_id or gate_member_agent_name:
        return False
    if stopped_at:
        return False
    if has_done_marker:
        return False
    if pid is None or not is_process_running(pid):
        return False
    return True


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
