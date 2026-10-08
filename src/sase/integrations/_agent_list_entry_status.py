"""Status derivation for agent list entry projections."""

from __future__ import annotations

from pathlib import Path

from sase.agent.status_buckets import (
    ACTIVE_AGENT_STATUSES,
    EPIC_APPROVED_STATUS,
    EPIC_FAILED_STATUS,
    PLAN_APPROVED_STATUS,
    PLAN_COMMITTED_STATUS,
    PLAN_FAILED_STATUS,
    TALE_APPROVED_STATUS,
    pending_plan_status_for_tier,
    status_bucket_for_values,
    valid_status_bucket,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from sase.monitor_state import is_monitor_member_role, monitor_state_bucket
from sase.monitor_status import (
    DEFAULT_MONITOR_START_STATUS,
    DEFAULT_MONITOR_STOP_STATUS,
    clamp_monitor_status_or_default,
)
from sase.sdd.plan_tiers import cached_plan_tier

from ._agent_list_entry_fields import (
    field_int,
    field_text,
    first_field_text,
    monitor_str,
    record_meta,
    record_pending_question,
    record_waiting,
)
from ._agent_list_entry_models import AgentRetryInfo


_ACTIVE_OR_PRE_ACTIVE_STATUSES = ACTIVE_AGENT_STATUSES | {"STARTING", "RUNNING"}


def record_status_bucket(record: AgentArtifactRecordWire) -> str:
    meta = record_meta(record)
    if is_monitor(meta, record.done):
        state = monitor_str(record.done, "state")
        return monitor_state_bucket(state or monitor_str(meta, "state"))
    status = derive_status(
        _base_record_status(record),
        meta,
        record_waiting(record),
        record_pending_question(record),
        record.done,
    )
    retry = retry_info(meta, record.done)
    override = valid_status_bucket(meta.status_bucket) if meta is not None else None
    if override is None and record.done is not None:
        override = valid_status_bucket(record.done.status_bucket)
    return override or status_bucket_for_values(status, retry.retried_as_timestamp)


def derive_status(
    status: str,
    meta: AgentMetaWire | None,
    waiting: WaitingMarkerWire | None,
    pending_question: PendingQuestionMarkerWire | None,
    done: DoneMarkerWire | None,
) -> str:
    derived = status or "RUNNING"
    if waiting is not None and derived in _ACTIVE_OR_PRE_ACTIVE_STATUSES:
        derived = "WAITING"
    if (
        waiting is None
        and pending_question is not None
        and derived in _ACTIVE_OR_PRE_ACTIVE_STATUSES
    ):
        derived = _pending_question_status(pending_question.request_path)
    if meta is not None and meta.plan and derived in _ACTIVE_OR_PRE_ACTIVE_STATUSES:
        plan_status = _plan_status(meta)
        if plan_status is not None:
            derived = plan_status
    if is_monitor(meta, done):
        if done is not None and done.outcome == "monitored":
            return clamp_monitor_status_or_default(
                done.status_label or monitor_str(meta, "stop_status"),
                default=DEFAULT_MONITOR_STOP_STATUS,
            )
        if meta is not None and (meta.run_started_at or meta.wait_completed_at):
            return clamp_monitor_status_or_default(
                monitor_str(meta, "start_status"),
                default=DEFAULT_MONITOR_START_STATUS,
            )
        return "STARTING"
    return derived


def is_monitor(meta: AgentMetaWire | None, done: DoneMarkerWire | None) -> bool:
    if meta is None or not is_monitor_member_role(
        meta.agent_session_role,
        meta.role_suffix,
    ):
        return False
    return bool(
        monitor_str(meta, "id") or (done is not None and done.outcome == "monitored")
    )


def retry_info(
    meta: AgentMetaWire | None,
    done: DoneMarkerWire | None,
) -> AgentRetryInfo:
    return AgentRetryInfo(
        retry_attempt=field_int(meta, "retry_attempt"),
        retry_of_timestamp=field_text(meta, "retry_of_timestamp"),
        retried_as_timestamp=first_field_text(
            field_text(meta, "retried_as_timestamp"),
            field_text(done, "retried_as_timestamp"),
        ),
        retry_chain_root_timestamp=first_field_text(
            field_text(meta, "retry_chain_root_timestamp"),
            field_text(done, "retry_chain_root_timestamp"),
        ),
        retry_error_category=first_field_text(
            field_text(meta, "retry_error_category"),
            field_text(done, "retry_error_category"),
        ),
    )


def _base_record_status(record: AgentArtifactRecordWire) -> str:
    if record.has_done_marker:
        done = record.done
        outcome = done.outcome if done is not None else None
        if outcome == "monitored":
            return clamp_monitor_status_or_default(
                done.status_label if done is not None else None,
                default=DEFAULT_MONITOR_STOP_STATUS,
            )
        return "FAILED" if outcome == "failed" else "DONE"
    if record.waiting is not None:
        return "WAITING"
    meta = record.agent_meta
    if meta is not None and (meta.run_started_at or meta.wait_completed_at):
        return "RUNNING"
    return "STARTING"


def _plan_status(meta: AgentMetaWire) -> str | None:
    action = (meta.plan_action or "").strip().lower()
    if action == "failed":
        return PLAN_FAILED_STATUS
    if action == "epic_failed":
        return EPIC_FAILED_STATUS
    if meta.plan_approved:
        if action == "tale":
            return TALE_APPROVED_STATUS
        if action == "epic":
            return EPIC_APPROVED_STATUS
        if action == "commit":
            if meta.plan_committed is False:
                return None
            return PLAN_COMMITTED_STATUS
        return PLAN_APPROVED_STATUS
    if meta.plan_submitted_at:
        if not (meta.approve or meta.auto_approve_plan_action):
            return pending_plan_status_for_tier(cached_plan_tier(meta.plan_path))
        # Auto state is set: a covered tier auto-resolves, but a parked
        # cross-tier gate (e.g. `%auto:tale` on an epic plan) still waits
        # for a human, so it stays visible as pending review.
        if _plan_auto_covers_submitted_tier(meta):
            return None
        return pending_plan_status_for_tier(cached_plan_tier(meta.plan_path))
    return None


def _plan_auto_covers_submitted_tier(meta: AgentMetaWire) -> bool:
    """Return whether the recorded auto state covers the submitted plan tier."""
    from sase._plan_gate_metadata import recorded_auto_covers_plan

    return recorded_auto_covers_plan(
        meta.auto_approve_plan_action,
        getattr(meta, "auto_approve_argument", None),
        meta.plan_path,
    )


def _pending_question_status(request_path: str | None) -> str:
    if request_path:
        response_path = Path(request_path).with_name("question_response.json")
        if response_path.exists():
            return "ANSWERED"
    return "QUESTION"
