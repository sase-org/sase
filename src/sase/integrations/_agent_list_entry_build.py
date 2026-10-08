"""Assemble rich agent list entries from runtime and artifact records."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
import json
from pathlib import Path
from typing import Any, cast

from sase.agent.running import RunningAgentInfo
from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    agent_status_bucket,
    valid_status_bucket,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
    agent_session_turn_from_mapping,
)
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.core.patch_metadata import canonicalize_patch_metadata
from sase.core.time import get_timezone
from sase.core.wire import with_agent_session_keys
from sase.monitor_state import monitor_state_bucket
from sase.monitor_status import clamp_monitor_status_or_default

from ._agent_list_entry_fields import (
    field_int,
    field_text,
    first_field_text,
    monitor_str,
    monitor_turn,
    record_meta,
    record_pending_question,
    record_waiting,
)
from ._agent_list_entry_models import AgentChildrenSummary, AgentListEntry
from ._agent_list_entry_status import derive_status, is_monitor, retry_info
from ._agent_list_entry_wait import wait_info
from .provider_badges import provider_emoji_badge


@dataclass(frozen=True, slots=True)
class _AgentListStatusRow:
    status: str
    retried_as_timestamp: str | None
    status_bucket: str | None


def build_agent_list_entry(
    agent: RunningAgentInfo,
    *,
    record: AgentArtifactRecordWire | None = None,
    now: datetime | None = None,
    children: AgentChildrenSummary | None = None,
) -> AgentListEntry:
    """Build one rich projection from a lightweight agent row plus markers."""
    now = now or datetime.now(get_timezone())
    meta = record_meta(record) or _read_meta(agent.artifacts_dir)
    waiting = record_waiting(record) or _read_waiting(agent.artifacts_dir)
    pending_question = record_pending_question(record) or _read_pending_question(
        agent.artifacts_dir
    )
    done = record.done if record is not None else _read_done(agent.artifacts_dir)

    status = derive_status(agent.status, meta, waiting, pending_question, done)
    retry = retry_info(meta, done)
    status_bucket: str | None
    if is_monitor(meta, done):
        status_bucket = monitor_state_bucket(
            monitor_str(done, "state") or monitor_str(meta, "state")
        )
    else:
        status_bucket = valid_status_bucket(agent.status_bucket) or (
            valid_status_bucket(meta.status_bucket) if meta is not None else None
        )
        if status_bucket is None and done is not None:
            status_bucket = valid_status_bucket(done.status_bucket)
    bucket = agent_status_bucket(
        _AgentListStatusRow(
            status=status,
            retried_as_timestamp=retry.retried_as_timestamp,
            status_bucket=status_bucket,
        )
    )

    model = agent.model or field_text(meta, "model") or field_text(done, "model")
    provider = (
        agent.provider
        or field_text(meta, "llm_provider")
        or field_text(done, "llm_provider")
    )
    vcs_provider = first_field_text(
        field_text(meta, "vcs_provider"),
        field_text(done, "vcs_provider"),
        field_text(record.running if record is not None else None, "vcs_provider"),
    )
    finished_at = _finished_at(done)
    has_file_changes = bool(
        field_text(done, "diff_path") or field_text(meta, "commit_diff_path")
    )

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
        reasoning_effort=field_text(meta, "reasoning_effort"),
        vcs_provider=vcs_provider,
        vcs_provider_display=_vcs_provider_display_name(vcs_provider),
        tribe=agent.tribe or field_text(meta, "tribe"),
        agent_clan=agent.agent_clan or field_text(meta, "agent_clan"),
        agent_clan_generation=(
            agent.agent_clan_generation or field_text(meta, "agent_clan_generation")
        ),
        clan_tribe=agent.clan_tribe or field_text(meta, "clan_tribe"),
        bead_id=field_text(meta, "bead_id"),
        patch_name=first_field_text(
            field_text(meta, "patch_name"),
            field_text(meta, "changespec_name"),
            field_text(meta, "cl_name"),
            field_text(done, "patch_name"),
            field_text(done, "cl_name"),
        ),
        changespec_name=first_field_text(
            field_text(meta, "changespec_name"),
            field_text(meta, "patch_name"),
            field_text(meta, "cl_name"),
        ),
        cl_name=first_field_text(
            field_text(meta, "cl_name"),
            field_text(meta, "patch_name"),
            field_text(done, "cl_name"),
            field_text(done, "patch_name"),
        ),
        workflow_name=first_field_text(
            field_text(meta, "workflow_name"),
            field_text(
                record.workflow_state if record is not None else None, "workflow_name"
            ),
        ),
        agent_session=field_text(meta, "agent_session"),
        agent_session_role=field_text(meta, "agent_session_role"),
        role_suffix=field_text(meta, "role_suffix"),
        parent_agent_name=field_text(meta, "parent_agent_name"),
        plan=bool(_bool(meta, "plan")),
        plan_approved=bool(_bool(meta, "plan_approved")),
        plan_action=field_text(meta, "plan_action"),
        auto_approve_plan_action=field_text(meta, "auto_approve_plan_action"),
        pending_question=pending_question is not None and status == "QUESTION",
        question_answered=status == "ANSWERED",
        wait=wait_info(agent, meta, waiting, now),
        retry=retry,
        children=children or AgentChildrenSummary(),
        activity=field_text(
            record.workflow_state if record is not None else None, "activity"
        ),
        output_variables=dict(meta.output_variables) if meta is not None else {},
        artifact_count=_artifact_count(done),
        commit_count=_commit_count(done),
        error=first_field_text(field_text(done, "error"), _workflow_error(record)),
        traceback=first_field_text(
            field_text(done, "traceback"), _workflow_traceback(record)
        ),
        has_file_changes=has_file_changes,
        has_done_marker=(
            record.has_done_marker if record is not None else done is not None
        ),
        monitor_id=first_field_text(agent.monitor_id, monitor_str(meta, "id")),
        monitor_state=first_field_text(
            agent.monitor_state,
            monitor_str(done, "state"),
            monitor_str(meta, "state"),
        ),
        monitor_label=first_field_text(agent.monitor_label, monitor_str(meta, "label")),
        monitor_command=first_field_text(
            agent.monitor_command,
            _monitor_command(meta),
        ),
        monitor_exit_code=_first_int(
            agent.monitor_exit_code,
            _monitor_exit_code(done),
            _monitor_exit_code(meta),
        ),
        monitor_start_status=_recorded_monitor_status(
            agent.monitor_start_status,
            monitor_str(meta, "start_status"),
        ),
        monitor_stop_status=_recorded_monitor_status(
            agent.monitor_stop_status,
            field_text(done, "status_label"),
            monitor_str(meta, "stop_status"),
        ),
    )


def artifact_timestamp(agent: RunningAgentInfo) -> str | None:
    if not agent.artifacts_dir:
        return None
    return Path(agent.artifacts_dir).name


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


def _workflow_error(record: AgentArtifactRecordWire | None) -> str | None:
    if record is None or record.workflow_state is None:
        return None
    return record.workflow_state.error


def _workflow_traceback(record: AgentArtifactRecordWire | None) -> str | None:
    if record is None or record.workflow_state is None:
        return None
    return record.workflow_state.traceback


def _monitor_command(source: AgentMetaWire | DoneMarkerWire | None) -> str | None:
    shell = monitor_turn(source)
    return field_text(shell.monitor if shell is not None else None, "command")


def _monitor_exit_code(source: AgentMetaWire | DoneMarkerWire | None) -> int | None:
    shell = monitor_turn(source)
    return field_int(shell.monitor if shell is not None else None, "exit_code")


def _recorded_monitor_status(*values: str | None) -> str | None:
    raw = first_field_text(*values)
    if raw is None:
        return None
    return clamp_monitor_status_or_default(raw, default="") or None


def _first_int(*values: int | None) -> int | None:
    return next((value for value in values if value is not None), None)


def _bool(obj: object | None, attr: str) -> bool:
    return bool(getattr(obj, attr, False))


def _read_meta(artifacts_dir: str | None) -> AgentMetaWire | None:
    data = _read_json_dict(artifacts_dir, "agent_meta.json")
    if data is not None:
        canonicalize_patch_metadata(data)
        data = canonicalize_agent_tribe_metadata(dict(data))
        # legacy agent-family spelling: pre-rename marker files carry
        # ``agent_family*`` / ``family_shell`` keys.
        data["agent_session_turn"] = agent_session_turn_from_mapping(data)
    return _wire_from_dict(
        AgentMetaWire,
        with_agent_session_keys(data) if data is not None else None,
    )


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
    if data is not None:
        canonicalize_patch_metadata(data)
        data["agent_session_turn"] = agent_session_turn_from_mapping(data)
    return _wire_from_dict(
        DoneMarkerWire,
        with_agent_session_keys(data) if data is not None else None,
    )


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
