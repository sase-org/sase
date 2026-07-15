"""Presentation-neutral rich agent list projections for integrations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, cast

from sase.agent.running import RunningAgentInfo, list_all_agents, list_running_agents
from sase.agent.status_buckets import (
    ACTIVE_AGENT_STATUSES,
    AGENT_STATUS_BUCKET_GLYPHS,
    AGENT_STATUS_BUCKETS,
    EPIC_APPROVED_STATUS,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    status_bucket_for_values,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from sase.core.paths import sase_projects_dir
from sase.core.time import get_timezone

from .provider_badges import provider_emoji_badge

__all__ = [
    "AgentListEntry",
    "agent_list_entries",
]

_ACTIVE_OR_PRE_ACTIVE_STATUSES = ACTIVE_AGENT_STATUSES | {"STARTING", "RUNNING"}
_TERMINAL_BUCKETS = {"Done", "Failed"}
_CHILD_SUMMARY_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    only_workflow_dirs=("ace-run",),
    include_workflow_state=False,
)


@dataclass(frozen=True)
class _AgentWaitInfo:
    """Wait metadata projected from agent markers."""

    wait_for: tuple[str, ...] = ()
    wait_duration_seconds: float | None = None
    wait_until: str | None = None
    remaining_seconds: int | None = None
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    slot_requested_at: str | None = None
    runner_slots_in_use: int | None = None
    runner_slot_queue_position: int | None = None
    runner_slot_queue_size: int | None = None

    @property
    def has_wait(self) -> bool:
        return bool(
            self.wait_for
            or self.wait_duration_seconds is not None
            or self.wait_until
            or self.remaining_seconds is not None
            or self.slot_requested_at
        )


@dataclass(frozen=True)
class _AgentRetryInfo:
    """Retry lineage metadata projected from agent markers."""

    retry_attempt: int | None = None
    retry_of_timestamp: str | None = None
    retried_as_timestamp: str | None = None
    retry_chain_root_timestamp: str | None = None
    retry_error_category: str | None = None
    fallback_model: str | None = None

    @property
    def has_retry(self) -> bool:
        return bool(
            self.retry_attempt is not None
            or self.retry_of_timestamp
            or self.retried_as_timestamp
            or self.retry_chain_root_timestamp
            or self.retry_error_category
            or self.fallback_model
        )


@dataclass(frozen=True)
class _AgentChildrenSummary:
    """Cheap direct-child count summary for folded linear surfaces."""

    count: int = 0
    status_counts: tuple[tuple[str, int], ...] = ()

    @property
    def badge(self) -> str | None:
        return f"×{self.count}" if self.count else None


@dataclass(frozen=True)
class AgentListEntry:
    """Rich, presentation-neutral agent list/detail projection."""

    name: str | None
    project: str
    pid: int | None
    model: str | None
    provider: str | None
    provider_badge: str | None
    workspace_num: int | None
    duration: str
    duration_seconds: int | None
    started_at: datetime | None
    finished_at: datetime | None
    prompt: str | None
    status: str
    status_bucket: str
    status_glyph: str
    approve: bool
    artifacts_dir: str | None
    timestamp: str | None = None
    reasoning_effort: str | None = None
    vcs_provider: str | None = None
    vcs_provider_display: str | None = None
    tag: str | None = None
    bead_id: str | None = None
    changespec_name: str | None = None
    cl_name: str | None = None
    workflow_name: str | None = None
    agent_family: str | None = None
    agent_family_role: str | None = None
    parent_agent_name: str | None = None
    plan: bool = False
    plan_approved: bool = False
    plan_action: str | None = None
    auto_approve_plan_action: str | None = None
    pending_question: bool = False
    question_answered: bool = False
    wait: _AgentWaitInfo = field(default_factory=_AgentWaitInfo)
    retry: _AgentRetryInfo = field(default_factory=_AgentRetryInfo)
    children: _AgentChildrenSummary = field(default_factory=_AgentChildrenSummary)
    activity: str | None = None
    output_variables: Mapping[str, str] = field(default_factory=dict)
    artifact_count: int = 0
    commit_count: int = 0
    error: str | None = None
    traceback: str | None = None
    has_file_changes: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.status_bucket in _TERMINAL_BUCKETS

    @property
    def needs_user_action(self) -> bool:
        return self.status in {"PLAN", "QUESTION"}

    @property
    def auto_badge(self) -> str | None:
        if self.auto_approve_plan_action:
            action = self.auto_approve_plan_action.strip().lower()
            if action == "tale":
                return "⚡T"
            if action == "epic":
                return "⚡E"
        return "⚡" if self.approve else None


def agent_list_entries(
    *,
    include_recent: bool = False,
    project: str | None = None,
) -> list[AgentListEntry]:
    """Return rich agent list entries for active and optionally recent agents."""
    agents = list_all_agents() if include_recent else list_running_agents()
    # The listing layer has already filtered to live root user agents and
    # carries exact source-record occupancy. The status fallback preserves
    # compatibility for integrations that construct RunningAgentInfo directly.
    runner_slots_in_use = sum(
        1
        for agent in agents
        if (
            agent.holds_runner_slot
            if agent.holds_runner_slot is not None
            else agent.status == "RUNNING"
        )
    )
    now = datetime.now(get_timezone())
    child_summaries = _children_by_parent_timestamp(project=project) if agents else {}
    entries: list[AgentListEntry] = []
    for agent in agents:
        timestamp = _artifact_timestamp(agent)
        children = (
            child_summaries.get((agent.project, timestamp))
            if timestamp is not None
            else None
        )
        entries.append(_build_agent_list_entry(agent, now=now, children=children))
    entries = _attach_runner_slot_context(entries, runner_slots_in_use)
    if project:
        entries = [entry for entry in entries if entry.project == project]
    return entries


def _attach_runner_slot_context(
    entries: list[AgentListEntry],
    runner_slots_in_use: int,
) -> list[AgentListEntry]:
    waiters = sorted(
        (
            entry
            for entry in entries
            if entry.wait.slot_requested_at
            and entry.wait.wait_runners is not None
            and runner_slots_in_use <= entry.wait.wait_runners
        ),
        key=lambda entry: (
            _parse_iso_datetime(entry.wait.slot_requested_at)
            or datetime.max.replace(tzinfo=get_timezone()),
            entry.timestamp or "",
            entry.artifacts_dir or "",
        ),
    )
    positions = {id(entry): index for index, entry in enumerate(waiters, 1)}
    queue_size = len(waiters)
    return [
        replace(
            entry,
            wait=replace(
                entry.wait,
                runner_slots_in_use=runner_slots_in_use,
                runner_slot_queue_position=positions.get(id(entry)),
                runner_slot_queue_size=queue_size,
            ),
        )
        if entry.wait.slot_requested_at
        else entry
        for entry in entries
    ]


def _children_by_parent_timestamp(
    *, project: str | None = None
) -> dict[tuple[str, str], _AgentChildrenSummary]:
    from sase.core.agent_scan_facade import scan_agent_artifacts

    snapshot = scan_agent_artifacts(
        sase_projects_dir(),
        _CHILD_SUMMARY_SCAN_OPTIONS,
    )
    counts: dict[tuple[str, str], Counter[str]] = {}
    for record in snapshot.records:
        meta = record.agent_meta
        if meta is None or not meta.parent_timestamp:
            continue
        if project and record.project_name != project:
            continue
        if meta.parent_timestamp == record.timestamp:
            continue
        key = (record.project_name, meta.parent_timestamp)
        counts.setdefault(key, Counter()).update([_record_status_bucket(record)])
    return {
        key: _AgentChildrenSummary(
            count=sum(bucket_counts.values()),
            status_counts=tuple(
                (bucket, bucket_counts[bucket])
                for bucket in AGENT_STATUS_BUCKETS
                if bucket_counts.get(bucket)
            ),
        )
        for key, bucket_counts in counts.items()
    }


def _record_status_bucket(record: AgentArtifactRecordWire) -> str:
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


def _build_agent_list_entry(
    agent: RunningAgentInfo,
    *,
    record: AgentArtifactRecordWire | None = None,
    now: datetime | None = None,
    children: _AgentChildrenSummary | None = None,
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
        timestamp=record.timestamp
        if record is not None
        else _artifact_timestamp(agent),
        reasoning_effort=_text(meta, "reasoning_effort"),
        vcs_provider=vcs_provider,
        vcs_provider_display=_vcs_provider_display_name(vcs_provider),
        tag=_text(meta, "tag"),
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
        children=children or _AgentChildrenSummary(),
        activity=_text(
            record.workflow_state if record is not None else None, "activity"
        ),
        output_variables=dict(meta.output_variables) if meta is not None else {},
        artifact_count=_artifact_count(done),
        commit_count=_commit_count(done),
        error=_first_text(_text(done, "error"), _workflow_error(record)),
        traceback=_first_text(_text(done, "traceback"), _workflow_traceback(record)),
        has_file_changes=has_file_changes,
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
        return "PLAN"
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
) -> _AgentWaitInfo:
    wait_for = tuple(waiting.waiting_for) if waiting is not None else ()
    if not wait_for and meta is not None:
        wait_for = tuple(meta.wait_for)
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
    return _AgentWaitInfo(
        wait_for=wait_for,
        wait_duration_seconds=wait_duration,
        wait_until=wait_until,
        remaining_seconds=_remaining_wait_seconds(
            agent, wait_duration, wait_until, now
        ),
        wait_runners=waiting.wait_runners if waiting is not None else None,
        wait_runners_explicit=(
            waiting.wait_runners_explicit if waiting is not None else False
        ),
        slot_requested_at=(waiting.slot_requested_at if waiting is not None else None),
    )


def _remaining_wait_seconds(
    agent: RunningAgentInfo,
    wait_duration: float | None,
    wait_until: str | None,
    now: datetime,
) -> int | None:
    target = _parse_iso_datetime(wait_until)
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
) -> _AgentRetryInfo:
    return _AgentRetryInfo(
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


def _parse_iso_datetime(value: str | None) -> datetime | None:
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


def _artifact_timestamp(agent: RunningAgentInfo) -> str | None:
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
