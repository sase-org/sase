"""Agent CLI conversion helpers for daemon-backed projection reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sase.agent.running import RunningAgentInfo
from sase.core.time import get_timezone
from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_models import (
    AgentArtifactAssociation,
    AgentDetailRead,
    AgentProjectionSummary,
    agent_detail_from_dict,
    agent_list_from_dict,
)


@dataclass(frozen=True)
class AgentShowData:
    name: str
    status_line: str
    artifacts_dir: str
    project: str
    model: str | None = None
    provider: str | None = None
    pid: int | None = None
    finished_at: str | None = None
    outcome: str | None = None
    prompt_text: str | None = None
    live_tail: bool = False


def load_status_agents(
    client: LocalDaemonClient,
    *,
    project_id: str,
    include_all: bool,
) -> list[RunningAgentInfo]:
    """Load agent status rows from daemon projections for one project."""

    active = [
        _running_info_from_summary(summary)
        for summary in _iter_agent_summaries(
            client,
            "active",
            project_id=project_id,
            limit=LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        )
    ]
    if not include_all:
        return active

    recent = [
        _running_info_from_summary(summary)
        for summary in _iter_agent_summaries(
            client, "recent", project_id=project_id, limit=50
        )
    ]
    return active + recent


def load_agent_show_by_handle(
    client: LocalDaemonClient,
    *,
    agent_id: str,
    project_id: str | None = None,
) -> AgentShowData | None:
    """Load an agent detail row when the CLI argument is an agent handle."""

    resolved_project_id = project_id or project_id_from_agent_id(agent_id)
    if not resolved_project_id:
        return None
    detail = agent_detail_from_dict(
        client.agent_detail(project_id=resolved_project_id, agent_id=agent_id)
    )
    return _show_data_from_detail(detail)


def load_agent_show_by_name(
    client: LocalDaemonClient,
    *,
    name: str,
    project_id: str,
) -> AgentShowData | None:
    """Resolve a stable agent name in one project, then load daemon detail."""

    matches = list(
        _iter_agent_summaries(
            client,
            "search",
            project_id=project_id,
            limit=LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
            query=name,
        )
    )
    summary = _best_name_match(matches, name)
    if summary is None:
        return None
    detail = agent_detail_from_dict(
        client.agent_detail(project_id=summary.project_id, agent_id=summary.agent_id)
    )
    return _show_data_from_detail(detail)


def _running_info_from_summary(summary: AgentProjectionSummary) -> RunningAgentInfo:
    status = _cli_status_from_summary(summary)
    started_at = _summary_started_at(summary)
    duration = "?"
    duration_seconds: int | None = None

    if status == "RUNNING" and started_at is not None:
        duration_seconds = int(
            (datetime.now(get_timezone()) - started_at).total_seconds()
        )
        duration = _format_duration(duration_seconds)
    elif status in {"DONE", "FAILED"} and started_at is not None:
        finished_at = _summary_finished_at(summary)
        if finished_at is not None:
            duration_seconds = int((finished_at - started_at).total_seconds())
            duration = _format_duration(max(duration_seconds, 0))

    return RunningAgentInfo(
        name=summary.agent_name,
        project=summary.project_name,
        pid=_extra_int(summary.extra, "pid"),
        model=summary.model,
        provider=summary.llm_provider,
        workspace_num=_workspace_num(summary),
        duration=duration,
        approve=bool(summary.extra.get("approve", False)),
        prompt=_extra_str(summary.extra, "prompt_snippet")
        or _extra_str(summary.extra, "raw_prompt_snippet")
        or _extra_str(summary.extra, "prompt"),
        status=status,
        started_at=started_at,
        duration_seconds=duration_seconds,
        artifacts_dir=summary.artifact_dir,
    )


def _show_data_from_detail(detail: AgentDetailRead) -> AgentShowData:
    summary = detail.summary
    status = _cli_status_from_summary(summary)
    outcome = _outcome_from_summary(summary)
    status_line = (
        f"DONE ({outcome or 'completed'})" if status in {"DONE", "FAILED"} else status
    )

    return AgentShowData(
        name=summary.agent_name or summary.agent_id,
        status_line=status_line,
        artifacts_dir=summary.artifact_dir,
        project=summary.project_name,
        model=summary.model,
        provider=summary.llm_provider,
        pid=_extra_int(summary.extra, "pid") or _extra_int(detail.extra, "pid"),
        finished_at=_finished_at_label(summary),
        outcome=outcome,
        prompt_text=_prompt_from_detail(detail),
        live_tail=status not in {"DONE", "FAILED"},
    )


def project_id_from_agent_id(agent_id: str) -> str | None:
    parts = agent_id.split(":", 2)
    if len(parts) == 3 and parts[0] == "agent" and parts[1]:
        return parts[1]
    return None


def _cli_status_from_summary(summary: AgentProjectionSummary) -> str:
    status = summary.status.lower()
    if summary.has_done_marker or status in {
        "done",
        "completed",
        "failed",
        "cancelled",
    }:
        return "FAILED" if status == "failed" else "DONE"
    if summary.has_waiting_marker or status == "waiting":
        return "WAITING"
    if status == "starting":
        return "STARTING"
    return "RUNNING"


def _iter_agent_summaries(
    client: LocalDaemonClient,
    surface: str,
    *,
    project_id: str,
    limit: int,
    query: str | None = None,
) -> list[AgentProjectionSummary]:
    cursor: str | None = None
    out: list[AgentProjectionSummary] = []
    while True:
        if surface == "active":
            data = client.agent_active(
                project_id=project_id, limit=limit, cursor=cursor
            )
        elif surface == "recent":
            data = client.agent_recent(
                project_id=project_id, limit=limit, cursor=cursor
            )
        elif surface == "search":
            data = client.agent_search(
                project_id=project_id,
                query=query,
                limit=limit,
                cursor=cursor,
            )
        else:
            raise ValueError(f"unsupported agent daemon list surface: {surface}")
        page = agent_list_from_dict(data)
        out.extend(page.agents)
        cursor = page.page.next_cursor
        if not cursor:
            return out


def _best_name_match(
    summaries: list[AgentProjectionSummary], name: str
) -> AgentProjectionSummary | None:
    exact = [summary for summary in summaries if summary.agent_name == name]
    if exact:
        return exact[0]
    handle = [summary for summary in summaries if summary.agent_id == name]
    if handle:
        return handle[0]
    return summaries[0] if summaries else None


def _summary_started_at(summary: AgentProjectionSummary) -> datetime | None:
    if summary.started_at:
        try:
            parsed = datetime.fromisoformat(summary.started_at.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            return (
                parsed
                if parsed.tzinfo is not None
                else parsed.replace(tzinfo=get_timezone())
            )
    return _parse_timestamp(summary.timestamp)


def _summary_finished_at(summary: AgentProjectionSummary) -> datetime | None:
    if summary.finished_at is None:
        return None
    return datetime.fromtimestamp(summary.finished_at, get_timezone())


def _finished_at_label(summary: AgentProjectionSummary) -> str | None:
    raw = summary.extra.get("finished_at")
    if isinstance(raw, str):
        return raw
    if summary.finished_at is None:
        return None
    return str(summary.finished_at)


def _outcome_from_summary(summary: AgentProjectionSummary) -> str | None:
    raw = summary.extra.get("outcome")
    if isinstance(raw, str) and raw:
        return raw
    status = summary.status.lower()
    if status == "failed":
        return "failed"
    if summary.has_done_marker or status in {"done", "completed"}:
        return "completed"
    return None


def _prompt_from_detail(detail: AgentDetailRead) -> str | None:
    for source in (detail.extra, detail.summary.extra):
        for key in ("prompt", "raw_prompt", "raw_prompt_text", "raw_prompt_snippet"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    prompt_artifact = _artifact_by_kind(detail.artifacts, "prompt")
    return prompt_artifact.artifact_path if prompt_artifact is not None else None


def _artifact_by_kind(
    artifacts: list[AgentArtifactAssociation], kind: str
) -> AgentArtifactAssociation | None:
    for artifact in artifacts:
        if artifact.artifact_kind == kind:
            return artifact
    return None


def _workspace_num(summary: AgentProjectionSummary) -> int | None:
    return _extra_int(summary.extra, "workspace_num") or _extra_int(
        summary.extra, "workspace_number"
    )


def _extra_int(values: dict[str, Any], key: str) -> int | None:
    value = values.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _extra_str(values: dict[str, Any], key: str) -> str | None:
    value = values.get(key)
    return value if isinstance(value, str) else None


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h{minutes}m"
    if minutes > 0:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


def _parse_timestamp(timestamp: str) -> datetime | None:
    try:
        return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=get_timezone()
        )
    except ValueError:
        return None
