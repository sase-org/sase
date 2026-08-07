"""Registered typed projections for notification gate kinds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.notification_gates.model_results import effective_response_input
from sase.notification_gates.models import (
    GateError,
    GateFeedbackMode,
    GateOption,
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
    auto_policy: str
    neutral_only: bool = False
    default_feedback: GateFeedbackMode = "disabled"
    generic_form: bool = False
    branch_actionable: bool = True

    def resolve_auto_selection(
        self, spec: GateSpec, argument: str | None
    ) -> tuple[str, ...]:
        """Interpret the common opaque auto argument for this kind."""
        by_id = {option.id: option for option in spec.options}
        if self.auto_policy == "forbidden":
            raise GateError(
                "auto_not_supported",
                "auto",
                f"automatic resolution is not supported for {self.kind} gates",
            )
        if self.auto_policy == "first":
            if argument not in (None, "", "first"):
                raise GateError(
                    "invalid_auto_argument",
                    "auto.argument",
                    f"unsupported {self.kind} auto argument: {argument}",
                )
            return _default_branch_selection(spec.primary_branch, by_id)

        allowed = {
            "plan": {None, "", "plan", "tale"},
            "epic_plan": {None, "", "epic", "epic_plan"},
        }[self.kind]
        if argument not in allowed:
            raise GateError(
                "invalid_auto_argument",
                "auto.argument",
                f"unsupported {self.kind} auto argument: {argument}",
            )
        return _default_branch_selection(spec.primary_branch, by_id)

    def apply_side_effects(
        self,
        *,
        bundle_path: Path,
        response: Mapping[str, Any],
        epic_launch_origin: EpicLaunchOrigin | None = None,
    ) -> None:
        """Apply adapter-declared host effects after terminal persistence."""
        if self.kind == "task_triage":
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

                response["task_launch_task_id"] = task_launch.task_id
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
        if self.kind not in {"plan", "epic_plan"}:
            return
        from sase.notification_gates.durability import read_json_object
        from sase.plan_approval_actions import run_plan_side_effects
        from sase.plan_gate import (
            plan_context_from_envelope,
            translate_plan_gate_response,
        )

        envelope = read_json_object(bundle_path / "request.json")
        selected = response.get("selected_option_ids")
        option_results = response.get("option_results")
        if (
            not isinstance(selected, list)
            or not selected
            or not all(isinstance(option_id, str) for option_id in selected)
            or not isinstance(option_results, list)
        ):
            raise GateError(
                "invalid_response",
                str(bundle_path / "response.json"),
                "plan response is missing its selected options or results",
            )
        selected_ids = tuple(selected)
        plan_action = (
            "epic"
            if self.kind == "epic_plan" and selected_ids == ("approve",)
            else "commit"
            if selected_ids == ("commit",)
            else selected_ids[0]
        )
        first_result = next(
            (
                entry.get("result")
                for entry in option_results
                if isinstance(entry, Mapping) and entry.get("id") == selected_ids[0]
            ),
            None,
        )
        if not isinstance(first_result, dict):
            raise GateError(
                "invalid_response",
                str(bundle_path / "response.json"),
                "plan response is missing the primary option result",
            )
        result = first_result
        context = plan_context_from_envelope(bundle_path, envelope)
        translated = translate_plan_gate_response(bundle_path, response)
        result.update(translated)
        run_plan_side_effects(
            context,
            plan_action,
            bundle_path / "response.json",
            result,
            response_container=response if isinstance(response, dict) else None,
            source=str(response.get("source") or "plan_response"),
        )
        if plan_action == "epic" and result.get("epic_launch_owner") == "host":
            effective_input = effective_response_input(response, selected_ids[0])
            mode = effective_input.get("epic_launch_mode") or "detached"
            if mode == "detached":
                from sase.plan_approval_actions import (
                    PlanApprovalActionError,
                    durable_plan_file_for_context,
                    prepare_epic_launch,
                )

                launch_plan = durable_plan_file_for_context(context) or (
                    bundle_path / "plan.md"
                )
                from sase.bead.epic_launch import (
                    epic_launch_origin_from_gate_source,
                )

                try:
                    task = prepare_epic_launch(
                        context,
                        launch_plan,
                        mode="detached",
                        response_dir=bundle_path,
                        origin=(
                            epic_launch_origin
                            if epic_launch_origin is not None
                            else epic_launch_origin_from_gate_source(
                                str(response.get("source") or "")
                            )
                        ),
                    )
                except PlanApprovalActionError as exc:
                    raise GateError(exc.code, exc.target, str(exc)) from exc
                if task is not None and isinstance(response, dict):
                    from sase.notification_gates.durability import atomic_write_json

                    response["epic_launch_task_id"] = task.task_id
                    atomic_write_json(bundle_path / "response.json", response)

    def validate_selection(
        self,
        *,
        selected_option_ids: Sequence[str],
        feedback: str | None,
    ) -> None:
        """Reject a selection this kind cannot act on, before it is persisted.

        The generic gate form carries structured input for some kinds in their
        one free-text feedback field, which no option command can see. Kinds
        that parse that text check it here so a typo leaves the gate pending
        instead of answering it with an instruction the host cannot follow.
        """
        if self.kind == "bead_snooze":
            from sase.bead.snooze_gate import validate_bead_snooze_feedback

            validate_bead_snooze_feedback(selected_option_ids, feedback)
        elif self.kind == "task_triage":
            from sase.bead.task_gate import validate_task_triage_feedback

            validate_task_triage_feedback(selected_option_ids, feedback)

    def validate_edited_resource(self, *, path: Path) -> None:
        """Validate an editable target before advancing its review revision."""
        if self.kind not in {"plan", "epic_plan"}:
            return
        from sase.plan_approval_actions import require_plan_approval_validation

        require_plan_approval_validation(
            path,
            "epic" if self.kind == "epic_plan" else "tale",
        )

    def regenerate_previews(self, *, bundle_path: Path) -> None:
        """Regenerate adapter-owned previews after an edit."""
        del bundle_path

    def automatic_input(self, spec: GateSpec) -> dict[str, Any]:
        """Return adapter-owned input for a common automatic resolution."""
        if self.kind == "question":
            from sase.user_question_actions import automatic_question_response

            try:
                return automatic_question_response(spec.payload)
            except Exception as exc:
                if isinstance(exc, GateError):
                    raise
                code = getattr(exc, "code", "invalid_auto_input")
                target = getattr(exc, "target", "auto")
                raise GateError(str(code), str(target), str(exc)) from exc
        if self.kind == "epic_plan":
            return {"epic_launch_mode": "detached"}
        return {}


def _default_branch_selection(
    branch: tuple[str, ...], by_id: Mapping[str, GateOption]
) -> tuple[str, ...]:
    selected = tuple(
        option_id for option_id in branch if by_id[option_id].default_selected
    )
    return selected or (branch[0],)


_ADAPTERS = (
    GateAdapter(
        kind="plan",
        display_title="Plan Approval",
        action="PlanApproval",
        pending_action_kind="plan_approval",
        sender="plan",
        request_filename="plan_request.json",
        response_filename="plan_response.json",
        legacy_directory_key="response_dir",
        auto_policy="approval",
    ),
    GateAdapter(
        kind="epic_plan",
        display_title="Epic Approval",
        action="EpicApproval",
        pending_action_kind="epic_approval",
        sender="epic",
        request_filename="plan_request.json",
        response_filename="plan_response.json",
        legacy_directory_key="response_dir",
        auto_policy="approval",
    ),
    GateAdapter(
        kind="question",
        display_title="Question",
        action="UserQuestion",
        pending_action_kind="user_question",
        sender="question",
        request_filename="question_request.json",
        response_filename="question_response.json",
        legacy_directory_key="response_dir",
        auto_policy="first",
        branch_actionable=False,
    ),
    GateAdapter(
        kind="launch",
        display_title="Launch Approval",
        action="LaunchApproval",
        pending_action_kind="launch_approval",
        sender="launch",
        request_filename="launch_request.json",
        response_filename="launch_response.json",
        legacy_directory_key="response_dir",
        auto_policy="forbidden",
    ),
    GateAdapter(
        kind="hitl",
        display_title="HITL",
        action="HITL",
        pending_action_kind="hitl",
        sender="hitl",
        request_filename="hitl_request.json",
        response_filename="hitl_response.json",
        legacy_directory_key="artifacts_dir",
        auto_policy="forbidden",
    ),
    GateAdapter(
        kind="task_triage",
        display_title="Task Triage",
        action="TaskTriage",
        pending_action_kind="task_triage",
        sender="bead",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        auto_policy="forbidden",
        neutral_only=True,
        generic_form=True,
    ),
    GateAdapter(
        kind="bead_snooze",
        display_title="Snoozed Task",
        action="BeadSnooze",
        pending_action_kind="bead_snooze",
        sender="bead",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bead_snooze_dir",
        auto_policy="forbidden",
        neutral_only=True,
        generic_form=True,
    ),
    GateAdapter(
        kind="custom",
        display_title="Custom Gate",
        action="CustomGate",
        pending_action_kind="custom_gate",
        sender="custom",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        auto_policy="forbidden",
        neutral_only=True,
        default_feedback="optional",
        generic_form=True,
    ),
)

_BY_KIND = {adapter.kind: adapter for adapter in _ADAPTERS}
_BY_ACTION = {adapter.action: adapter for adapter in _ADAPTERS}
_KIND_ALIASES = {
    "plan_approval": "plan",
    "epic": "epic_plan",
    "epic_approval": "epic_plan",
    "user_question": "question",
    "launch_approval": "launch",
}

PRIVILEGED_GATE_ACTIONS = frozenset(_BY_ACTION)


def adapter_for_kind(kind: str) -> GateAdapter:
    """Return the registered adapter for *kind*."""
    canonical = _KIND_ALIASES.get(kind, kind)
    try:
        return _BY_KIND[canonical]
    except KeyError as exc:
        raise GateError(
            "unknown_gate_kind", "kind", f"unregistered gate kind: {kind}"
        ) from exc


def adapter_for_action(action: str | None) -> GateAdapter | None:
    """Return the registered adapter projected by a notification action."""
    if action is None:
        return None
    return _BY_ACTION.get(action)


def registered_gate_kinds() -> tuple[str, ...]:
    """Return canonical registered kind identifiers."""
    return tuple(adapter.kind for adapter in _ADAPTERS)


__all__ = [
    "PRIVILEGED_GATE_ACTIONS",
    "GateAdapter",
    "adapter_for_action",
    "adapter_for_kind",
    "registered_gate_kinds",
]
