"""Capacity-record construction and runner-slot row predicates."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.agent.status_buckets import PRE_RUN_WAIT_STATUSES, agent_status_bucket
from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.agent_hold_facade import candidate_created_at_from_timestamp
from sase.core.runner_slots import DEFAULT_QUEUE_WEIGHT, runner_slot_queue_display_key

from .agent import Agent
from .agent_status import DISMISSABLE_STATUSES


def clan_container_lookup(
    agents: list[Agent],
) -> dict[tuple[str | None, str | None], Agent]:
    return {
        (agent.agent_clan, agent.agent_clan_generation): agent
        for agent in agents
        if agent.is_clan_container and agent.agent_clan
    }


def capacity_record_from_agent(
    agent: Agent,
    parsed_artifact_paths: dict[str, Any],
    *,
    clan_containers: dict[tuple[str | None, str | None], Agent] | None = None,
) -> dict[str, Any]:
    artifacts_dir = capacity_artifact_dir(agent)
    parsed = parsed_artifact_path(agent, parsed_artifact_paths)
    membership = tui_hold_membership_tribes(agent, clan_containers or {})
    from sase.core.agent_hold_identity import primary_hold_tribe

    container = (clan_containers or {}).get(
        (agent.agent_clan, agent.agent_clan_generation)
    )
    effective_clan = (
        agent.clan_tribe
        if agent.is_clan_container
        else (container.clan_tribe if container is not None else agent.clan_tribe)
    )
    return {
        "artifact_dir": artifacts_dir,
        "project_name": project_name(agent, parsed),
        "workflow_dir_name": workflow_dir_name(agent, parsed),
        "timestamp": capacity_timestamp(agent),
        "agent_name": agent.agent_name,
        "workflow": agent.workflow,
        "clan": agent.agent_clan,
        "tribe": primary_hold_tribe(
            membership, preferred=(agent.tribe, effective_clan)
        ),
        "tribes": list(membership),
        "created_at": candidate_created_at_from_timestamp(capacity_timestamp(agent)),
        "has_agent_meta": not (agent.is_clan_container or agent.is_proc_shell),
        "has_done_marker": agent.stop_time is not None
        or agent.status in {"DONE", "FAILED", "FAILED (RETRIED)"},
        "appears_as_agent": appears_as_agent(agent),
        "live": capacity_record_is_live(agent),
        "pending_question": agent.runner_slot_yielded,
        "pid": agent.pid,
        "run_started_at": capacity_run_started_at(agent),
        "parent_timestamp": agent.parent_timestamp,
        "agent_family": capacity_agent_family(agent),
        "agent_family_role": agent.agent_family_role,
        "agent_family_parallel": agent.agent_family_parallel,
        "family_shell_kind": family_shell_kind(agent),
        "family_shell_id": family_shell_id(agent),
        "family_shell_state": family_shell_state(agent),
        "queue_weight": None
        if agent.queue_weight_invalid
        else finite_float(agent.queue_weight),
        "queue_weight_explicit": agent.queue_weight_explicit,
        "queue_weight_invalid": agent.queue_weight_invalid,
        "slot_requested_at": agent.slot_requested_at
        if is_live_slot_waiter(agent)
        else None,
        "queue_capacity": nonnegative_int(
            agent.queue_capacity
            if agent.queue_capacity is not None
            else agent.wait_runners
        ),
        "queue_capacity_explicit": (
            agent.queue_capacity_explicit or agent.wait_runners_explicit
        ),
        "wait_priority": nonnegative_int(agent.wait_priority),
        "eligible_since": None,
    }


def tui_hold_membership_tribes(
    agent: Agent,
    clan_containers: dict[tuple[str | None, str | None], Agent],
) -> tuple[str, ...]:
    from sase.core.agent_hold_identity import hold_membership_tribes

    container = clan_containers.get((agent.agent_clan, agent.agent_clan_generation))
    effective_clan = (
        agent.clan_tribe
        if agent.is_clan_container
        else (container.clan_tribe if container is not None else agent.clan_tribe)
    )
    return hold_membership_tribes(direct=(agent.tribe,), effective_clan=effective_clan)


def capacity_artifact_dir(agent: Agent) -> str:
    if agent.artifacts_dir:
        return agent.artifacts_dir
    agent_type, cl_name, raw_suffix = agent.identity
    suffix = raw_suffix or agent.raw_suffix or cl_name
    return f"memory://{agent_type.value}/{cl_name}/{suffix}"


def parsed_artifact_path(
    agent: Agent, parsed_artifact_paths: dict[str, Any]
) -> Any | None:
    """Parse *agent*'s real artifact dir at most once per caching pass."""
    artifacts_dir = agent.artifacts_dir
    if not artifacts_dir:
        return None
    if artifacts_dir not in parsed_artifact_paths:
        try:
            parsed_artifact_paths[artifacts_dir] = parse_agent_artifact_path(
                artifacts_dir
            )
        except (OSError, RuntimeError, ValueError):
            parsed_artifact_paths[artifacts_dir] = None
    return parsed_artifact_paths[artifacts_dir]


def project_name(agent: Agent, parsed: Any | None) -> str:
    if agent.project_file:
        name = Path(agent.project_file).parent.name
        if name:
            return name
    if parsed is not None:
        return parsed.project_name
    if agent.artifacts_dir:
        try:
            return Path(agent.artifacts_dir).parents[2].name
        except IndexError:
            pass
    return ""


def workflow_dir_name(agent: Agent, parsed: Any | None) -> str:
    if parsed is not None:
        return parsed.workflow_dir_name
    if agent.artifacts_dir:
        workflow = Path(agent.artifacts_dir).parent.name
        if workflow:
            return workflow
    if agent.workflow:
        return agent.workflow
    return "ace-run" if is_ace_run_root(agent) or agent.is_child_row else ""


def capacity_timestamp(agent: Agent) -> str:
    if agent.raw_suffix:
        return agent.raw_suffix
    if agent.artifacts_dir:
        return Path(agent.artifacts_dir).name
    return agent.cl_name


def appears_as_agent(agent: Agent) -> bool:
    return not (agent.is_clan_container or agent.is_proc_shell) and (
        agent.appears_as_agent or is_ace_run_root(agent) or agent.is_child_row
    )


def capacity_record_is_live(agent: Agent) -> bool:
    return bool(agent.runner_is_live or agent.pid is not None)


def capacity_run_started_at(agent: Agent) -> str | None:
    if agent.run_start_time is not None:
        return agent.run_start_time.isoformat()
    if agent.pid is not None and agent_lane_bucket_counts_as_running(agent):
        return None if agent.start_time is None else agent.start_time.isoformat()
    return None


def capacity_agent_family(agent: Agent) -> str | None:
    if agent.agent_family:
        return agent.agent_family
    return (
        agent.parent_timestamp
        if agent.parent_timestamp and not agent.agent_family_parallel
        else None
    )


def family_shell_kind(agent: Agent) -> str | None:
    if agent.is_gate:
        return "gate"
    return "monitor" if agent.is_monitor else None


def family_shell_id(agent: Agent) -> str | None:
    if agent.is_gate:
        return agent.gate_id
    return agent.monitor_id if agent.is_monitor else None


def family_shell_state(agent: Agent) -> str | None:
    if agent.is_gate:
        return agent.gate_state
    return agent.monitor_state if agent.is_monitor else None


def finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def waiter_threshold(waiter: dict[str, Any]) -> int | None:
    for key in ("queue_capacity", "wait_runners"):
        threshold = nonnegative_int(waiter.get(key))
        if threshold is not None:
            return threshold
    return None


def int_value(value: object) -> int | None:
    return value if type(value) is int else None


def positive_int(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def text_value(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def blocker_tuple(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(blocker) for blocker in value if isinstance(blocker, dict))


def ordered_snapshot_waiters(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list | tuple):
        return ()
    indexed = [
        (i, dict(waiter)) for i, waiter in enumerate(value) if isinstance(waiter, dict)
    ]
    indexed.sort(
        key=lambda item: (
            positive_int(item[1].get("queue_position")) is None,
            positive_int(item[1].get("queue_position")) or item[0] + 1,
            item[0],
        )
    )
    return tuple(waiter for _, waiter in indexed)


def snapshot_waiter_is_parked(waiter: dict[str, Any]) -> bool:
    if waiter.get("eligible") is True:
        return False
    return any(
        blocker.get("code") != "queue-order"
        for blocker in blocker_tuple(waiter.get("blockers"))
    )


def agent_lane_bucket_counts_as_running(agent: Agent) -> bool:
    return (
        agent_status_bucket(agent) == "Running"
        and agent.status not in DISMISSABLE_STATUSES
    )


def container_is_genuinely_occupying(agent: Agent) -> bool:
    return (
        agent.pid is not None
        and agent.run_start_time is not None
        and agent.stop_time is None
        and not agent.runner_slot_yielded
        and agent.status not in {"DONE", "FAILED", "FAILED (RETRIED)"}
    )


def is_ace_run_root(agent: Agent) -> bool:
    if agent.is_clan_container or agent.is_child_row:
        return False
    if agent.slot_requested_at:
        return True
    if agent.artifacts_dir and Path(agent.artifacts_dir).parent.name == "ace-run":
        return True
    if agent.appears_as_agent:
        return True
    workflow = agent.workflow or ""
    return workflow == "ace-run" or workflow.startswith("ace(run)")


def participates_in_runner_slots(agent: Agent) -> bool:
    return is_ace_run_root(agent) or agent.is_family_member_child


def is_live_slot_waiter(agent: Agent) -> bool:
    return (
        participates_in_runner_slots(agent)
        and agent.pid is not None
        and bool(agent.slot_requested_at)
        and agent.status in PRE_RUN_WAIT_STATUSES
    )


def waiter_sort_key(
    agent: Agent, *, running_count: int
) -> tuple[int, int, int, int, datetime, str, str]:
    return runner_slot_queue_display_key(
        running_count=running_count,
        threshold=agent.wait_runners,
        priority=agent.wait_priority,
        slot_requested_at=agent.slot_requested_at,
        timestamp=agent.raw_suffix,
        artifact_dir=agent.artifacts_dir,
    )
