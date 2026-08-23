"""External wait resolution and unit dispatch for launch admission."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import agent_unit_dispatch_prompt
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchPlanWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)


class ConditionEvaluator(Protocol):
    def __call__(
        self,
        unit: LaunchUnitWire,
        waited_outcomes: list[dict[str, Any]],
        context: Mapping[str, Any],
    ) -> tuple[str, str | None]:
        """Return ``eligible`` / ``skipped`` / ``condition_error`` plus message."""


class UnitDispatcher(Protocol):
    def __call__(
        self,
        unit: LaunchUnitWire,
        fingerprint: str,
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        """Return ok, identity, message, and any spawned agent results."""


class WaitResolver(Protocol):
    def __call__(
        self,
        plan: LaunchPlanWire,
        states: dict[str, dict[str, Any]],
        *,
        now: float,
        waiting_since: Mapping[str, float],
    ) -> list[dict[str, Any]]:
        """Return wait facts for non-logical targets."""


def resolve_external_wait_facts(
    plan: LaunchPlanWire,
    states: dict[str, dict[str, Any]],
    *,
    now: float,
    waiting_since: Mapping[str, float],
) -> list[dict[str, Any]]:
    """Resolve agent, proc, bead, and time waits without taking resources."""

    del states
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in plan.units:
        started = float(waiting_since.get(unit.logical_id, now))
        for wait in unit.waits:
            key = f"{wait.kind}:{wait.logical_id or wait.name or wait.identifier or wait.bead_id or wait.value}"
            if wait.kind == "logical" or key in seen:
                continue
            seen.add(key)
            fact = _resolve_one_wait(wait, plan, now=now, started=started)
            if fact is not None:
                facts.append(fact)
    return facts


def evaluate_launch_condition(
    unit: LaunchUnitWire,
    waited_outcomes: list[dict[str, Any]],
    context: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Sandbox ``unit.condition`` and return a durable admission verdict."""

    from sase.agent.launch_condition_runtime import (
        evaluate_launch_condition as evaluate_sandboxed,
    )

    return evaluate_sandboxed(unit, waited_outcomes, context)


def dispatch_agent_unit(
    unit: LaunchUnitWire,
    fingerprint: str,
) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
    """Dispatch one eligible agent through the established launch path."""

    if not isinstance(unit.payload, AgentUnitWire):
        return False, None, "not_an_agent_unit", []
    prompt = agent_unit_dispatch_prompt(unit.payload)
    extra_env = {
        "SASE_LAUNCH_DISPATCH_FINGERPRINT": fingerprint,
        "SASE_LAUNCH_LOGICAL_ID": unit.logical_id,
    }
    from sase.agent import launcher as launcher_mod

    results = launcher_mod.launch_agents_from_cwd(prompt, extra_env=extra_env)
    if not results:
        return False, None, "agent_dispatch_produced_no_results", []
    identity = results[0].agent_name or f"pid:{results[0].pid}"
    return True, identity, None, list(results)


def dispatch_proc_unit(
    unit: LaunchUnitWire,
    fingerprint: str,
    context: Mapping[str, Any] | None = None,
) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
    """Dispatch one eligible stand-alone `%proc` through the native supervisor."""

    if not isinstance(unit.payload, ProcUnitWire):
        return False, None, "not_a_proc_unit", []
    from sase.agent.launch_proc_runtime import dispatch_proc_unit as hooked

    return hooked(unit, fingerprint, context)


def call_proc_dispatcher(
    dispatcher: UnitDispatcher,
    unit: LaunchUnitWire,
    fingerprint: str,
    context: Mapping[str, Any],
) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
    if dispatcher is dispatch_proc_unit:
        return dispatch_proc_unit(unit, fingerprint, context)
    return dispatcher(unit, fingerprint)


def stop_proc_identity(identity: str) -> None:
    try:
        from sase.procs.models import TERMINAL_PROC_STATUSES
        from sase.procs.service import stop_proc_shell
        from sase.procs.store import get_proc

        proc = get_proc(identity)
        if proc is None or proc.status in TERMINAL_PROC_STATUSES:
            return
        stop_proc_shell(proc, requested_by="launch-admission")
    except Exception:
        return


def _resolve_one_wait(
    wait: WaitTargetWire,
    plan: LaunchPlanWire,
    *,
    now: float,
    started: float,
) -> dict[str, Any] | None:
    target = agent_launch_wire_to_json_dict(wait)
    if wait.kind == "time":
        return _resolve_time_wait(wait, target, now=now, started=started)
    if wait.kind == "agent" and wait.name:
        return _resolve_agent_wait(wait.name, target)
    if wait.kind == "proc" and wait.identifier:
        return _resolve_proc_wait(wait.identifier, target)
    if wait.kind == "bead" and wait.bead_id:
        return _resolve_bead_wait(wait.bead_id, plan.selected_project, target)
    return None


def _resolve_time_wait(
    wait: WaitTargetWire,
    target: dict[str, Any],
    *,
    now: float,
    started: float,
) -> dict[str, Any]:
    from sase.xprompt._directive_time import parse_absolute_time, parse_duration

    value = str(wait.value or "")
    duration = parse_duration(value)
    if duration is not None:
        resolved = now >= started + duration
        return {
            "target": target,
            "resolved": resolved,
            "outcome": "launched" if resolved else None,
        }
    try:
        iso = parse_absolute_time(value)
    except Exception:
        iso = None
    if iso:
        from datetime import datetime

        try:
            resolved = now >= datetime.fromisoformat(iso).timestamp()
        except ValueError:
            resolved = False
        return {
            "target": target,
            "resolved": resolved,
            "outcome": "launched" if resolved else None,
        }
    return {"target": target, "resolved": False}


def _resolve_agent_wait(name: str, target: dict[str, Any]) -> dict[str, Any]:
    from sase.agent.names import find_named_agent
    from sase.core.dismissed_agent_completion import (
        FAILURE_OUTCOMES,
        KNOWN_DONE_OUTCOMES,
        WAIT_SUCCESS_OUTCOMES,
    )

    agent = find_named_agent(name)
    if agent is None or not agent.is_done:
        return {"target": target, "resolved": False}
    outcome = agent.outcome if agent.outcome in KNOWN_DONE_OUTCOMES else "failed"
    launch_outcome = "launched" if outcome in WAIT_SUCCESS_OUTCOMES else "launch_error"
    if outcome in FAILURE_OUTCOMES:
        launch_outcome = "launch_error"
    return {
        "target": target,
        "resolved": True,
        "outcome": launch_outcome,
        "identity": agent.name,
        "message": outcome,
    }


def _resolve_proc_wait(identifier: str, target: dict[str, Any]) -> dict[str, Any]:
    from sase.procs.models import TERMINAL_PROC_STATUSES
    from sase.procs.store import get_proc, read_procs

    proc = get_proc(identifier)
    if proc is None:
        matches = read_procs(shell_name=identifier)
        proc = matches[0] if matches else None
    if proc is None or proc.status not in TERMINAL_PROC_STATUSES:
        return {"target": target, "resolved": False}
    outcome = "launched" if proc.status == "success" else "launch_error"
    return {
        "target": target,
        "resolved": True,
        "outcome": outcome,
        "identity": proc.proc_id,
        "message": proc.status,
    }


def _resolve_bead_wait(
    bead_id: str,
    selected_project: str | None,
    target: dict[str, Any],
) -> dict[str, Any]:
    if not selected_project:
        return {"target": target, "resolved": False}
    from sase.bead.store_locator import bead_statuses_for_project

    statuses = bead_statuses_for_project(selected_project, [bead_id])
    status = None if statuses is None else statuses.get(bead_id)
    if status is None or status != "closed":
        return {"target": target, "resolved": False}
    return {
        "target": target,
        "resolved": True,
        "outcome": "launched",
        "identity": bead_id,
        "message": status,
    }
