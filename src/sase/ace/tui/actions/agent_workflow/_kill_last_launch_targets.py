"""Target resolution helpers for ``,X`` kill-and-edit-last-launch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ._launch_delta import artifact_dir_from_launch_result
from ._launch_records import LaunchRecord

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult

    from ...models import Agent


@dataclass(frozen=True)
class ResolvedLaunchTargets:
    """Exact target resolution for one session launch record."""

    agents: tuple[Agent, ...]
    unresolved_count: int = 0
    handled_count: int = 0


def agent_for_launch_result(
    agents: Sequence[Agent], result: AgentLaunchResult
) -> Agent | None:
    """Return the loaded row this session's own launch produced, if any."""
    target = artifact_dir_from_launch_result(result)
    if target is None:
        return None
    target_str = str(target)
    for agent in agents:
        found = agent.get_artifacts_dir()
        if found == target_str:
            return agent
        raw = getattr(agent, "artifacts_dir", None)
        if raw is not None and str(raw) == target_str:
            return agent
    return None


def matched_agents_for_record(
    record: LaunchRecord, agents: Sequence[Agent]
) -> list[Agent]:
    """Join a resolved record's launch results to currently loaded rows.

    Iterates in ``record.proc_ids`` order (launch/mark order); a result with
    no loaded row (already killed or dismissed by hand since launch) is
    skipped rather than treated as an error.
    """
    matched: list[Agent] = []
    seen: set[object] = set()
    for proc_id in record.proc_ids:
        for result in record.results.get(proc_id, ()):
            agent = agent_for_launch_result(agents, result)
            if agent is None or agent.identity in seen:
                continue
            seen.add(agent.identity)
            matched.append(agent)
    return matched


def resolve_agents_for_record(
    app: object,
    record: LaunchRecord,
    agents: Sequence[Agent],
    *,
    match_record_agents: Callable[[LaunchRecord, Sequence[Agent]], list[Agent]]
    | None = None,
) -> ResolvedLaunchTargets:
    """Resolve all unhandled launch results without treating cache misses as dead."""
    pending_results = unhandled_launch_results(record, all_record_results(record))
    if not pending_results:
        return ResolvedLaunchTargets(
            agents=(),
            handled_count=len(record.handled_result_keys),
        )

    matcher = match_record_agents or matched_agents_for_record
    loaded_matches = matcher(record, agents)
    if len(loaded_matches) == len(pending_results):
        return ResolvedLaunchTargets(agents=tuple(loaded_matches))

    matched: list[Agent] = []
    seen: set[object] = set()
    unresolved = 0
    handled = 0
    for result in pending_results:
        key = launch_result_key(result)
        if _launch_result_confirmed_handled(app, result):
            record.handled_result_keys.add(key)
            handled += 1
            continue

        agent = agent_for_launch_result(agents, result)
        if agent is None:
            agent = synthetic_agent_from_launch_result(result)
            if agent is not None:
                ensure_agent_visible(app, agent)
        if agent is None:
            unresolved += 1
            continue

        identity = getattr(agent, "identity", id(agent))
        if identity in seen:
            continue
        seen.add(identity)
        matched.append(agent)

    return ResolvedLaunchTargets(
        agents=tuple(matched),
        unresolved_count=unresolved,
        handled_count=handled,
    )


def notify_unresolved_launch_targets(
    app: object,
    record: LaunchRecord,
    count: int,
) -> None:
    schedule_launch_target_refresh(app, all_record_results(record))
    suffix = "" if count == 1 else "s"
    notify_app(
        app,
        f'"{record.display_name}" still has {count} launch target{suffix} '
        "resolving; press ,X again after refresh",
        severity="warning",
    )


def _launch_result_confirmed_handled(
    app: object,
    result: AgentLaunchResult,
) -> bool:
    dismissed_objects = tuple(getattr(app, "_dismissed_agent_objects", ()) or ())
    if dismissed_objects and agent_for_launch_result(dismissed_objects, result):
        return True
    dismissed: set[object] = getattr(app, "_dismissed_agents", set()) or set()
    if not dismissed:
        return False
    synthetic = synthetic_agent_from_launch_result(result)
    identity = getattr(synthetic, "identity", None) if synthetic is not None else None
    return identity in dismissed


def all_record_results(record: LaunchRecord) -> tuple[AgentLaunchResult, ...]:
    results: list[AgentLaunchResult] = []
    for proc_id in record.proc_ids:
        results.extend(record.results.get(proc_id, ()))
    return tuple(results)


def unhandled_launch_results(
    record: LaunchRecord,
    results: Sequence[AgentLaunchResult],
) -> tuple[AgentLaunchResult, ...]:
    pending: list[AgentLaunchResult] = []
    for result in results:
        key = launch_result_key(result)
        if key in record.handled_result_keys:
            continue
        if key in record.kill_in_progress_result_keys:
            continue
        pending.append(result)
    return tuple(pending)


def record_results_are_handled(record: LaunchRecord) -> bool:
    keys = {launch_result_key(result) for result in all_record_results(record)}
    return (
        bool(keys)
        and not record.kill_in_progress_result_keys
        and keys <= (record.handled_result_keys)
    )


def mark_all_record_results_handled(record: LaunchRecord) -> None:
    record.handled_result_keys.update(
        launch_result_key(result) for result in all_record_results(record)
    )


def launch_result_key(result: AgentLaunchResult) -> str:
    artifact_dir = artifact_dir_from_launch_result(result)
    if artifact_dir is not None:
        return f"artifact:{Path(artifact_dir).expanduser()}"
    artifacts_dir = getattr(result, "artifacts_dir", "")
    if artifacts_dir:
        return f"artifact:{Path(str(artifacts_dir)).expanduser()}"
    output_path = getattr(result, "output_path", "")
    if output_path:
        return f"output:{Path(str(output_path)).expanduser()}"
    return "|".join(
        str(part)
        for part in (
            getattr(result, "project_name", ""),
            getattr(result, "workflow_name", ""),
            getattr(result, "timestamp", ""),
            getattr(result, "workspace_dir", ""),
            getattr(result, "workspace_num", ""),
            getattr(result, "pid", ""),
            getattr(result, "agent_name", ""),
        )
    )


def schedule_launch_target_refresh(
    app: object,
    results: Sequence[AgentLaunchResult],
) -> None:
    if results:
        handle_delta = getattr(app, "_handle_launch_results_delta", None)
        if callable(handle_delta):
            try:
                handle_delta(tuple(results), source="last_launch")
                return
            except TypeError:
                handle_delta(tuple(results))
                return
    schedule_refresh = getattr(app, "_schedule_agents_async_refresh", None)
    if callable(schedule_refresh):
        schedule_refresh(source="last_launch")
        return
    request_refresh = getattr(app, "request_agents_refresh", None)
    if callable(request_refresh):
        request_refresh("last_launch")


def is_gate_dismissable(agent: Agent) -> bool:
    if not getattr(agent, "is_gate", False):
        return False
    from sase.gate_shell.state import gate_state_is_terminal

    return bool(gate_state_is_terminal(agent.gate_state) or agent.stop_time)


def ensure_agent_visible(app: object, agent: Agent) -> None:
    """Inject *agent* so bulk/single kill can see it in ``_agents_with_children``."""
    children = getattr(app, "_agents_with_children", None)
    if not isinstance(children, list):
        cast(Any, app)._agents_with_children = [agent]
        children = app._agents_with_children  # type: ignore[attr-defined]
    identity = getattr(agent, "identity", None)
    if identity is not None and any(
        getattr(existing, "identity", None) == identity for existing in children
    ):
        return
    children.append(agent)
    agents = getattr(app, "_agents", None)
    if isinstance(agents, list) and agent not in agents:
        agents.append(agent)


def synthetic_agent_from_launch_result(result: AgentLaunchResult) -> Agent | None:
    """Build a killable row from a launch result when the Agents tab has none yet."""
    from sase.ace.tui.models._timestamps import normalize_to_14_digit
    from sase.ace.tui.models.agent import Agent, AgentType

    artifact_dir = artifact_dir_from_launch_result(result)
    artifacts_dir = (
        str(artifact_dir)
        if artifact_dir is not None
        else (result.artifacts_dir or None)
    )
    if artifacts_dir is None:
        return None
    raw_suffix = normalize_to_14_digit(result.timestamp)
    if raw_suffix is None and artifacts_dir:
        raw_suffix = normalize_to_14_digit(Path(artifacts_dir).name)
    pid = result.pid if result.pid else None
    cl_name = result.cl_name or result.agent_name or "agent"
    status = "WAITING" if pid is None else "RUNNING"
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=result.project_file or "",
        status=status,
        start_time=None,
        pid=pid,
        raw_suffix=raw_suffix,
        artifacts_dir=artifacts_dir,
        agent_name=result.agent_name or cl_name,
        workspace_num=result.workspace_num or None,
        workflow=result.workflow_name or None,
    )


def notify_app(app: object, message: str, *, severity: str | None = None) -> None:
    notify = getattr(app, "notify", None)
    if callable(notify):
        if severity is None:
            notify(message)
        else:
            notify(message, severity=severity)
