"""Typed gate-kind adapter and its non-plan behavior."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.notification_gates.adapter_plan import (
    apply_plan_side_effects,
    prepare_plan_terminal_response,
    validate_plan_edited_resource,
)
from sase.notification_gates.models import (
    GateError,
    GateFeedbackMode,
    GateSpec,
)

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin


@dataclass(frozen=True)
class GateAdapter:
    """The stable typed transport and legacy-file shape for one gate kind.

    Option commands in an AND branch must be idempotent. The branch runs its
    commands one at a time, and when a later member fails the reviewer may
    choose to restart the whole branch, which re-runs the members that already
    succeeded. See :func:`sase.notification_gates.executor.execute_gate_selection`.
    """

    kind: str
    display_title: str
    action: str
    pending_action_kind: str
    sender: str
    request_filename: str
    response_filename: str
    legacy_directory_key: str
    auto_capabilities: frozenset[str] = field(default_factory=frozenset)
    neutral_only: bool = False
    default_feedback: GateFeedbackMode = "disabled"
    generic_form: bool = False
    branch_actionable: bool = True

    def normalize_option_inputs(
        self,
        envelope: Mapping[str, Any],
        selected_option_ids: Sequence[str],
        option_inputs: Mapping[str, object] | None,
        *,
        source: str,
        caller: str,
    ) -> Mapping[str, object] | None:
        """Normalize per-option inputs before acceptance and execution.

        The base implementation returns the inputs unchanged. The plan
        adapter resolves Plan Decisions here so the receipt and the
        execution paths consume one identical vector.
        """
        if self.kind not in {"plan", "epic_plan"}:
            return option_inputs
        try:
            from sase.plan_gate_decisions import normalize_plan_option_inputs
        except Exception:
            return option_inputs
        return normalize_plan_option_inputs(
            envelope,
            selected_option_ids,
            option_inputs,
            source=source,
            caller=caller,
        )

    def preflight_decision(self, *, selected_option_ids: Sequence[str]) -> None:
        """Refuse a decision the host already knows it cannot carry out.

        Runs before the decision is accepted, so a refusal leaves the gate
        pending instead of failing it after acceptance.
        """
        if self.kind != "plan":
            return
        from sase.plan_approval_actions import (
            PlanApprovalActionError,
            preflight_plan_archive_credential,
        )

        try:
            preflight_plan_archive_credential(selected_option_ids)
        except PlanApprovalActionError as exc:
            raise GateError(exc.code, exc.target, str(exc)) from exc

    def apply_side_effects(
        self,
        *,
        bundle_path: Path,
        response: Mapping[str, Any],
        epic_launch_origin: EpicLaunchOrigin | None = None,
    ) -> None:
        """Apply adapter-declared host effects after terminal persistence."""
        if self.kind == "task_triage":
            if isinstance(response, dict) and response.get("task_launch_task_id"):
                # A resumed retry: this decision already launched its
                # successor on a prior attempt, recorded here. Nothing else
                # in this branch is retried, so there is nothing left to do.
                return
            from sase.bead.task_gate import (
                close_task_triage,
                launch_task_triage,
                snooze_task_triage,
                translate_task_triage_response,
            )

            decision = translate_task_triage_response(bundle_path, response)
            if decision.action == "close":
                close_task_triage(decision)
                return
            if decision.action == "snooze":
                snooze_task_triage(decision)
                return
            task_launch = launch_task_triage(decision, origin=epic_launch_origin)
            if isinstance(response, dict):
                from sase.notification_gates.durability import atomic_write_json

                response["task_launch_task_id"] = task_launch.proc_id
                atomic_write_json(bundle_path / "response.json", response)
            return
        if self.kind == "bead_snooze":
            from sase.bead.snooze_gate import (
                close_bead_snooze,
                ready_bead_snooze,
                resnooze_bead_snooze,
                translate_bead_snooze_response,
            )

            snooze_decision = translate_bead_snooze_response(bundle_path, response)
            if snooze_decision.action == "close":
                close_bead_snooze(snooze_decision)
            elif snooze_decision.action == "ready":
                ready_bead_snooze(snooze_decision)
            else:
                resnooze_bead_snooze(snooze_decision)
            return
        if self.kind == "flag_triage":
            if isinstance(response, dict) and response.get("task_launch_task_id"):
                # See the task_triage guard above: this decision's launch
                # already happened on a prior attempt.
                return
            from sase.bead.flag_gate import (
                close_flag_triage,
                extend_flag_triage,
                keep_flag_triage,
                remove_flag_triage,
                translate_flag_triage_response,
            )

            flag_decision = translate_flag_triage_response(bundle_path, response)
            proc = None
            if flag_decision.action == "close":
                close_flag_triage(flag_decision)
            elif flag_decision.action == "extend":
                extend_flag_triage(flag_decision)
            elif flag_decision.action == "keep":
                proc = keep_flag_triage(flag_decision, origin=epic_launch_origin)
            else:
                proc = remove_flag_triage(flag_decision, origin=epic_launch_origin)
            if proc is not None and isinstance(response, dict):
                from sase.notification_gates.durability import atomic_write_json

                response["task_launch_task_id"] = proc.proc_id
                atomic_write_json(bundle_path / "response.json", response)
            return
        if self.kind == "bead_stale_cleanup":
            from sase.bead.stale_cleanup_gate import (
                close_bead_stale_cleanup,
                translate_bead_stale_cleanup_response,
            )

            stale_cleanup_decision = translate_bead_stale_cleanup_response(
                bundle_path, response
            )
            close_bead_stale_cleanup(stale_cleanup_decision)
            return
        if self.kind == "plugins_required":
            from sase.plugins.required_gate import (
                apply_plugins_required_decision,
                translate_plugins_required_response,
            )

            plugins_required_decision = translate_plugins_required_response(
                bundle_path, response
            )
            apply_plugins_required_decision(plugins_required_decision)
            return
        apply_plan_side_effects(
            kind=self.kind,
            bundle_path=bundle_path,
            response=response,
            epic_launch_origin=epic_launch_origin,
        )

    def prepare_terminal_response(
        self,
        *,
        bundle_path: Path,
        response: dict[str, Any],
    ) -> None:
        """Populate response fields required before the terminal file exists."""
        prepare_plan_terminal_response(
            kind=self.kind,
            bundle_path=bundle_path,
            response=response,
        )

    def validate_edited_resource(self, *, path: Path) -> None:
        """Validate an editable target before advancing its review revision."""
        validate_plan_edited_resource(kind=self.kind, path=path)

    def regenerate_previews(self, *, bundle_path: Path) -> None:
        """Regenerate adapter-owned previews after an edit."""
        del bundle_path

    def automatic_input(
        self, spec: GateSpec, decision: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return adapter-owned input for a core automatic decision.

        The input is built from the decision value only: the question
        answers for ``first``, or the epic launch mode for ``approve``.
        It never depends on ``primary_branch``, ``default_selected``, or
        option order.
        """
        value = decision.get("value")
        if value == "first":
            from sase.user_question_actions import automatic_question_response

            try:
                return automatic_question_response(spec.payload)
            except Exception as exc:
                if isinstance(exc, GateError):
                    raise
                code = getattr(exc, "code", "invalid_auto_input")
                target = getattr(exc, "target", "auto")
                raise GateError(str(code), str(target), str(exc)) from exc
        if value == "approve":
            return {"epic_launch_mode": "launch"}
        return {}
