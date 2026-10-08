"""Validation contract for tale and epic plan gates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.notification_gates.adapters import GateAdapter
from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import GateError, GateSpec

if TYPE_CHECKING:
    from sase.plan_gate import PlanGateTier


def validate_plan_spec(spec: GateSpec, adapter: GateAdapter) -> None:
    """Keep plan gates on their tier-specific trusted command contract."""
    tier: PlanGateTier = "epic" if adapter.kind == "epic_plan" else "tale"
    _validate_plan_payload(spec, tier, adapter.kind)
    expected_commands = _validate_plan_options(spec, tier)
    _validate_plan_groups(spec, tier)
    _validate_plan_operations(spec, tier)
    _validate_plan_resources(spec, expected_commands)
    _validate_plan_gate_turn(spec, tier)
    _validate_plan_decisions(spec, tier)


def _validate_plan_payload(spec: GateSpec, tier: PlanGateTier, kind: str) -> None:
    from sase.plan_gate import PLAN_RESOURCE_PATH

    if spec.payload.get("authored_tier") != tier:
        raise GateError(
            "plan_tier_mismatch",
            "payload.authored_tier",
            f"{kind} gates require authored tier {tier}",
        )
    if spec.payload.get("plan_resource") != PLAN_RESOURCE_PATH:
        raise GateError(
            "invalid_plan_payload",
            "payload.plan_resource",
            "plan gate payload must reference the adapter-owned plan resource",
        )


def _validate_plan_options(spec: GateSpec, tier: PlanGateTier) -> dict[str, str]:
    """Check the query and options, returning the expected command resources."""
    from sase.plan_gate import plan_gate_option_ids, plan_gate_query

    expected_query = plan_gate_query(tier)
    expected_branches = (
        (("approve",), ("reject",), ("feedback",))
        if tier == "epic"
        else (("approve", "commit"), ("reject",), ("feedback",))
    )
    if spec.query != expected_query or spec.branches != expected_branches:
        raise GateError(
            "invalid_plan_query",
            "query",
            f"{tier} plan gates require query: {expected_query}",
        )
    expected_commands = {
        option_id: f"commands/{option_id}" for option_id in plan_gate_option_ids(tier)
    }
    actual_commands = {option.id: option.command.argv[0] for option in spec.options}
    if actual_commands != expected_commands:
        raise GateError(
            "invalid_plan_options",
            "options",
            f"{tier} plan gate options do not match the registered adapter",
        )
    return expected_commands


def _validate_plan_groups(spec: GateSpec, tier: PlanGateTier) -> None:
    from sase.plan_gate import TALE_PLAN_SUBMIT_GROUP

    if tier == "tale":
        if len(spec.groups) != 1:
            raise GateError(
                "invalid_plan_group",
                "groups",
                "tale plan gates require exactly one configured submit group",
            )
        actual_group = spec.groups[0]
        if actual_group.options != TALE_PLAN_SUBMIT_GROUP.options:
            raise GateError(
                "invalid_plan_group",
                "groups[0].options",
                "tale plan submit group must contain the canonical options: "
                + ", ".join(TALE_PLAN_SUBMIT_GROUP.options),
            )
        if actual_group.label != TALE_PLAN_SUBMIT_GROUP.label:
            raise GateError(
                "invalid_plan_group",
                "groups[0].label",
                "tale plan submit group label must be "
                f"{TALE_PLAN_SUBMIT_GROUP.label!r}",
            )
        if actual_group.icon != TALE_PLAN_SUBMIT_GROUP.icon:
            raise GateError(
                "invalid_plan_group",
                "groups[0].icon",
                f"tale plan submit group icon must be {TALE_PLAN_SUBMIT_GROUP.icon!r}",
            )
    if tier == "epic" and spec.groups:
        raise GateError(
            "invalid_plan_group", "groups", "epic plan gates do not define groups"
        )


def _validate_plan_operations(spec: GateSpec, tier: PlanGateTier) -> None:
    """Pin both tiers to the registered edit action, shape and all.

    The edit action is declared rather than hardcoded per surface, so its
    presentation and its origin edit target are part of the trusted contract.
    """
    from sase.notification_gates.model_operations import GateOperation
    from sase.plan_gate import plan_gate_edit_operation

    expected = GateOperation.from_mapping(plan_gate_edit_operation(tier), 0)
    if len(spec.operations) != 1 or spec.operations[0] != expected:
        raise GateError(
            "invalid_plan_operation",
            "operations",
            f"{tier} plan gates require the registered edit_plan action",
        )


def _validate_plan_resources(spec: GateSpec, expected_commands: dict[str, str]) -> None:
    from sase.plan_gate import PLAN_RESOURCE_PATH, plan_gate_command_script

    resources = {resource.path: resource for resource in spec.resources}
    plan_resource = resources.get(PLAN_RESOURCE_PATH)
    if plan_resource is None or plan_resource.role != "editable":
        raise GateError(
            "invalid_plan_resource",
            PLAN_RESOURCE_PATH,
            "plan gates require one editable plan.md resource",
        )
    for option_id, path in expected_commands.items():
        resource = resources.get(path)
        if resource is None or resource.role != "command":
            raise GateError(
                "invalid_plan_command", path, "plan command resource is missing"
            )
        content = read_gate_resource(
            resource, code="invalid_plan_command", description="plan command"
        )
        if content != plan_gate_command_script(option_id):
            raise GateError(
                "invalid_plan_command",
                path,
                "plan command does not match the registered adapter",
            )


def _validate_plan_gate_turn(spec: GateSpec, tier: PlanGateTier) -> None:
    """If present, pin the additive gate-turn contract to this tier."""
    if spec.shell is None:
        return
    from sase.notification_gates.model_turn import GateTurnSpec
    from sase.plan_gate_turn.create import plan_gate_turn_block

    expected = GateTurnSpec.from_mapping(
        plan_gate_turn_block(tier),
        branches=spec.branches,
        allow_branch_subsets=True,
    )
    if spec.shell != expected:
        raise GateError(
            "invalid_plan_gate_turn",
            "shell",
            f"{tier} plan gate turn block does not match the registered adapter",
        )


def _validate_plan_decisions(spec: GateSpec, tier: PlanGateTier) -> None:
    """Pin compiled Plan Decision properties and result schemas.

    Rebuilds frozen definitions from the adapter-owned plan resource and the
    supplied frozen host facts (never gathering fresh environment facts),
    then round-trips through core. Any malformed definition, inconsistent
    default or kind, duplicate id, invalid provenance, unreadable resource,
    or binding exception is ``invalid_plan_decisions``.
    """
    from sase.plan_gate import (
        PLAN_APPROVE_OPTION_ID,
        PLAN_COMMIT_OPTION_ID,
        PLAN_FEEDBACK_OPTION_ID,
        PLAN_REJECT_OPTION_ID,
    )

    payload_decisions = spec.payload.get("decisions")
    by_id = {option.id: option for option in spec.options}
    if payload_decisions is None:
        for option in spec.options:
            props = option.input_schema.get("properties") or {}
            offenders = [name for name in props if name.startswith("decision_")]
            if offenders:
                raise GateError(
                    "invalid_plan_decisions",
                    f"options.{option.id}.input_schema",
                    "decision properties require payload.decisions",
                )
            result_props = option.result_schema.get("properties") or {}
            if "decisions" in result_props:
                raise GateError(
                    "invalid_plan_decisions",
                    f"options.{option.id}.result_schema",
                    "result decisions require payload.decisions",
                )
        return
    if not isinstance(payload_decisions, list):
        raise GateError(
            "invalid_plan_decisions",
            "payload.decisions",
            "payload.decisions must be a frozen definition vector",
        )
    try:
        from sase.sdd.plan_decisions import (
            compile_input_properties,
            digest_binding,
            payload_binding,
            resolve_binding,
            sheet_binding,
            validated_to_wire_dict,
        )
    except Exception as exc:
        raise GateError(
            "invalid_plan_decisions", "payload.decisions", str(exc)
        ) from exc
    try:
        frozen = [item for item in payload_decisions if isinstance(item, dict)]
        if len(frozen) != len(payload_decisions):
            raise GateError(
                "invalid_plan_decisions",
                "payload.decisions",
                "payload.decisions must be a frozen definition vector",
            )
        seen: set[str] = set()
        for item in frozen:
            decision_id = item.get("id")
            if not isinstance(decision_id, str) or not decision_id:
                raise ValueError(f"decision has invalid id: {decision_id!r}")
            if decision_id in seen:
                raise ValueError(f"duplicate decision id: {decision_id!r}")
            seen.add(decision_id)
            provenance = item.get("provenance")
            if provenance is not None and provenance not in (
                "asked",
                "not_asked",
                "quote_not_found",
                "inherited",
            ):
                raise ValueError(f"invalid provenance for {decision_id!r}")
        frozen_digest = digest_binding(list(frozen))
        rebuilt = _rebuild_definitions_from_resource(spec, tier, list(frozen))
        if digest_binding(rebuilt) != frozen_digest:
            raise GateError(
                "invalid_plan_decisions",
                "payload.decisions",
                "payload.decisions does not match the adapter-owned plan resource",
            )
        resolved = resolve_binding(list(frozen), {}, "auto")
        values = resolved.get("values")
        if not isinstance(values, dict):
            raise ValueError("resolver returned no values")
        if resolved.get("errors"):
            raise ValueError(f"effective defaults failed: {resolved.get('errors')}")
        sheet = sheet_binding(list(frozen), dict(values), 0)
        if not isinstance(sheet, dict) or not isinstance(sheet.get("rows"), list):
            raise ValueError("sheet builder returned no rows")
    except GateError:
        raise
    except Exception as exc:
        raise GateError(
            "invalid_plan_decisions", "payload.decisions", str(exc)
        ) from exc
    expected_inputs = compile_input_properties(list(payload_decisions))
    expected_ids = sorted(
        key.removeprefix("decision_") for key in expected_inputs.keys()
    )
    decision_options: tuple[str, ...]
    if tier == "tale":
        decision_options = (
            PLAN_APPROVE_OPTION_ID,
            PLAN_COMMIT_OPTION_ID,
            PLAN_FEEDBACK_OPTION_ID,
        )
    else:
        decision_options = (PLAN_APPROVE_OPTION_ID, PLAN_FEEDBACK_OPTION_ID)
    for option_id in decision_options:
        opt = by_id.get(option_id)
        if opt is None:
            continue
        props = dict(opt.input_schema.get("properties") or {})
        actual = {
            name: value for name, value in props.items() if name.startswith("decision_")
        }
        if actual != expected_inputs:
            raise GateError(
                "invalid_plan_decisions",
                f"options.{option_id}.input_schema",
                "decision properties do not match payload.decisions",
            )
        required = opt.input_schema.get("required") or []
        if any(name.startswith("decision_") for name in required):
            raise GateError(
                "invalid_plan_decisions",
                f"options.{option_id}.input_schema",
                "decision properties are never required",
            )
    reject_opt = by_id.get(PLAN_REJECT_OPTION_ID)
    if reject_opt is not None:
        reject_props = dict(reject_opt.input_schema.get("properties") or {})
        if any(name.startswith("decision_") for name in reject_props):
            raise GateError(
                "invalid_plan_decisions",
                f"options.{PLAN_REJECT_OPTION_ID}.input_schema",
                "reject declares no decision properties",
            )
        reject_result = dict(reject_opt.result_schema.get("properties") or {})
        if "decisions" in reject_result:
            raise GateError(
                "invalid_plan_decisions",
                f"options.{PLAN_REJECT_OPTION_ID}.result_schema",
                "reject declares no decision result",
            )
    feedback_opt = by_id.get(PLAN_FEEDBACK_OPTION_ID)
    if feedback_opt is not None:
        feedback_result = dict(feedback_opt.result_schema.get("properties") or {})
        if "decisions" in feedback_result:
            raise GateError(
                "invalid_plan_decisions",
                f"options.{PLAN_FEEDBACK_OPTION_ID}.result_schema",
                "feedback carries provisional values but no acceptance result",
            )
    for option_id in (PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID):
        result_opt = by_id.get(option_id)
        if result_opt is None:
            continue
        if tier == "epic" and option_id == PLAN_COMMIT_OPTION_ID:
            continue
        result_props = dict(result_opt.result_schema.get("properties") or {})
        decisions_schema = result_props.get("decisions")
        if not isinstance(decisions_schema, dict):
            raise GateError(
                "invalid_plan_decisions",
                f"options.{option_id}.result_schema",
                "approve and commit results require a decisions object",
            )
        required = result_opt.result_schema.get("required") or []
        if "decisions" not in required:
            raise GateError(
                "invalid_plan_decisions",
                f"options.{option_id}.result_schema",
                "result decisions must be required",
            )
        actual_props = decisions_schema.get("properties") or {}
        stripped = dict(expected_inputs)
        expected_result_props = {
            key.removeprefix("decision_"): value for key, value in stripped.items()
        }
        if dict(actual_props) != expected_result_props:
            raise GateError(
                "invalid_plan_decisions",
                f"options.{option_id}.result_schema",
                "result decisions do not match payload.decisions",
            )
        if sorted(decisions_schema.get("required") or []) != expected_ids:
            raise GateError(
                "invalid_plan_decisions",
                f"options.{option_id}.result_schema",
                "result decisions must require every decision id",
            )


def _rebuild_definitions_from_resource(
    spec: GateSpec, tier: PlanGateTier, frozen: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Rebuild definitions from the adapter-owned plan resource.

    Uses the validated authored questions and the frozen host facts from
    ``payload.decisions``. Never gathers fresh environment-dependent facts.
    """
    from sase.plan_gate import PLAN_RESOURCE_PATH

    resources = {resource.path: resource for resource in spec.resources}
    plan_resource = resources.get(PLAN_RESOURCE_PATH)
    if plan_resource is None:
        raise ValueError("adapter-owned plan resource is missing")
    content = read_gate_resource(
        plan_resource, code="invalid_plan_decisions", description="plan resource"
    )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("adapter-owned plan resource is unreadable")
    from sase.sdd.plan_validate import validate_plan

    validation = validate_plan(content, tier)
    if not validation.ok or validation.plan is None:
        raise ValueError("adapter-owned plan resource failed validation")
    from sase.sdd.plan_decisions import payload_binding, validated_to_wire_dict

    frozen_by_id = {
        str(item.get("id")): item for item in frozen if isinstance(item, dict)
    }
    wired = validated_to_wire_dict(validation.plan)
    host_facts: dict[str, dict[str, object]] = {}
    for decision in getattr(validation.plan, "decisions", ()):
        decision_id = getattr(decision, "id", "")
        frozen_fact = frozen_by_id.get(str(decision_id), {})
        resolved_raw = frozen_fact.get("resolved", [])
        host_facts[str(decision_id)] = {
            "requested_verified": bool(frozen_fact.get("requested_verified", False)),
            "provenance": str(frozen_fact.get("provenance", "not_asked")),
            "resolved": list(resolved_raw)
            if isinstance(resolved_raw, (list, tuple))
            else [],
        }
    rebuilt = payload_binding(wired, host_facts)
    return list(rebuilt)
