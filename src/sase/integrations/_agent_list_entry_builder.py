"""Build rich agent list entries from runtime and artifact records."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, cast

from sase.agent.running import RunningAgentInfo
from sase.agent.status_buckets import (
    ACTIVE_AGENT_STATUSES,
    AGENT_STATUS_BUCKET_GLYPHS,
    EPIC_APPROVED_STATUS,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    pending_plan_status_for_tier,
    status_bucket_for_values,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.sdd.plan_tiers import cached_plan_tier
from sase.core.time import get_timezone

from ._agent_list_entry_models import (
    AgentChildrenSummary,
    AgentListEntry,
    AgentRetryInfo,
    AgentWaitInfo,
)
from .provider_badges import provider_emoji_badge


_ACTIVE_OR_PRE_ACTIVE_STATUSES = ACTIVE_AGENT_STATUSES | {"STARTING", "RUNNING"}


def record_status_bucket(record: AgentArtifactRecordWire) -> str:
    meta = _record_meta(record)
    status = _derive_status(
        _base_record_status(record),
        meta,
        _record_waiting(record),
        _record_pending_question(record),
    )
    retry = _retry_info(meta, record.done)
    return status_bucket_for_values(status, retry.retried_as_timestamp)


def _base_record_status(record: AgentArtifactRecordWire) -> str:
    if record.has_done_marker:
        outcome = record.done.outcome if record.done is not None else None
        return "FAILED" if outcome == "failed" else "DONE"
    if record.waiting is not None:
        return "WAITING"
    meta = record.agent_meta
    if meta is not None and (meta.run_started_at or meta.wait_completed_at):
        return "RUNNING"
    return "STARTING"


def build_agent_list_entry(
    agent: RunningAgentInfo,
    *,
    record: AgentArtifactRecordWire | None = None,
    now: datetime | None = None,
    children: AgentChildrenSummary | None = None,
) -> AgentListEntry:
    """Build one rich projection from a lightweight agent row plus markers."""
    now = now or datetime.now(get_timezone())
    meta = _record_meta(record) or _read_meta(agent.artifacts_dir)
    waiting = _record_waiting(record) or _read_waiting(agent.artifacts_dir)
    pending_question = _record_pending_question(record) or _read_pending_question(
        agent.artifacts_dir
    )
    done = record.done if record is not None else _read_done(agent.artifacts_dir)

    status = _derive_status(agent.status, meta, waiting, pending_question)
    retry = _retry_info(meta, done)
    bucket = status_bucket_for_values(status, retry.retried_as_timestamp)

    model = agent.model or _text(meta, "model") or _text(done, "model")
    provider = (
        agent.provider or _text(meta, "llm_provider") or _text(done, "llm_provider")
    )
    vcs_provider = _first_text(
        _text(meta, "vcs_provider"),
        _text(done, "vcs_provider"),
        _text(record.running if record is not None else None, "vcs_provider"),
    )
    finished_at = _finished_at(done)
    has_file_changes = bool(_text(done, "diff_path") or _text(meta, "commit_diff_path"))

    return AgentListEntry(
        name=agent.name,
        project=agent.project,
        pid=agent.pid,
        model=model,
        provider=provider,
        provider_badge=provider_emoji_badge(provider),
        workspace_num=agent.workspace_num,
        duration=agent.duration,
        duration_seconds=agent.duration_seconds,
        started_at=agent.started_at,
        finished_at=finished_at,
        prompt=agent.prompt,
        status=status,
        status_bucket=bucket,
        status_glyph=AGENT_STATUS_BUCKET_GLYPHS.get(bucket, ""),
        approve=bool(agent.approve or _bool(meta, "approve") or _bool(done, "approve")),
        artifacts_dir=agent.artifacts_dir,
        timestamp=(
            record.timestamp if record is not None else artifact_timestamp(agent)
        ),
        reasoning_effort=_text(meta, "reasoning_effort"),
        vcs_provider=vcs_provider,
        vcs_provider_display=_vcs_provider_display_name(vcs_provider),
        tribe=agent.tribe or _text(meta, "tribe"),
        agent_clan=agent.agent_clan or _text(meta, "agent_clan"),
        agent_clan_generation=(
            agent.agent_clan_generation or _text(meta, "agent_clan_generation")
        ),
        clan_tribe=agent.clan_tribe or _text(meta, "clan_tribe"),
        bead_id=_text(meta, "bead_id"),
        changespec_name=_first_text(
            _text(meta, "changespec_name"), _text(meta, "cl_name")
        ),
        cl_name=_first_text(_text(meta, "cl_name"), _text(done, "cl_name")),
        workflow_name=_first_text(
            _text(meta, "workflow_name"),
            _text(
                record.workflow_state if record is not None else None, "workflow_name"
            ),
        ),
        agent_family=_text(meta, "agent_family"),
        agent_family_role=_text(meta, "agent_family_role"),
        parent_agent_name=_text(meta, "parent_agent_name"),
        plan=bool(_bool(meta, "plan")),
        plan_approved=bool(_bool(meta, "plan_approved")),
        plan_action=_text(meta, "plan_action"),
        auto_approve_plan_action=_text(meta, "auto_approve_plan_action"),
        pending_question=pending_question is not None and status == "QUESTION",
        question_answered=status == "ANSWERED",
        wait=_wait_info(agent, meta, waiting, now),
        retry=retry,
        children=children or AgentChildrenSummary(),
        activity=_text(
            record.workflow_state if record is not None else None, "activity"
        ),
        output_variables=dict(meta.output_variables) if meta is not None else {},
        artifact_count=_artifact_count(done),
        commit_count=_commit_count(done),
        error=_first_text(_text(done, "error"), _workflow_error(record)),
        traceback=_first_text(_text(done, "traceback"), _workflow_traceback(record)),
        has_file_changes=has_file_changes,
        has_done_marker=(
            record.has_done_marker if record is not None else done is not None
        ),
    )


def _vcs_provider_display_name(vcs_provider: str | None) -> str | None:
    """Return a user-facing VCS provider label."""
    if not vcs_provider:
        return None
    normalized = vcs_provider.strip().lower()
    if not normalized:
        return None
    labels = {
        "gh": "GitHub",
        "github": "GitHub",
        "git": "Git",
        "hg": "Mercurial",
        "mercurial": "Mercurial",
        "jj": "Jujutsu",
        "p4": "Perforce",
    }
    return labels.get(normalized, vcs_provider.strip())


def _derive_status(
    status: str,
    meta: AgentMetaWire | None,
    waiting: WaitingMarkerWire | None,
    pending_question: PendingQuestionMarkerWire | None,
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
    return derived


def _plan_status(meta: AgentMetaWire) -> str | None:
    if meta.plan_approved:
        action = (meta.plan_action or "plan").strip().lower()
        if action == "tale":
            return TALE_APPROVED_STATUS
        if action == "epic":
            return EPIC_APPROVED_STATUS
        return PLAN_APPROVED_STATUS
    if meta.plan_submitted_at and not (meta.approve or meta.auto_approve_plan_action):
        return pending_plan_status_for_tier(cached_plan_tier(meta.plan_path))
    return None


def _pending_question_status(request_path: str | None) -> str:
    if request_path:
        response_path = Path(request_path).with_name("question_response.json")
        if response_path.exists():
            return "ANSWERED"
    return "QUESTION"


def _wait_info(
    agent: RunningAgentInfo,
    meta: AgentMetaWire | None,
    waiting: WaitingMarkerWire | None,
    now: datetime,
) -> AgentWaitInfo:
    wait_for = tuple(waiting.waiting_for) if waiting is not None else ()
    if not wait_for and meta is not None:
        wait_for = tuple(meta.wait_for)
    wait_for_beads = tuple(waiting.wait_for_beads) if waiting is not None else ()
    if not wait_for_beads and meta is not None:
        wait_for_beads = tuple(meta.wait_for_beads)
    wait_duration = (
        waiting.wait_duration
        if waiting is not None and waiting.wait_duration is not None
        else meta.wait_duration
        if meta is not None
        else None
    )
    wait_until = (
        waiting.wait_until
        if waiting is not None and waiting.wait_until
        else meta.wait_until
        if meta is not None
        else None
    )
    return AgentWaitInfo(
        wait_for=wait_for,
        wait_for_beads=wait_for_beads,
        wait_duration_seconds=wait_duration,
        wait_until=wait_until,
        remaining_seconds=_remaining_wait_seconds(
            agent, wait_duration, wait_until, now
        ),
        wait_runners=waiting.wait_runners if waiting is not None else None,
        wait_runners_explicit=(
            waiting.wait_runners_explicit if waiting is not None else False
        ),
        wait_priority=waiting.wait_priority if waiting is not None else None,
        slot_requested_at=(waiting.slot_requested_at if waiting is not None else None),
    )


def _remaining_wait_seconds(
    agent: RunningAgentInfo,
    wait_duration: float | None,
    wait_until: str | None,
    now: datetime,
) -> int | None:
    target = parse_iso_datetime(wait_until)
    if target is None and wait_duration is not None and agent.started_at is not None:
        target = agent.started_at.astimezone(get_timezone()) + _seconds_delta(
            wait_duration
        )
    if target is None:
        return None
    remaining = int((target - now.astimezone(get_timezone())).total_seconds())
    return max(remaining, 0)


def _seconds_delta(seconds: float) -> timedelta:
    return timedelta(seconds=max(float(seconds), 0.0))


def _retry_info(
    meta: AgentMetaWire | None,
    done: DoneMarkerWire | None,
) -> AgentRetryInfo:
    return AgentRetryInfo(
        retry_attempt=_int(meta, "retry_attempt"),
        retry_of_timestamp=_text(meta, "retry_of_timestamp"),
        retried_as_timestamp=_first_text(
            _text(meta, "retried_as_timestamp"),
            _text(done, "retried_as_timestamp"),
        ),
        retry_chain_root_timestamp=_first_text(
            _text(meta, "retry_chain_root_timestamp"),
            _text(done, "retry_chain_root_timestamp"),
        ),
        retry_error_category=_first_text(
            _text(meta, "retry_error_category"),
            _text(done, "retry_error_category"),
        ),
    )


def _artifact_count(done: DoneMarkerWire | None) -> int:
    if done is None:
        return 0
    count = 0
    for value in (
        done.plan_path,
        done.diff_path,
        done.response_path,
        done.output_path,
    ):
        count += 1 if value else 0
    count += len(done.markdown_pdf_paths)
    count += len(done.image_paths)
    count += len(done.video_paths)
    return count


def _commit_count(done: DoneMarkerWire | None) -> int:
    if done is None or not isinstance(done.step_output, dict):
        return 0
    commits = done.step_output.get("commits")
    if isinstance(commits, list):
        return len(commits)
    commit = done.step_output.get("commit")
    return 1 if isinstance(commit, str) and commit else 0


def _finished_at(done: DoneMarkerWire | None) -> datetime | None:
    if done is None or done.finished_at is None:
        return None
    try:
        return datetime.fromtimestamp(float(done.finished_at), get_timezone())
    except (OSError, OverflowError, ValueError):
        return None


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone())
    return parsed.astimezone(get_timezone())


def _record_meta(record: AgentArtifactRecordWire | None) -> AgentMetaWire | None:
    return record.agent_meta if record is not None else None


def _record_waiting(record: AgentArtifactRecordWire | None) -> WaitingMarkerWire | None:
    return record.waiting if record is not None else None


def _record_pending_question(
    record: AgentArtifactRecordWire | None,
) -> PendingQuestionMarkerWire | None:
    return record.pending_question if record is not None else None


def _read_meta(artifacts_dir: str | None) -> AgentMetaWire | None:
    data = _read_json_dict(artifacts_dir, "agent_meta.json")
    if data is not None:
        data = canonicalize_agent_tribe_metadata(dict(data))
    return _wire_from_dict(AgentMetaWire, data)


def _read_waiting(artifacts_dir: str | None) -> WaitingMarkerWire | None:
    data = _read_json_dict(artifacts_dir, "waiting.json")
    return _wire_from_dict(WaitingMarkerWire, data)


def _read_pending_question(
    artifacts_dir: str | None,
) -> PendingQuestionMarkerWire | None:
    data = _read_json_dict(artifacts_dir, "pending_question.json")
    return _wire_from_dict(PendingQuestionMarkerWire, data)


def _read_done(artifacts_dir: str | None) -> DoneMarkerWire | None:
    data = _read_json_dict(artifacts_dir, "done.json")
    return _wire_from_dict(DoneMarkerWire, data)


def _read_json_dict(artifacts_dir: str | None, filename: str) -> dict[str, Any] | None:
    if not artifacts_dir:
        return None
    try:
        data = json.loads((Path(artifacts_dir) / filename).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _wire_from_dict[T](wire_type: type[T], data: dict[str, Any] | None) -> T | None:
    if data is None:
        return None
    names = {field.name for field in fields(cast(Any, wire_type))}
    try:
        return wire_type(**{key: value for key, value in data.items() if key in names})
    except TypeError:
        return None


def artifact_timestamp(agent: RunningAgentInfo) -> str | None:
    if not agent.artifacts_dir:
        return None
    return Path(agent.artifacts_dir).name


def _workflow_error(record: AgentArtifactRecordWire | None) -> str | None:
    if record is None or record.workflow_state is None:
        return None
    return record.workflow_state.error


def _workflow_traceback(record: AgentArtifactRecordWire | None) -> str | None:
    if record is None or record.workflow_state is None:
        return None
    return record.workflow_state.traceback


def _text(obj: object | None, attr: str) -> str | None:
    value = getattr(obj, attr, None)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _first_text(*values: str | None) -> str | None:
    return next((value for value in values if value), None)


def _bool(obj: object | None, attr: str) -> bool:
    return bool(getattr(obj, attr, False))


def _int(obj: object | None, attr: str) -> int | None:
    value = getattr(obj, attr, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None
