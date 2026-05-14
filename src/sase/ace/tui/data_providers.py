"""ACE data-provider abstractions for read-heavy TUI surfaces."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_config import daemon_read_surface_enabled
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    AgentProjectionSummary,
    agent_list_from_dict,
)

from .models._agent_ordering import sort_and_reorder
from .models._agent_status_overrides import apply_status_overrides
from .models._dedup import (
    dedup_axe_spawned_agents,
    dedup_by_pid,
    dedup_running_vs_workflow,
    dedup_workflow_entries,
    remove_vcs_workspace_claims,
)
from .models._timestamps import parse_timestamp_14_digit
from .models.agent import Agent, AgentType
from .models.agent_loader import AgentLoadState
from .provider_contract import (
    AceFallbackMetadata,
    AceProviderCapabilities,
    AceProviderInfo,
    AceRowHandle,
    AceSnapshot,
    make_snapshot,
    trace_provider_snapshot,
)


@dataclass(frozen=True)
class _AgentsProviderSnapshot:
    """Agents-tab snapshot returned by either direct or daemon providers."""

    agents: list[Agent]
    workflow_agent_steps: list[Agent]
    load_state: AgentLoadState
    shared_snapshot: AceSnapshot[Agent]
    used_daemon: bool = False
    fallback_reason: str | None = None
    fallback_message: str | None = None
    snapshot_id: str | None = None


@dataclass(frozen=True)
class _AgentEventApplyResult:
    """Result of applying daemon agent delta events to an in-memory snapshot."""

    agents: list[Agent]
    resync_required: bool = False
    resync_reason: str | None = None


@dataclass(frozen=True)
class AgentsViewport:
    """Bounded Agents-tab read window used by daemon-backed providers."""

    start_row: int = 0
    visible_rows: int = 40
    prefetch_rows: int = 80

    @property
    def requested_limit(self) -> int:
        return max(1, self.start_row + self.visible_rows + self.prefetch_rows)


class AgentsDataProvider(Protocol):
    """Provider contract for the ACE Agents tab."""

    prefers_daemon: bool

    def load_agents(
        self,
        *,
        changespec_snapshot: list[Any] | None = None,
        full_history: bool = False,
        search_query: str | None = None,
        viewport: AgentsViewport | None = None,
    ) -> _AgentsProviderSnapshot:
        """Load an Agents-tab snapshot without touching Textual widgets."""


class _DirectAgentsDataProvider:
    """Current source-store/index-backed Agents-tab provider."""

    prefers_daemon = False

    def load_agents(
        self,
        *,
        changespec_snapshot: list[Any] | None = None,
        full_history: bool = False,
        search_query: str | None = None,
        viewport: AgentsViewport | None = None,
    ) -> _AgentsProviderSnapshot:
        from .models.agent_loader import load_tiered_agents

        del search_query, viewport
        agents, load_state = load_tiered_agents(
            changespec_snapshot=changespec_snapshot,
            full_history=full_history,
        )
        shared_snapshot = _agent_snapshot(
            agents,
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=None,
            page_count=1,
            full_reload=True,
        )
        return _AgentsProviderSnapshot(
            agents=agents,
            workflow_agent_steps=[],
            load_state=load_state,
            shared_snapshot=shared_snapshot,
            used_daemon=False,
        )


class _DaemonAgentsDataProvider:
    """Daemon projection-backed provider for the ACE Agents tab."""

    prefers_daemon = True

    def __init__(
        self,
        *,
        client: LocalDaemonClient | None = None,
        project_ids: Sequence[str] | None = None,
        direct_provider: AgentsDataProvider | None = None,
    ) -> None:
        self._client = client
        self._project_ids = list(project_ids) if project_ids is not None else None
        self._direct_provider = direct_provider or _DirectAgentsDataProvider()

    def load_agents(
        self,
        *,
        changespec_snapshot: list[Any] | None = None,
        full_history: bool = False,
        search_query: str | None = None,
        viewport: AgentsViewport | None = None,
    ) -> _AgentsProviderSnapshot:
        def direct_loader() -> _AgentsProviderSnapshot:
            return self._direct_provider.load_agents(
                changespec_snapshot=changespec_snapshot,
                full_history=full_history,
            )

        if (
            search_query or full_history
        ) and not _ace_archive_search_daemon_reads_enabled():
            snapshot = direct_loader()
            return _AgentsProviderSnapshot(
                agents=snapshot.agents,
                workflow_agent_steps=snapshot.workflow_agent_steps,
                load_state=snapshot.load_state,
                shared_snapshot=_agent_snapshot(
                    snapshot.agents,
                    provider_source="direct_fallback",
                    prefers_daemon=True,
                    fallback_reason="surface_disabled",
                    fallback_message="daemon reads disabled for ace_archive_search",
                    snapshot_id=snapshot.snapshot_id,
                    page_count=snapshot.shared_snapshot.metadata.get("page_count", 1),
                    full_reload=True,
                ),
                used_daemon=False,
                fallback_reason="surface_disabled",
                fallback_message="daemon reads disabled for ace_archive_search",
                snapshot_id=snapshot.snapshot_id,
            )

        result: DaemonReadResult[_AgentsProviderSnapshot] = read_or_fallback(
            "agent_search"
            if search_query
            else ("agent_archive" if full_history else "agent_recent"),
            client=self._client,
            required_capability="agents.read",
            daemon_loader=lambda client: self._load_daemon_snapshot(
                client,
                full_history=full_history,
                search_query=search_query,
                viewport=viewport,
            ),
            direct_loader=direct_loader,
        )
        if result.used_daemon:
            return result.value
        shared_snapshot = _agent_snapshot(
            result.value.agents,
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=result.value.snapshot_id,
            page_count=result.value.shared_snapshot.metadata.get("page_count", 1),
            full_reload=True,
        )
        return _AgentsProviderSnapshot(
            agents=result.value.agents,
            workflow_agent_steps=result.value.workflow_agent_steps,
            load_state=result.value.load_state,
            shared_snapshot=shared_snapshot,
            used_daemon=False,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=result.value.snapshot_id,
        )

    def _load_daemon_snapshot(
        self,
        client: LocalDaemonClient,
        *,
        full_history: bool,
        search_query: str | None,
        viewport: AgentsViewport | None,
    ) -> _AgentsProviderSnapshot:
        summaries: list[AgentProjectionSummary] = []
        snapshot_id: str | None = None
        page_count = 0
        next_cursor: str | None = None
        read_surfaces = _agent_daemon_surfaces(
            full_history=full_history,
            search_query=search_query,
        )
        page_limit = (viewport or AgentsViewport()).requested_limit
        for project_id in self._daemon_project_ids():
            for surface in read_surfaces:
                page = _read_agent_page(
                    client,
                    surface,
                    project_id=project_id,
                    include_hidden=True,
                    query=search_query,
                    limit=page_limit,
                )
                summaries.extend(page.agents)
                snapshot_id = snapshot_id or page.snapshot_id
                next_cursor = next_cursor or page.next_cursor
                page_count += 1

        agents = _prepare_daemon_agents(_agent_from_summary(row) for row in summaries)
        shared_snapshot = _agent_snapshot(
            agents,
            provider_source="daemon",
            prefers_daemon=True,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=snapshot_id,
            page_count=page_count,
            full_reload=False,
            requested_limit=page_limit,
            next_cursor=next_cursor,
            query=search_query,
            surfaces=read_surfaces,
        )
        return _AgentsProviderSnapshot(
            agents=agents,
            workflow_agent_steps=[],
            load_state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="daemon_projection",
                used_artifact_index=False,
            ),
            shared_snapshot=shared_snapshot,
            used_daemon=True,
            snapshot_id=snapshot_id,
        )

    def apply_event_batch(
        self,
        agents: Sequence[Agent],
        event_batch: dict[str, Any],
    ) -> _AgentEventApplyResult:
        """Apply daemon delta events produced for the agents collection."""

        return _apply_daemon_agent_events(agents, event_batch)

    def _daemon_project_ids(self) -> list[str]:
        if self._project_ids is not None:
            return list(self._project_ids)
        projects_root = Path.home() / ".sase" / "projects"
        if not projects_root.is_dir():
            return []
        return sorted(path.name for path in projects_root.iterdir() if path.is_dir())


@dataclass(frozen=True)
class _DaemonAgentPage:
    agents: list[AgentProjectionSummary]
    snapshot_id: str | None
    page_count: int
    next_cursor: str | None = None


def agents_daemon_reads_enabled() -> bool:
    """Return whether ACE should try daemon-backed Agents-tab reads."""

    value = os.environ.get("SASE_ACE_AGENTS_DAEMON_READS", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return daemon_read_surface_enabled("ace_agents")


def _ace_archive_search_daemon_reads_enabled() -> bool:
    """Return whether ACE archive/search agent reads may use daemon pages."""

    value = os.environ.get("SASE_ACE_ARCHIVE_SEARCH_DAEMON_READS", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return daemon_read_surface_enabled("ace_archive_search")


def make_agents_data_provider() -> AgentsDataProvider:
    """Return the configured Agents-tab data provider."""

    if agents_daemon_reads_enabled():
        return _DaemonAgentsDataProvider()
    return _DirectAgentsDataProvider()


def agent_row_handle(agent: Agent) -> AceRowHandle:
    """Return the stable ACE row handle for an agent row."""

    handle = _daemon_handle_for_agent(agent)
    return AceRowHandle(
        surface="agents",
        stable_id=handle,
        daemon_handle=handle,
        local_identity="|".join(str(part) for part in agent.identity),
    )


def _agent_snapshot(
    agents: Sequence[Agent],
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    page_count: int,
    full_reload: bool,
    requested_limit: int | None = None,
    next_cursor: str | None = None,
    query: str | None = None,
    surfaces: Sequence[str] | None = None,
) -> AceSnapshot[Agent]:
    snapshot = make_snapshot(
        surface="agents",
        rows=list(agents),
        row_handles=[agent_row_handle(agent) for agent in agents],
        provider=AceProviderInfo(
            identity=f"agents:{provider_source}",
            surface="agents",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(
                pages=provider_source == "daemon",
                deltas=provider_source == "daemon",
                lazy_details=provider_source == "daemon",
            ),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=snapshot_id,
        page_count=page_count,
        next_cursor=next_cursor,
        full_reload=full_reload,
        metadata={
            "requested_limit": requested_limit,
            "query": query,
            "surfaces": list(surfaces or ()),
        },
    )
    trace_provider_snapshot(snapshot)
    return snapshot


def _apply_daemon_agent_events(
    agents: Sequence[Agent],
    event_batch: dict[str, Any],
) -> _AgentEventApplyResult:
    """Apply local-daemon agent deltas to a current Agents-tab row snapshot."""

    current = list(agents)
    for event in event_batch.get("events", []):
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict):
            continue
        if "resync_required" in payload:
            reason = payload.get("resync_required")
            if isinstance(reason, dict):
                reason_value = reason.get("reason")
                return _AgentEventApplyResult(
                    current,
                    resync_required=True,
                    resync_reason=str(reason_value) if reason_value else None,
                )
            return _AgentEventApplyResult(current, resync_required=True)
        delta = payload.get("delta")
        if not isinstance(delta, dict):
            continue
        if str(delta.get("collection", "")).lower() not in {"agents", "artifacts"}:
            continue
        operation = str(delta.get("operation", ""))
        handle = str(delta.get("handle", ""))
        if operation == "invalidate":
            return _AgentEventApplyResult(
                current,
                resync_required=True,
                resync_reason=handle or "agent_delta_invalidate",
            )
        if operation == "delete":
            current = [
                agent for agent in current if _daemon_handle_for_agent(agent) != handle
            ]
            continue
        if operation in {"insert", "upsert"}:
            fields = delta.get("fields")
            if not isinstance(fields, dict):
                return _AgentEventApplyResult(
                    current,
                    resync_required=True,
                    resync_reason="agent_delta_missing_fields",
                )
            incoming = _agent_from_summary(_summary_from_delta_fields(fields))
            replaced = False
            next_agents: list[Agent] = []
            incoming_handle = _daemon_handle_for_agent(incoming)
            for agent in current:
                if _daemon_handle_for_agent(agent) == incoming_handle:
                    next_agents.append(incoming)
                    replaced = True
                else:
                    next_agents.append(agent)
            if not replaced:
                next_agents.append(incoming)
            current = _prepare_daemon_agents(next_agents)
            continue
        if operation:
            return _AgentEventApplyResult(
                current,
                resync_required=True,
                resync_reason=f"unknown_agent_delta_operation:{operation}",
            )
    return _AgentEventApplyResult(current)


def apply_daemon_agent_events(
    agents: Sequence[Agent],
    event_batch: dict[str, Any],
) -> _AgentEventApplyResult:
    """Apply daemon agent deltas to an in-memory Agents-tab snapshot."""

    return _apply_daemon_agent_events(agents, event_batch)


def _agent_daemon_surfaces(
    *,
    full_history: bool,
    search_query: str | None,
) -> list[str]:
    if search_query:
        return ["agent_search"]
    if full_history:
        return ["agent_archive"]
    return ["agent_active", "agent_recent"]


def _read_agent_page(
    client: LocalDaemonClient,
    surface: str,
    *,
    project_id: str,
    include_hidden: bool,
    query: str | None,
    limit: int,
) -> _DaemonAgentPage:
    if surface == "agent_active":
        data = client.agent_active(
            project_id=project_id,
            include_hidden=include_hidden,
            query=query,
            limit=limit,
        )
    elif surface == "agent_recent":
        data = client.agent_recent(
            project_id=project_id,
            include_hidden=include_hidden,
            query=query,
            limit=limit,
        )
    elif surface == "agent_archive":
        data = client.agent_archive(
            project_id=project_id,
            include_hidden=include_hidden,
            query=query,
            limit=limit,
        )
    elif surface == "agent_search":
        data = client.agent_search(
            project_id=project_id,
            include_hidden=include_hidden,
            query=query,
            limit=limit,
        )
    else:
        raise ValueError(f"unsupported daemon agent surface: {surface}")
    page = agent_list_from_dict(data)
    return _DaemonAgentPage(
        agents=page.agents,
        snapshot_id=page.snapshot.snapshot_id,
        page_count=1,
        next_cursor=page.page.next_cursor,
    )


def _prepare_daemon_agents(agents: Iterable[Agent]) -> list[Agent]:
    rows = list(agents)
    rows = dedup_axe_spawned_agents(rows)
    rows = remove_vcs_workspace_claims(rows)
    rows = dedup_workflow_entries(rows)
    rows = dedup_running_vs_workflow(rows)
    rows = dedup_by_pid(rows)
    apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


def _agent_from_summary(summary: AgentProjectionSummary) -> Agent:
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


def _summary_from_delta_fields(fields: dict[str, Any]) -> AgentProjectionSummary:
    from sase.daemon.read_models import agent_list_from_dict

    payload = {
        "snapshot": {"schema_version": 1, "snapshot_id": "delta"},
        "page": {"schema_version": 1, "next_cursor": None},
        "entries": {"schema_version": 1, "entries": [fields]},
    }
    return agent_list_from_dict(payload).agents[0]


def _daemon_handle_for_agent(agent: Agent) -> str:
    project = Path(agent.project_file).parent.name if agent.project_file else "unknown"
    return f"agent:{project}:{agent.raw_suffix or ''}"


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


__all__ = [
    "AceFallbackMetadata",
    "AceProviderCapabilities",
    "AceProviderInfo",
    "AceRowHandle",
    "AceSnapshot",
    "AgentsViewport",
    "AgentsDataProvider",
    "agent_row_handle",
    "agents_daemon_reads_enabled",
    "apply_daemon_agent_events",
    "make_agents_data_provider",
]
