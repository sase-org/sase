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
    _validate_plan_shell(spec, tier)


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


def _validate_plan_shell(spec: GateSpec, tier: PlanGateTier) -> None:
    """If present, pin the additive gate-shell contract to this tier."""
    if spec.shell is None:
        return
    from sase.notification_gates.model_shell import GateShellSpec
    from sase.plan_shell.create import plan_gate_shell_block

    expected = GateShellSpec.from_mapping(
        plan_gate_shell_block(tier),
        branches=spec.branches,
        allow_branch_subsets=True,
    )
    if spec.shell != expected:
        raise GateError(
            "invalid_plan_shell",
            "shell",
            f"{tier} plan gate shell block does not match the registered adapter",
        )
