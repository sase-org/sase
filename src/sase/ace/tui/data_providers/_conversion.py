"""Conversion helpers between daemon projections and TUI agent rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.daemon.read_models import AgentProjectionSummary, agent_list_from_dict

from ..models._timestamps import parse_timestamp_14_digit
from ..models.agent import Agent, AgentType


def agent_from_summary(summary: AgentProjectionSummary) -> Agent:
    extra = summary.extra
    agent_type = (
        AgentType.WORKFLOW
        if summary.agent_type.lower() == "workflow"
        else AgentType.RUNNING
    )
    status = _tui_status_from_summary(summary)
    start_time = _summary_start_time(summary)
    stop_time = _summary_stop_time(summary)
    workflow = _summary_workflow_name(summary, agent_type)
    step_output = extra.get("step_output")
    return Agent(
        agent_type=agent_type,
        cl_name=summary.cl_name or summary.project_name or "unknown",
        project_file=summary.project_file,
        status=status,
        start_time=start_time,
        run_start_time=_parse_datetime(summary.started_at),
        stop_time=stop_time,
        workspace_num=_optional_int(extra.get("workspace_num")),
        workflow=workflow,
        pid=_optional_int(extra.get("pid")),
        raw_suffix=summary.timestamp,
        response_path=_optional_str(extra.get("response_path")),
        diff_path=_optional_str(extra.get("diff_path")),
        extra_files=_string_list(extra.get("extra_files")),
        parent_workflow=_optional_str(extra.get("parent_workflow")),
        parent_timestamp=_optional_str(extra.get("parent_timestamp")),
        step_name=_optional_str(extra.get("step_name")),
        step_type=_optional_str(extra.get("step_type")),
        step_source=_optional_str(extra.get("step_source")),
        step_output=step_output if isinstance(step_output, dict) else None,
        step_index=_optional_int(extra.get("step_index")),
        total_steps=_optional_int(extra.get("total_steps")),
        appears_as_agent=bool(extra.get("appears_as_agent", False)),
        is_anonymous=bool(extra.get("is_anonymous", False)),
        error_message=_optional_str(extra.get("error_message")),
        error_traceback=_optional_str(extra.get("error_traceback")),
        output_path=_optional_str(extra.get("output_path")),
        model=summary.model,
        llm_provider=summary.llm_provider,
        vcs_provider=_optional_str(extra.get("vcs_provider")),
        workspace_dir=_optional_str(extra.get("workspace_dir")),
        agent_name=summary.agent_name,
        artifacts_dir=summary.artifact_dir,
        hidden=summary.hidden,
        approve=bool(extra.get("approve", False)),
        tag=_optional_str(extra.get("tag")),
    )


def summary_from_delta_fields(fields: dict[str, Any]) -> AgentProjectionSummary:
    payload = {
        "snapshot": {"schema_version": 1, "snapshot_id": "delta"},
        "page": {"schema_version": 1, "next_cursor": None},
        "entries": {"schema_version": 1, "entries": [fields]},
    }
    return agent_list_from_dict(payload).agents[0]


def _tui_status_from_summary(summary: AgentProjectionSummary) -> str:
    raw = summary.status.lower().replace("_", " ")
    outcome = str(summary.extra.get("outcome", "")).lower()
    if raw in {"failed", "failure"} or outcome == "failed":
        if summary.extra.get("retried_as_timestamp"):
            return "FAILED (RETRIED)"
        return "FAILED"
    if raw in {"done", "completed", "complete", "cancelled"} or summary.has_done_marker:
        if outcome == "plan_rejected":
            return "PLAN REJECTED"
        return "DONE"
    if (
        raw in {"waiting", "waiting input", "waiting hitl"}
        or summary.has_waiting_marker
    ):
        return "WAITING INPUT" if "input" in raw or "hitl" in raw else "WAITING"
    if raw in {"plan", "plan approved", "tale approved", "question", "retrying"}:
        return raw.upper()
    if raw == "starting":
        return "STARTING"
    return "RUNNING"


def _summary_start_time(summary: AgentProjectionSummary) -> datetime | None:
    return parse_timestamp_14_digit(summary.timestamp) or _parse_datetime(
        summary.started_at
    )


def _summary_stop_time(summary: AgentProjectionSummary) -> datetime | None:
    if summary.finished_at is None:
        return None
    return datetime.fromtimestamp(summary.finished_at)


def _summary_workflow_name(
    summary: AgentProjectionSummary,
    agent_type: AgentType,
) -> str | None:
    if agent_type is AgentType.RUNNING:
        return summary.workflow_dir_name or None
    if summary.agent_name:
        return summary.agent_name
    name = summary.workflow_dir_name
    return name.removeprefix("workflow-") if name else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]
