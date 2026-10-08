"""Plan and epic-plan side effects for notification gate adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.notification_gates.model_results import effective_response_input
from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin


def apply_plan_side_effects(
    *,
    kind: str,
    bundle_path: Path,
    response: Mapping[str, Any],
    epic_launch_origin: EpicLaunchOrigin | None = None,
) -> None:
    """Apply plan and epic-plan host effects after terminal persistence."""
    if kind not in {"plan", "epic_plan"}:
        return
    from sase.notification_gates.durability import read_json_object
    from sase.plan_approval_actions import apply_plan_post_terminal_side_effects
    from sase.plan_gate import (
        plan_context_from_envelope,
        translate_plan_gate_response,
    )

    try:
        from sase.plan_gate_decisions import recover_plan_stamp_from_response

        recover_plan_stamp_from_response(bundle_path)
    except Exception:
        pass
    envelope = read_json_object(bundle_path / "request.json")
    selected_ids, result = _plan_response_selection_and_result(
        kind,
        bundle_path,
        response,
    )
    plan_action = _plan_action_for_selection(kind, selected_ids)
    context = plan_context_from_envelope(bundle_path, envelope)
    translated = translate_plan_gate_response(bundle_path, response)
    result.update(translated)
    apply_plan_post_terminal_side_effects(
        context,
        plan_action,
        source=str(response.get("source") or "plan_response"),
    )
    _post_plan_auto_receipt_best_effort(
        kind,
        bundle_path,
        envelope,
        response,
        selected_ids,
    )
    if plan_action == "epic" and result.get("epic_launch_owner") == "host":
        _publish_shell_terminal_before_epic_launch(
            bundle_path,
            envelope,
            response,
        )
        effective_input = effective_response_input(response, selected_ids[0])
        mode = effective_input.get("epic_launch_mode") or "launch"
        already_launched = isinstance(response, dict) and (
            response.get("epic_launch_monitor_id")
            or response.get("epic_launch_task_id")
        )
        if mode != "skip" and not already_launched:
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
                from sase.wait_spec import wait_spec_from_name_lists

                launch = prepare_epic_launch(
                    context,
                    launch_plan,
                    mode="launch",
                    response_dir=bundle_path,
                    origin=(
                        epic_launch_origin
                        if epic_launch_origin is not None
                        else epic_launch_origin_from_gate_source(
                            str(response.get("source") or "")
                        )
                    ),
                    wait_spec=wait_spec_from_name_lists(
                        result.get("wait_agents"),
                        result.get("wait_beads"),
                        result.get("wait_hoods"),
                    ),
                    capacity=_capacity_from_launch_result(result),
                )
            except PlanApprovalActionError as exc:
                raise GateError(exc.code, exc.target, str(exc)) from exc
            if launch is not None and isinstance(response, dict):
                from sase.notification_gates.durability import atomic_write_json

                monitor_id = getattr(launch, "monitor_id", None)
                task_id = getattr(launch, "proc_id", None)
                if monitor_id:
                    response["epic_launch_monitor_id"] = str(monitor_id)
                elif task_id:
                    response["epic_launch_task_id"] = str(task_id)
                atomic_write_json(bundle_path / "response.json", response)


def prepare_plan_terminal_response(
    *,
    kind: str,
    bundle_path: Path,
    response: dict[str, Any],
) -> None:
    """Populate plan response fields required before the terminal file exists."""
    if kind not in {"plan", "epic_plan"}:
        return
    from sase.notification_gates.durability import read_json_object
    from sase.plan_approval_actions import (
        PlanApprovalActionError,
        prepare_plan_terminal_response as prepare_response,
    )
    from sase.plan_gate import (
        plan_context_from_envelope,
        translate_plan_gate_response,
    )

    envelope = read_json_object(bundle_path / "request.json")
    selected_ids, result = _plan_response_selection_and_result(
        kind,
        bundle_path,
        response,
    )
    translated = translate_plan_gate_response(bundle_path, response)
    result.update(translated)
    try:
        prepare_response(
            plan_context_from_envelope(bundle_path, envelope),
            _plan_action_for_selection(kind, selected_ids),
            result,
            source=str(response.get("source") or "plan_response"),
            caller=str(response.get("caller") or "human"),
        )
    except PlanApprovalActionError as exc:
        raise GateError(exc.code, exc.target, str(exc)) from exc


def validate_plan_edited_resource(*, kind: str, path: Path) -> None:
    """Validate a plan editable target before advancing its review revision."""
    if kind not in {"plan", "epic_plan"}:
        return
    from sase.plan_approval_actions import require_plan_approval_validation

    validation = require_plan_approval_validation(
        path,
        "epic" if kind == "epic_plan" else "tale",
    )
    try:
        from sase.notification_gates.durability import read_json_object

        bundle_path = path.parent
        envelope = read_json_object(bundle_path / "request.json")
        payload_decisions = envelope.get("payload", {}).get("decisions")
    except Exception:
        payload_decisions = None
    if not payload_decisions:
        return
    from sase.sdd.frontmatter import parse_frontmatter

    try:
        frontmatter, _body, had = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        frontmatter, had = {}, False
    if had and any(
        key in frontmatter for key in ("answer", "decided_by", "decided_via")
    ):
        raise GateError(
            "decision-frozen",
            str(path),
            "Decisions are fixed for this review. Change answers in the Decisions panel, or send feedback to change the questions.",
        )
    decisions_map = frontmatter.get("decisions") if had else None
    if isinstance(decisions_map, dict) and any(
        isinstance(value, dict) and "answer" in value
        for value in decisions_map.values()
    ):
        raise GateError(
            "decision-frozen",
            str(path),
            "Decisions are fixed for this review. Change answers in the Decisions panel, or send feedback to change the questions.",
        )
    try:
        from sase.sdd.plan_decisions import (
            digest_binding,
            payload_binding,
            validated_to_wire_dict,
        )

        frozen_by_id = {
            str(item.get("id")): item
            for item in payload_decisions
            if isinstance(item, dict) and item.get("id")
        }
        wired = validated_to_wire_dict(validation.plan)
        host_facts = {}
        for decision in getattr(validation.plan, "decisions", ()):
            frozen = frozen_by_id.get(decision.id, {})
            host_facts[decision.id] = {
                "requested_verified": bool(frozen.get("requested_verified", False)),
                "provenance": frozen.get("provenance", "not_asked"),
                "resolved": list(frozen.get("resolved", [])),
            }
        rebuilt = payload_binding(wired, host_facts)
        if digest_binding(rebuilt) != digest_binding(list(payload_decisions)):
            raise GateError(
                "decision-frozen",
                str(path),
                "Decisions are fixed for this review. Change answers in the Decisions panel, or send feedback to change the questions.",
            )
    except GateError:
        raise
    except Exception as exc:
        raise GateError("decision-frozen", str(path), str(exc)) from exc


def _publish_shell_terminal_before_epic_launch(
    bundle_path: Path,
    envelope: Mapping[str, Any],
    response: Mapping[str, Any],
) -> None:
    """Publish shell terminal state and the refresh pulse before epic launch.

    ``%auto`` keeps first-time ``creator_live`` settlement, which must not see
    an already-terminal shell.
    """
    if str(response.get("source") or "") == "auto_resolution":
        return
    if not (
        isinstance(envelope.get("turn"), dict)
        or isinstance(envelope.get("shell"), dict)
    ):
        return
    try:
        from sase.gate_turn.settlement import publish_gate_turn_terminal_state
        from sase.gate_turn.store import find_gate_turn_by_gate_id

        record = find_gate_turn_by_gate_id(
            None, str(envelope.get("request_id") or bundle_path.name)
        )
        if record is None:
            return
        publish_gate_turn_terminal_state(
            record,
            gate_state="answered",
            reason="gate answered",
        )
    except Exception:
        return


def _plan_response_selection_and_result(
    kind: str,
    bundle_path: Path,
    response: Mapping[str, Any],
) -> tuple[tuple[str, ...], dict[str, Any]]:
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
    result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping) and entry.get("id") == selected_ids[0]
        ),
        None,
    )
    if not isinstance(result, dict):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "plan response is missing the primary option result",
        )
    _plan_action_for_selection(kind, selected_ids)
    return selected_ids, result


def _plan_action_for_selection(kind: str, selected_ids: tuple[str, ...]) -> str:
    if kind == "epic_plan" and selected_ids == ("approve",):
        return "epic"
    if selected_ids == ("commit",):
        return "commit"
    return selected_ids[0]


def _capacity_from_launch_result(result: Mapping[str, Any]) -> int | None:
    """Read durable epic capacity from a translated approve result."""
    value = result.get("capacity")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _post_plan_auto_receipt_best_effort(
    kind: str,
    bundle_path: Path,
    envelope: Mapping[str, Any],
    response: Mapping[str, Any],
    selected_ids: Sequence[str],
) -> None:
    """Post the quiet ``%auto`` receipt when a decision plan auto-resolves.

    Best effort: anything missing (non-auto source, no frozen definitions,
    disabled flag) silently posts nothing. Plans without decisions stay
    silent, as they are today.
    """
    try:
        if str(response.get("source") or "") != "auto_resolution":
            return
        payload = envelope.get("payload")
        definitions = payload.get("decisions") if isinstance(payload, dict) else None
        if not isinstance(definitions, list) or not definitions:
            return
        from sase.sdd.plan_decision_handoff import post_auto_approval_receipt
        from sase.sdd.plan_decisions import sheet_binding

        values: dict[str, Any] = {}
        for option_id in selected_ids:
            effective = effective_response_input(response, option_id)
            if not isinstance(effective, dict):
                continue
            for key, value in effective.items():
                if str(key).startswith("decision_"):
                    values[str(key).removeprefix("decision_")] = value
        sheet = sheet_binding(list(definitions), values)
        original = (
            payload.get("original_plan_file") if isinstance(payload, dict) else ""
        )
        name = (
            Path(str(original)).name
            if str(original or "").strip()
            else bundle_path.name
        )
        tier = "epic" if kind == "epic_plan" else "tale"
        post_auto_approval_receipt(
            request_id=bundle_path.name,
            plan_label=f"{tier} \u00b7 {name}",
            sheet=sheet,
        )
    except Exception:
        return
