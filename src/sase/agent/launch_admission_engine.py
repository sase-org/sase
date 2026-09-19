"""In-process launch-admission driver over the Rust journal planner."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.launch_admission_runtime import (
    ConditionEvaluator,
    UnitDispatcher,
    WaitResolver,
    call_proc_dispatcher,
    dispatch_agent_unit,
    dispatch_proc_unit,
    resolve_external_wait_facts,
    stop_proc_identity,
)
from sase.agent.launch_admission_engine_conditions import AdmissionConditionMixin
from sase.agent.launch_admission_engine_helpers import (
    all_terminal,
    unit_by_logical_id,
    unpack_agent_dispatch,
)
from sase.agent.launch_admission_engine_holds import (
    proc_hold_blocks,
    proc_unit_blocked_by_hold,
)
from sase.agent.launch_hold import (
    reanchor_dispatched_agent_hold,
    release_unit_hold_if_terminal,
)
from sase.agent.launch_admission_request_data import (
    request_project_file,
    request_safe_inputs,
    request_source_cwd,
    typed_plan_from_request,
)
from sase.agent.proc_capacity_admission import (
    ProcCapacityAdmission,
    evaluate_proc_capacity_admission,
    iso_from_unix,
    proc_requires_capacity_admission,
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
)
from sase.core.atomic_json import write_json_marker_atomic
from sase.core.runner_slots import runner_slot_admission_lock


@dataclass(frozen=True)
class AdmissionProgress:
    complete: bool
    summary: LaunchAdmissionSummaryWire
    unit_results: tuple[LaunchUnitResultWire, ...]
    results: list[AgentLaunchResult]
    receipt: dict[str, Any]


@dataclass
class AdmissionEngine(AdmissionConditionMixin):
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
    project_file: str | None = None
    source_cwd: str | None = None
    safe_inputs: dict[str, Any] = field(default_factory=dict)
    results: list[AgentLaunchResult] = field(default_factory=list)
    _waiting_since: dict[str, float] = field(default_factory=dict)
    _proc_capacity_requested_at: dict[str, str] = field(default_factory=dict)
    _proc_capacity_eligible_since: dict[str, str] = field(default_factory=dict)
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
                self.plan,
                states,
                self._wait_facts(states),
                self._hold_blocks(states),
            )
            if not actions:
                progress = self._progress(complete=all_terminal(self.plan, states))
                if progress.complete or until_blocked:
                    return progress
                self.sleep(self.poll_seconds)
                continue
            for action in actions:
                if self.cancelled():
                    self._cancel_open_units()
                    return self._progress(complete=True)
                outcome = self._apply_action(action)
                if outcome == "blocked":
                    if until_blocked:
                        return self._progress(complete=False)
                    self.sleep(self.poll_seconds)
                    break
                if outcome == "replan":
                    break

    def _states(self) -> dict[str, dict[str, Any]]:
        states = reconcile_admission_journal(read_journal(self.admission_dir))
        units_dir = self.admission_dir / UNITS_DIRNAME
        if not units_dir.is_dir():
            return states
        for path in units_dir.glob("*.json"):
            if path.name.endswith(".hold.json"):
                continue
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
            for key in (
                "dispatch_target",
                "workspace_reference",
                "operation_key",
                "locator",
                "receipt_state",
                "uncertain",
            ):
                value = receipt.get(key)
                if value is not None:
                    state[key] = value
        return states

    def _wait_facts(self, states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        resolver = self.wait_resolver or resolve_external_wait_facts
        return resolver(
            self.plan,
            states,
            now=self.clock(),
            waiting_since=self._waiting_since,
        )

    def _hold_blocks(self, states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return proc_hold_blocks(
            self.plan,
            states,
            request_id=self.request_id,
            now_seconds=self.clock(),
        )

    def _apply_action(self, action: Mapping[str, Any]) -> str | None:
        kind = str(action.get("kind") or "")
        logical_id = str(action.get("logical_id") or "")
        if kind == "reserve":
            self._journal(logical_id, "reserved")
            return None
        if kind == "wait":
            self._waiting_since.setdefault(logical_id, self.clock())
            self._journal(logical_id, "waiting")
            return None
        if kind == "check":
            return self._apply_check(action)
        if kind == "eligible":
            self._journal(
                logical_id,
                "eligible",
                waited_outcomes=list(action.get("waited_outcomes") or []),
            )
            return None
        if kind == "dispatch":
            fingerprint = str(action.get("fingerprint") or "")
            unit = unit_by_logical_id(self.plan, logical_id)
            if str(action.get("unit_kind") or "") == "proc":
                commit = self._commit_proc_pre_run(unit, fingerprint)
                if commit == "blocked":
                    return "blocked"
                if commit == "failed":
                    return None
                proc_dispatcher = self.proc_dispatcher or dispatch_proc_unit
                ok, identity, message, spawned = call_proc_dispatcher(
                    proc_dispatcher,
                    unit,
                    fingerprint,
                    self._proc_context(unit, action),
                )
                extra: dict[str, Any] = {}
            elif self.agent_dispatcher is None:
                self._journal(logical_id, "dispatching", fingerprint=fingerprint)
                ok, identity, message, spawned, extra = unpack_agent_dispatch(
                    dispatch_agent_unit(
                        unit,
                        fingerprint,
                        selected_project=self.plan.selected_project,
                        source_cwd=self.source_cwd,
                        request_id=self.request_id,
                    )
                )
            else:
                self._journal(logical_id, "dispatching", fingerprint=fingerprint)
                ok, identity, message, spawned, extra = unpack_agent_dispatch(
                    self.agent_dispatcher(unit, fingerprint)
                )
            self.results.extend(spawned)
            if ok:
                reanchor_dispatched_agent_hold(
                    self.admission_dir,
                    unit,
                    self.request_id,
                    list(spawned),
                )
                write_unit_receipt(
                    self.admission_dir,
                    logical_id=logical_id,
                    fingerprint=fingerprint,
                    identity=identity or logical_id,
                    unit=unit,
                    extra=extra,
                )
                self._journal(
                    logical_id,
                    "launched",
                    fingerprint=fingerprint,
                    identity=identity or logical_id,
                    message=message,
                    extra=extra,
                )
                return None
            self._journal(
                logical_id,
                "launch_error",
                fingerprint=fingerprint,
                message=message or "launch_error",
                extra=extra,
            )
            return None
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
                return "replan"
            self._journal(
                logical_id,
                "condition_error",
                message=str(action.get("message") or "check_interrupted"),
            )
            return "replan"
        if kind == "fail_dispatch":
            self._journal(
                logical_id,
                "launch_error",
                message=str(action.get("message") or "dispatch_interrupted"),
            )
            return None
        if kind == "record_launched":
            identity = str(action.get("identity") or logical_id)
            self._journal(logical_id, "launched", identity=identity)
        return None

    def _commit_proc_pre_run(self, unit: LaunchUnitWire, fingerprint: str) -> str:
        """Recheck holds and commit the proc's pre-run dispatch transition.

        Returns ``committed`` after journaling ``dispatching`` under
        ``runner_slots.lock``, ``blocked`` when a hold or capacity gate
        still applies, or ``failed`` after journaling a launch error.
        Process spawn stays outside the lock. Once ``dispatching`` is
        journaled the proc is immune to later arms.
        """
        logical_id = unit.logical_id
        invalid_capacity: ProcCapacityAdmission | None = None
        blocked_capacity: ProcCapacityAdmission | None = None
        with runner_slot_admission_lock():
            if proc_unit_blocked_by_hold(
                self.plan,
                unit,
                self._states().get(logical_id) or {},
                request_id=self.request_id,
                now_seconds=self.clock(),
                notify=False,
            ):
                return "blocked"
            capacity = self._proc_capacity_admission(unit, acquire_lock=False)
            if capacity is not None and capacity.invalid:
                invalid_capacity = capacity
            elif capacity is not None and not capacity.admitted:
                blocked_capacity = capacity
            else:
                self._journal(logical_id, "dispatching", fingerprint=fingerprint)
                return "committed"
        if invalid_capacity is not None:
            self._journal(
                logical_id,
                "launch_error",
                fingerprint=fingerprint,
                message=invalid_capacity.message or "proc capacity admission failed",
            )
            return "failed"
        prior_state = self._states().get(logical_id) or {}
        prior_waited = prior_state.get("waited_outcomes") or []
        self._journal(
            logical_id,
            "eligible",
            waited_outcomes=list(prior_waited),
            message=(
                blocked_capacity.message
                if blocked_capacity is not None and blocked_capacity.message
                else "proc blocked by runner capacity"
            ),
        )
        return "blocked"

    def _proc_capacity_admission(
        self, unit: LaunchUnitWire, *, acquire_lock: bool = True
    ) -> ProcCapacityAdmission | None:
        if not proc_requires_capacity_admission(unit):
            return None
        now_seconds = self.clock()
        requested_at = self._proc_capacity_requested_at.setdefault(
            unit.logical_id, iso_from_unix(now_seconds)
        )
        now_dt = datetime.fromtimestamp(now_seconds, UTC)
        now = now_dt.isoformat()
        decision = evaluate_proc_capacity_admission(
            unit,
            admission_dir=self.admission_dir,
            request_id=self.request_id,
            selected_project=self.plan.selected_project,
            requested_at=requested_at,
            eligible_since=self._proc_capacity_eligible_since.get(unit.logical_id),
            now=now_dt,
            acquire_lock=acquire_lock,
        )
        if any(
            blocker.get("code") == "deference-window" for blocker in decision.blockers
        ):
            self._proc_capacity_eligible_since.setdefault(unit.logical_id, now)
        elif unit.logical_id in self._proc_capacity_eligible_since:
            self._proc_capacity_eligible_since.pop(unit.logical_id, None)
        return decision

    def _proc_context(
        self, unit: LaunchUnitWire, action: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "logical_unit": unit.logical_id,
            "request_id": self.request_id,
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
                if phase == "checking":
                    self._recover_condition(unit.logical_id)
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
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        if phase in {"skipped", "condition_error", "launch_error", "cancelled"}:
            unit = unit_by_logical_id(self.plan, logical_id)
            release_unit_hold_if_terminal(unit, self.request_id)
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
        if extra:
            for key in (
                "dispatch_target",
                "workspace_reference",
                "operation_key",
                "locator",
                "receipt_state",
                "uncertain",
            ):
                value = extra.get(key)
                if value is not None:
                    entry[key] = value
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


__all__ = [
    "AdmissionEngine",
    "AdmissionProgress",
    "request_project_file",
    "request_safe_inputs",
    "request_source_cwd",
    "typed_plan_from_request",
]
