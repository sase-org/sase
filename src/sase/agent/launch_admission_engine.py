"""In-process launch-admission driver over the Rust journal planner."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.agent.launch_admission_runtime import (
    ConditionEvaluator,
    UnitDispatcher,
    WaitResolver,
    call_proc_dispatcher,
    dispatch_agent_unit,
    dispatch_proc_unit,
    evaluate_launch_condition,
    resolve_external_wait_facts,
    stop_proc_identity,
)
from sase.agent.launch_admission_store import (
    POLL_SECONDS,
    RECEIPT_FILENAME,
    UNITS_DIRNAME,
    append_journal,
    next_journal_seq,
    read_journal,
    write_unit_receipt,
)
from sase.agent.launch_request_types import LaunchRequestError
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import (
    admission_unit_results,
    next_admission_actions,
    reconcile_admission_journal,
    summarize_admission,
)
from sase.core.agent_launch_wire import (
    LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
    LaunchAdmissionSummaryWire,
    LaunchPlanWire,
    LaunchUnitResultWire,
    LaunchUnitWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.monitor.transaction import write_json_marker_atomic


@dataclass(frozen=True)
class AdmissionProgress:
    complete: bool
    summary: LaunchAdmissionSummaryWire
    unit_results: tuple[LaunchUnitResultWire, ...]
    results: list[AgentLaunchResult]
    receipt: dict[str, Any]


@dataclass
class AdmissionEngine:
    """In-process admission driver with injectable wait/dispatch hooks."""

    plan: LaunchPlanWire
    admission_dir: Path
    request_id: str
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    cancelled: Callable[[], bool] = lambda: False
    wait_resolver: WaitResolver | None = None
    condition_evaluator: ConditionEvaluator | None = None
    agent_dispatcher: UnitDispatcher | None = None
    proc_dispatcher: UnitDispatcher | None = None
    poll_seconds: float = POLL_SECONDS
    source_cwd: str | None = None
    safe_inputs: dict[str, Any] = field(default_factory=dict)
    results: list[AgentLaunchResult] = field(default_factory=list)
    _waiting_since: dict[str, float] = field(default_factory=dict)
    _next_seq: int = 1

    def run(self, *, until_blocked: bool = False) -> AdmissionProgress:
        """Drive the journal until complete, cancelled, or blocked on waits."""

        self.admission_dir.mkdir(parents=True, exist_ok=True)
        self._next_seq = next_journal_seq(self.admission_dir)
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
        states = reconcile_admission_journal(read_journal(self.admission_dir))
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
        resolver = self.wait_resolver or resolve_external_wait_facts
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
                    dispatch_proc_unit
                    if str(action.get("unit_kind") or "") == "proc"
                    else dispatch_agent_unit
                )
            if dispatcher is self.proc_dispatcher or (dispatcher is dispatch_proc_unit):
                ok, identity, message, spawned = call_proc_dispatcher(
                    dispatcher, unit, fingerprint, self._proc_context(unit, action)
                )
            else:
                ok, identity, message, spawned = dispatcher(unit, fingerprint)
            self.results.extend(spawned)
            if ok:
                write_unit_receipt(
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
        evaluator = self.condition_evaluator or evaluate_launch_condition
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

    def _proc_context(
        self, unit: LaunchUnitWire, action: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "logical_unit": unit.logical_id,
            "selected_project": self.plan.selected_project,
            "source_cwd": self.source_cwd,
            "admission_dir": str(self.admission_dir),
            "work_dir": str(self.admission_dir / UNITS_DIRNAME / unit.logical_id),
            "cancelled": self.cancelled,
            "waited_outcomes": list(action.get("waited_outcomes") or []),
            "condition_result": (self._states().get(unit.logical_id) or {}).get(
                "message"
            ),
            "python_executable": sys.executable,
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
            if phase in {"checking", "dispatching", "reserved", "waiting", "eligible"}:
                cancel_path = (
                    self.admission_dir / UNITS_DIRNAME / unit.logical_id / "cancel"
                )
                cancel_path.parent.mkdir(parents=True, exist_ok=True)
                cancel_path.write_text("1\n", encoding="utf-8")
            identity = state.get("identity")
            if phase == "dispatching" and isinstance(identity, str) and identity:
                stop_proc_identity(identity)
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
        append_journal(self.admission_dir, entry)

    def _progress(self, *, complete: bool) -> AdmissionProgress:
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
        return AdmissionProgress(
            complete=complete,
            summary=summary,
            unit_results=tuple(admission_unit_results(self.plan, states)),
            results=list(self.results),
            receipt=receipt,
        )


def typed_plan_from_request(data: Mapping[str, Any]) -> LaunchPlanWire:
    raw = data.get("typed_plan")
    if not isinstance(raw, dict):
        raise LaunchRequestError(
            "invalid_request",
            "typed_plan",
            "typed launch plan is missing",
        )
    plan = launch_plan_from_dict(raw)
    digest = data.get("plan_digest")
    if digest not in (None, "") and str(digest) != plan.content_digest:
        raise LaunchRequestError(
            "plan_digest_mismatch",
            "plan_digest",
            "approved launch plan digest does not match typed_plan.content_digest",
        )
    return plan


def request_source_cwd(data: Mapping[str, Any]) -> str | None:
    dispatch = data.get("dispatch")
    if not isinstance(dispatch, Mapping):
        return None
    cwd = dispatch.get("cwd")
    return None if cwd is None else str(cwd)


def request_safe_inputs(data: Mapping[str, Any]) -> dict[str, Any]:
    raw = data.get("safe_inputs")
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items()}
    request = data.get("launch_request")
    if isinstance(request, Mapping) and isinstance(request.get("inputs"), Mapping):
        return {str(key): value for key, value in request["inputs"].items()}
    return {}


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
