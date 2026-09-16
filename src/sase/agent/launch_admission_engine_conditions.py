"""Condition-checking support for the launch-admission engine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.launch_admission_engine_helpers import unit_by_logical_id
from sase.agent.launch_admission_runtime import (
    ConditionEvaluator,
    evaluate_launch_condition,
)
from sase.agent.launch_admission_store import UNITS_DIRNAME
from sase.agent.launch_condition_workspace import (
    ConditionWorkspaceError,
    ConditionWorkspaceUnavailable,
    acquire_condition_workspace,
    settle_condition_workspace,
)
from sase.core.agent_launch_wire import LaunchPlanWire, LaunchUnitWire


class AdmissionConditionMixin:
    plan: LaunchPlanWire
    admission_dir: Path
    request_id: str
    project_file: str | None
    source_cwd: str | None
    safe_inputs: dict[str, Any]
    condition_evaluator: ConditionEvaluator | None
    cancelled: Callable[[], bool]

    def _states(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

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
        raise NotImplementedError

    def _apply_check(self, action: Mapping[str, Any]) -> str:
        logical_id = str(action.get("logical_id") or "")
        waited = list(action.get("waited_outcomes") or [])
        unit = unit_by_logical_id(self.plan, logical_id)
        context = self._condition_context(unit.logical_id, waited)
        work_dir = Path(str(context["work_dir"]))
        lease_acquired = False
        if self._uses_condition_workspace(unit):
            try:
                lease = acquire_condition_workspace(
                    project=str(self.plan.selected_project),
                    request_id=self.request_id,
                    plan_digest=self.plan.content_digest,
                    logical_id=unit.logical_id,
                    work_dir=work_dir,
                    project_file=self.project_file,
                )
            except ConditionWorkspaceUnavailable:
                return "blocked"
            except ConditionWorkspaceError as exc:
                self._journal(
                    logical_id,
                    "condition_error",
                    waited_outcomes=waited,
                    message=str(exc),
                )
                return "replan"
            lease_acquired = True
            context.update(lease.context_payload())
        self._journal(logical_id, "checking", waited_outcomes=waited)
        try:
            verdict, message = self._evaluate_condition(unit, waited, context)
        except Exception as exc:
            verdict, message = "condition_error", f"condition evaluator failed: {exc}"
        finally:
            if lease_acquired:
                settle_condition_workspace(work_dir)
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
        return "replan"

    def _evaluate_condition(
        self,
        unit: LaunchUnitWire,
        waited: list[dict[str, Any]],
        context: Mapping[str, Any] | None = None,
    ) -> tuple[str, str | None]:
        evaluator = self.condition_evaluator or evaluate_launch_condition
        return evaluator(
            unit,
            waited,
            context or self._condition_context(unit.logical_id, waited),
        )

    def _recover_condition(self, logical_id: str) -> tuple[str, str | None] | None:
        from sase.agent.launch_condition_runtime import recover_launch_condition

        work_dir = self.admission_dir / UNITS_DIRNAME / logical_id
        try:
            return recover_launch_condition(
                work_dir,
                cancelled=self.cancelled,
            )
        finally:
            settle_condition_workspace(work_dir)

    def _condition_context(
        self,
        logical_id: str,
        waited: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "logical_unit": logical_id,
            "request_id": self.request_id,
            "plan_digest": self.plan.content_digest,
            "project_file": self.project_file,
            "selected_project": self.plan.selected_project,
            "waited_outcomes": waited,
            "safe_inputs": dict(self.safe_inputs),
            "source_cwd": self.source_cwd,
            "admission_dir": str(self.admission_dir),
            "work_dir": str(self.admission_dir / UNITS_DIRNAME / logical_id),
            "cancelled": self.cancelled,
            "supervise": self.condition_evaluator is None,
        }

    def _uses_condition_workspace(self, unit: LaunchUnitWire) -> bool:
        if self.condition_evaluator is not None:
            return False
        if unit.condition is None:
            return False
        project = self.plan.selected_project
        return isinstance(project, str) and bool(project.strip())


__all__ = ["AdmissionConditionMixin"]
