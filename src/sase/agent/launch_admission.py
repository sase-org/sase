"""Durable launch-admission coordinator over the Rust journal planner.

The coordinator is infrastructure owned by a launch-request bundle: it is not
a proc shell, agent, or Agents-tab row. Waiting never claims runners,
workspaces, proc records, or provider capacity. Eligible AgentUnits still
dispatch through the established agent launch path.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sase.agent.launch_request_types import (
    ApprovedLaunchDispatchResult,
    LaunchRequestError,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import (
    admission_unit_results,
    agent_unit_dispatch_prompt,
    next_admission_actions,
    reconcile_admission_journal,
    summarize_admission,
)
from sase.core.agent_launch_wire import (
    LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
    AgentUnitWire,
    LaunchAdmissionSummaryWire,
    LaunchPlanWire,
    LaunchUnitResultWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.monitor.transaction import write_json_marker_atomic

ADMISSION_DIRNAME = "launch_admission"
JOURNAL_FILENAME = "journal.jsonl"
SIDECAR_FILENAME = "sidecar.json"
STARTED_FILENAME = "started.json"
RECEIPT_FILENAME = "receipt.json"
LOCK_FILENAME = "lock"
UNITS_DIRNAME = "units"
COORDINATOR_LOG_FILENAME = "coordinator.log"
START_ACK_TIMEOUT_SECONDS = 20.0
STOP_TERM_SECONDS = 5.0
STOP_KILL_SECONDS = 1.0
POLL_SECONDS = 0.05
COORDINATOR_ENV = "SASE_LAUNCH_ADMISSION_COORDINATOR"


class _ConditionEvaluator(Protocol):
    def __call__(
        self,
        unit: LaunchUnitWire,
        waited_outcomes: list[dict[str, Any]],
        context: Mapping[str, Any],
    ) -> tuple[str, str | None]:
        """Return ``eligible`` / ``skipped`` / ``condition_error`` plus message."""


class _UnitDispatcher(Protocol):
    def __call__(
        self,
        unit: LaunchUnitWire,
        fingerprint: str,
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        """Return ok, identity, message, and any spawned agent results."""


class _WaitResolver(Protocol):
    def __call__(
        self,
        plan: LaunchPlanWire,
        states: dict[str, dict[str, Any]],
        *,
        now: float,
        waiting_since: Mapping[str, float],
    ) -> list[dict[str, Any]]:
        """Return wait facts for non-logical targets."""


@dataclass
class _AdmissionEngine:
    """In-process admission driver with injectable wait/dispatch hooks."""

    plan: LaunchPlanWire
    admission_dir: Path
    request_id: str
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    cancelled: Callable[[], bool] = lambda: False
    wait_resolver: _WaitResolver | None = None
    condition_evaluator: _ConditionEvaluator | None = None
    agent_dispatcher: _UnitDispatcher | None = None
    proc_dispatcher: _UnitDispatcher | None = None
    poll_seconds: float = POLL_SECONDS
    source_cwd: str | None = None
    safe_inputs: dict[str, Any] = field(default_factory=dict)
    results: list[AgentLaunchResult] = field(default_factory=list)
    _waiting_since: dict[str, float] = field(default_factory=dict)
    _next_seq: int = 1

    def run(self, *, until_blocked: bool = False) -> _AdmissionProgress:
        """Drive the journal until complete, cancelled, or blocked on waits."""

        self.admission_dir.mkdir(parents=True, exist_ok=True)
        self._next_seq = _next_journal_seq(self.admission_dir)
        while True:
            if self.cancelled():
                self._cancel_open_units()
                return self._progress(complete=True)
            states = self._states()
            actions = next_admission_actions(
                self.plan, states, self._wait_facts(states)
            )
            if not actions:
                progress = self._progress(complete=_all_terminal(self.plan, states))
                if progress.complete or until_blocked:
                    return progress
                self.sleep(self.poll_seconds)
                continue
            for action in actions:
                if self.cancelled():
                    self._cancel_open_units()
                    return self._progress(complete=True)
                self._apply_action(action)

    def _states(self) -> dict[str, dict[str, Any]]:
        states = reconcile_admission_journal(_read_journal(self.admission_dir))
        units_dir = self.admission_dir / UNITS_DIRNAME
        if not units_dir.is_dir():
            return states
        for path in units_dir.glob("*.json"):
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(receipt, dict):
                continue
            logical_id = str(receipt.get("logical_id") or "")
            identity = receipt.get("identity")
            state = states.get(logical_id)
            if (
                state is None
                or not logical_id
                or not isinstance(identity, str)
                or not identity
            ):
                continue
            state["identity"] = identity
        return states

    def _wait_facts(self, states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        resolver = self.wait_resolver or _resolve_external_wait_facts
        return resolver(
            self.plan,
            states,
            now=self.clock(),
            waiting_since=self._waiting_since,
        )

    def _apply_action(self, action: Mapping[str, Any]) -> None:
        kind = str(action.get("kind") or "")
        logical_id = str(action.get("logical_id") or "")
        if kind == "reserve":
            self._journal(logical_id, "reserved")
            return
        if kind == "wait":
            self._waiting_since.setdefault(logical_id, self.clock())
            self._journal(logical_id, "waiting")
            return
        if kind == "check":
            waited = list(action.get("waited_outcomes") or [])
            self._journal(logical_id, "checking", waited_outcomes=waited)
            unit = _unit(self.plan, logical_id)
            verdict, message = self._evaluate_condition(unit, waited)
            phase = {
                "eligible": "eligible",
                "skipped": "skipped",
                "condition_error": "condition_error",
            }.get(verdict, "condition_error")
            self._journal(
                logical_id,
                phase,
                waited_outcomes=waited,
                message=message or verdict,
            )
            return
        if kind == "eligible":
            self._journal(
                logical_id,
                "eligible",
                waited_outcomes=list(action.get("waited_outcomes") or []),
            )
            return
        if kind == "dispatch":
            fingerprint = str(action.get("fingerprint") or "")
            self._journal(logical_id, "dispatching", fingerprint=fingerprint)
            unit = _unit(self.plan, logical_id)
            dispatcher = (
                self.proc_dispatcher
                if str(action.get("unit_kind") or "") == "proc"
                else self.agent_dispatcher
            )
            if dispatcher is None:
                dispatcher = (
                    _dispatch_proc_unit
                    if str(action.get("unit_kind") or "") == "proc"
                    else _dispatch_agent_unit
                )
            ok, identity, message, spawned = dispatcher(unit, fingerprint)
            self.results.extend(spawned)
            if ok:
                _write_unit_receipt(
                    self.admission_dir,
                    logical_id=logical_id,
                    fingerprint=fingerprint,
                    identity=identity or logical_id,
                )
                self._journal(
                    logical_id,
                    "launched",
                    fingerprint=fingerprint,
                    identity=identity or logical_id,
                    message=message,
                )
                return
            self._journal(
                logical_id,
                "launch_error",
                fingerprint=fingerprint,
                message=message or "launch_error",
            )
            return
        if kind == "fail_check":
            recovered = self._recover_condition(logical_id)
            if recovered is not None:
                verdict, message = recovered
                phase = {
                    "eligible": "eligible",
                    "skipped": "skipped",
                    "condition_error": "condition_error",
                }.get(verdict, "condition_error")
                self._journal(logical_id, phase, message=message or verdict)
                return
            self._journal(
                logical_id,
                "condition_error",
                message=str(action.get("message") or "check_interrupted"),
            )
            return
        if kind == "fail_dispatch":
            self._journal(
                logical_id,
                "launch_error",
                message=str(action.get("message") or "dispatch_interrupted"),
            )
            return
        if kind == "record_launched":
            identity = str(action.get("identity") or logical_id)
            self._journal(logical_id, "launched", identity=identity)

    def _evaluate_condition(
        self,
        unit: LaunchUnitWire,
        waited: list[dict[str, Any]],
    ) -> tuple[str, str | None]:
        evaluator = self.condition_evaluator or _evaluate_launch_condition
        return evaluator(unit, waited, self._condition_context(unit.logical_id, waited))

    def _recover_condition(self, logical_id: str) -> tuple[str, str | None] | None:
        from sase.agent.launch_condition_runtime import recover_launch_condition

        return recover_launch_condition(
            self.admission_dir / UNITS_DIRNAME / logical_id,
            cancelled=self.cancelled,
        )

    def _condition_context(
        self,
        logical_id: str,
        waited: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "logical_unit": logical_id,
            "selected_project": self.plan.selected_project,
            "waited_outcomes": waited,
            "safe_inputs": dict(self.safe_inputs),
            "source_cwd": self.source_cwd,
            "admission_dir": str(self.admission_dir),
            "work_dir": str(self.admission_dir / UNITS_DIRNAME / logical_id),
            "cancelled": self.cancelled,
            "supervise": self.condition_evaluator is None,
        }

    def _cancel_open_units(self) -> None:
        states = self._states()
        for unit in self.plan.units:
            state = states.get(unit.logical_id) or {}
            phase = str(state.get("phase") or "")
            if phase in {
                "launched",
                "skipped",
                "condition_error",
                "launch_error",
                "cancelled",
            }:
                continue
            if phase == "checking":
                cancel_path = (
                    self.admission_dir / UNITS_DIRNAME / unit.logical_id / "cancel"
                )
                cancel_path.parent.mkdir(parents=True, exist_ok=True)
                cancel_path.write_text("1\n", encoding="utf-8")
            identity = state.get("identity")
            fingerprint = state.get("fingerprint")
            self._journal(
                unit.logical_id,
                "cancelled",
                identity=identity if isinstance(identity, str) else None,
                fingerprint=(fingerprint if isinstance(fingerprint, str) else None),
                message="cancelled",
            )

    def _journal(
        self,
        logical_id: str,
        phase: str,
        *,
        fingerprint: str | None = None,
        identity: str | None = None,
        waited_outcomes: list[dict[str, Any]] | None = None,
        message: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "schema_version": LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
            "seq": self._next_seq,
            "logical_id": logical_id,
            "phase": phase,
            "recorded_at_unix": self.clock(),
        }
        self._next_seq += 1
        if fingerprint:
            entry["fingerprint"] = fingerprint
        if identity:
            entry["identity"] = identity
        if waited_outcomes is not None:
            entry["waited_outcomes"] = waited_outcomes
        if message:
            entry["message"] = message
        _append_journal(self.admission_dir, entry)

    def _progress(self, *, complete: bool) -> _AdmissionProgress:
        states = self._states()
        summary = summarize_admission(self.plan, states)
        receipt = {
            "schema_version": LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
            "request_id": self.request_id,
            "plan_digest": self.plan.content_digest,
            "plan_schema_version": self.plan.schema_version,
            "complete": complete,
            "summary": agent_launch_wire_to_json_dict(summary),
            "units": [
                agent_launch_wire_to_json_dict(result)
                for result in admission_unit_results(self.plan, states)
            ],
        }
        write_json_marker_atomic(self.admission_dir / RECEIPT_FILENAME, receipt)
        return _AdmissionProgress(
            complete=complete,
            summary=summary,
            unit_results=tuple(admission_unit_results(self.plan, states)),
            results=list(self.results),
            receipt=receipt,
        )


@dataclass(frozen=True)
class _AdmissionProgress:
    complete: bool
    summary: LaunchAdmissionSummaryWire
    unit_results: tuple[LaunchUnitResultWire, ...]
    results: list[AgentLaunchResult]
    receipt: dict[str, Any]


def admission_dir(response_dir: Path) -> Path:
    return response_dir / ADMISSION_DIRNAME


def dispatch_typed_launch_request(
    response_dir: Path,
    data: Mapping[str, Any],
    *,
    until_blocked: bool = True,
    wait_resolver: _WaitResolver | None = None,
    condition_evaluator: _ConditionEvaluator | None = None,
    agent_dispatcher: _UnitDispatcher | None = None,
    proc_dispatcher: _UnitDispatcher | None = None,
    spawn_coordinator: bool = True,
    cancelled: Callable[[], bool] | None = None,
) -> ApprovedLaunchDispatchResult:
    """Admit an approved typed plan, detaching only when waits remain."""

    plan = _typed_plan_from_request(data)
    request_id = str(data.get("request_id") or "")
    root = admission_dir(response_dir)
    lock_path = root / LOCK_FILENAME
    root.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            _write_sidecar(root, data, plan)
            engine = _AdmissionEngine(
                plan=plan,
                admission_dir=root,
                request_id=request_id,
                wait_resolver=wait_resolver,
                condition_evaluator=condition_evaluator,
                agent_dispatcher=agent_dispatcher,
                proc_dispatcher=proc_dispatcher,
                cancelled=cancelled or (lambda: False),
                source_cwd=_request_source_cwd(data),
                safe_inputs=_request_safe_inputs(data),
            )
            progress = engine.run(until_blocked=until_blocked)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    if spawn_coordinator and not progress.complete:
        from sase.agent.launch_admission_coordinator import (
            start_detached_coordinator,
        )

        start_detached_coordinator(response_dir)
    elif progress.complete:
        _notify_admission_complete(request_id, progress, root / RECEIPT_FILENAME)
    return _dispatch_result(request_id, progress)


def run_coordinator_in_bundle(
    response_dir: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> _AdmissionProgress:
    """Reconcile and finish an approved bundle as the detached coordinator."""

    from sase.agent.launch_request_response import read_launch_request

    data = read_launch_request(response_dir)
    plan = _typed_plan_from_request(data)
    root = admission_dir(response_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / LOCK_FILENAME
    stop = cancelled or (lambda: False)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            write_json_marker_atomic(
                root / STARTED_FILENAME,
                {
                    "pid": os.getpid(),
                    "request_id": str(data.get("request_id") or ""),
                    "plan_digest": plan.content_digest,
                    "started_at_unix": time.time(),
                },
            )
            engine = _AdmissionEngine(
                plan=plan,
                admission_dir=root,
                request_id=str(data.get("request_id") or ""),
                cancelled=stop,
                source_cwd=_request_source_cwd(data),
                safe_inputs=_request_safe_inputs(data),
            )
            progress = engine.run(until_blocked=False)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    _notify_admission_complete(
        str(data.get("request_id") or ""),
        progress,
        root / RECEIPT_FILENAME,
    )
    return progress


def stop_launch_admission(response_dir: Path) -> None:
    """Escalate SIGTERM then SIGKILL against a live admission coordinator."""

    sidecar = _read_json(admission_dir(response_dir) / SIDECAR_FILENAME)
    pid = sidecar.get("pid") if isinstance(sidecar, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return
    _escalate_pid(pid)


def _resolve_external_wait_facts(
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


def _evaluate_launch_condition(
    unit: LaunchUnitWire,
    waited_outcomes: list[dict[str, Any]],
    context: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Sandbox ``unit.condition`` and return a durable admission verdict."""

    from sase.agent.launch_condition_runtime import evaluate_launch_condition

    return evaluate_launch_condition(unit, waited_outcomes, context)


def _request_source_cwd(data: Mapping[str, Any]) -> str | None:
    dispatch = data.get("dispatch")
    if not isinstance(dispatch, Mapping):
        return None
    cwd = dispatch.get("cwd")
    return None if cwd is None else str(cwd)


def _request_safe_inputs(data: Mapping[str, Any]) -> dict[str, Any]:
    raw = data.get("safe_inputs")
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items()}
    request = data.get("launch_request")
    if isinstance(request, Mapping) and isinstance(request.get("inputs"), Mapping):
        return {str(key): value for key, value in request["inputs"].items()}
    return {}


def _dispatch_agent_unit(
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


def _dispatch_proc_unit(
    unit: LaunchUnitWire,
    fingerprint: str,
) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
    """Default proc hook; Phase 5 replaces this with native proc dispatch."""

    del fingerprint
    if not isinstance(unit.payload, ProcUnitWire):
        return False, None, "not_a_proc_unit", []
    try:
        from sase.agent.launch_proc_runtime import (  # type: ignore[import-not-found]
            dispatch_proc_unit as hooked,
        )
    except ImportError:
        return False, None, "proc_dispatcher_unavailable", []
    return hooked(unit, fingerprint)


def _format_admission_summary(summary: LaunchAdmissionSummaryWire) -> str:
    return (
        f"{summary.total} total, {summary.eligible} eligible, "
        f"{summary.launched} launched, {summary.skipped} skipped, "
        f"{summary.condition_errors} condition error(s), "
        f"{summary.launch_errors} launch error(s)"
    )


def _typed_plan_from_request(data: Mapping[str, Any]) -> LaunchPlanWire:
    raw = data.get("typed_plan")
    if not isinstance(raw, dict):
        raise LaunchRequestError(
            "invalid_request",
            "typed_plan",
            "typed launch plan is missing",
        )
    return launch_plan_from_dict(raw)


def _unit(plan: LaunchPlanWire, logical_id: str) -> LaunchUnitWire:
    for unit in plan.units:
        if unit.logical_id == logical_id:
            return unit
    raise LaunchRequestError(
        "invalid_request",
        logical_id,
        f"typed launch plan has no unit {logical_id}",
    )


def _all_terminal(
    plan: LaunchPlanWire, states: Mapping[str, Mapping[str, Any]]
) -> bool:
    terminal = {
        "launched",
        "skipped",
        "condition_error",
        "launch_error",
        "cancelled",
    }
    return all(
        str((states.get(unit.logical_id) or {}).get("phase") or "") in terminal
        for unit in plan.units
    )


def _dispatch_result(
    request_id: str,
    progress: _AdmissionProgress,
) -> ApprovedLaunchDispatchResult:
    return ApprovedLaunchDispatchResult(
        request_id=request_id,
        results=list(progress.results),
        summary=progress.summary,
        unit_results=progress.unit_results,
        plan_digest=str(progress.receipt.get("plan_digest") or ""),
        admission_complete=progress.complete,
    )


def _write_sidecar(root: Path, data: Mapping[str, Any], plan: LaunchPlanWire) -> None:
    write_json_marker_atomic(
        root / SIDECAR_FILENAME,
        {
            "schema_version": LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
            "request_id": str(data.get("request_id") or ""),
            "plan_digest": plan.content_digest,
            "plan_schema_version": plan.schema_version,
            "pid": os.getpid(),
            "updated_at_unix": time.time(),
        },
    )


def _append_journal(root: Path, entry: dict[str, Any]) -> None:
    path = root / JOURNAL_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entry, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_journal(root: Path) -> list[dict[str, Any]]:
    path = root / JOURNAL_FILENAME
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def _next_journal_seq(root: Path) -> int:
    seq = 1
    for entry in _read_journal(root):
        try:
            seq = max(seq, int(entry.get("seq") or 0) + 1)
        except (TypeError, ValueError):
            continue
    return seq


def _write_unit_receipt(
    root: Path,
    *,
    logical_id: str,
    fingerprint: str,
    identity: str,
) -> None:
    units_dir = root / UNITS_DIRNAME
    write_json_marker_atomic(
        units_dir / f"{logical_id}.json",
        {
            "logical_id": logical_id,
            "fingerprint": fingerprint,
            "identity": identity,
        },
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _notify_admission_complete(
    request_id: str,
    progress: _AdmissionProgress,
    receipt_path: Path,
) -> None:
    try:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="launch.admission",
            cl_name=None,
            success=(
                progress.summary.condition_errors == 0
                and progress.summary.launch_errors == 0
            ),
            notes=[
                f"Launch admission finished for `{request_id}`",
                _format_admission_summary(progress.summary),
            ],
            extra_files=[str(receipt_path)],
            tags=["launch"],
        )
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


def install_coordinator_signal_flag() -> Callable[[], bool]:
    cancelled = threading.Event()

    def _handle(signum: int, frame: object) -> None:
        del signum, frame
        cancelled.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
    return cancelled.is_set


def _escalate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + STOP_TERM_SECONDS
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(POLL_SECONDS)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return
    kill_deadline = time.monotonic() + STOP_KILL_SECONDS
    while time.monotonic() < kill_deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(POLL_SECONDS)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except (OSError, IndexError):
        return True
    return state != "Z"


__all__ = [
    "ADMISSION_DIRNAME",
    "COORDINATOR_ENV",
    "STARTED_FILENAME",
    "START_ACK_TIMEOUT_SECONDS",
    "admission_dir",
    "dispatch_typed_launch_request",
    "install_coordinator_signal_flag",
    "run_coordinator_in_bundle",
    "stop_launch_admission",
]
