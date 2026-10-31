"""Command-script generation and execution for plan gate options."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sase.notification_gates.entrypoints import (
    gate_command_entrypoint,
    python_gate_command_script,
)

from ._plan_gate_metadata import plan_gate_option_ids
from ._plan_gate_shared import (
    PLAN_APPROVE_OPTION_ID,
    PLAN_COMMIT_OPTION_ID,
    PLAN_FEEDBACK_OPTION_ID,
    PLAN_REJECT_OPTION_ID,
    PLAN_RESOURCE_PATH,
    PlanGateTier,
    plan_gate_optional_capacity,
    plan_gate_optional_text,
)


def plan_gate_command_script(option_id: str) -> str:
    """Return the hashed adapter-owned command wrapper for *option_id*."""
    return python_gate_command_script(
        "from sase.plan_gate import execute_plan_gate_command\n"
        f"raise SystemExit(execute_plan_gate_command({option_id!r}))\n"
    )


@gate_command_entrypoint
def execute_plan_gate_command(option_id: str) -> int:
    """Entry point used by the command resources inside plan gate bundles."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("plan command input must be an object", file=sys.stderr)
        return 2

    try:
        envelope = json.loads((Path.cwd() / "request.json").read_text(encoding="utf-8"))
        if not isinstance(envelope, dict):
            raise ValueError("request envelope is not an object")
        kind = envelope.get("kind")
        tier: PlanGateTier = "epic" if kind == "epic_plan" else "tale"
        if option_id not in plan_gate_option_ids(tier):
            raise ValueError(f"option {option_id!r} is not valid for a {tier} plan")

        if option_id not in {PLAN_REJECT_OPTION_ID, PLAN_FEEDBACK_OPTION_ID}:
            from sase.plan_approval_actions import require_plan_approval_validation

            require_plan_approval_validation(Path.cwd() / PLAN_RESOURCE_PATH, tier)

        feedback = plan_gate_optional_text(raw_input.get("feedback"))
        from sase.plan_approval_actions import plan_response_json
        from sase.wait_spec import parse_wait_spec

        protocol_choice = (
            "epic"
            if tier == "epic" and option_id == PLAN_APPROVE_OPTION_ID
            else option_id
        )
        wait_text = plan_gate_optional_text(raw_input.get("wait"))
        wait_spec = parse_wait_spec(wait_text) if wait_text is not None else None
        _reject_turn_waits_on_pre_upgrade_bundle(envelope, option_id, wait_spec)
        capacity = None
        if protocol_choice == "epic" and "capacity" in raw_input:
            capacity = plan_gate_optional_capacity(raw_input.get("capacity"))
        result, _message = plan_response_json(
            protocol_choice,
            feedback=feedback,
            commit_plan=None,
            run_coder=None,
            coder_prompt=plan_gate_optional_text(raw_input.get("coder_prompt")),
            coder_model=plan_gate_optional_text(raw_input.get("coder_model")),
            wait_spec=wait_spec,
            capacity=capacity,
        )
        if option_id in {PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID}:
            decisions = {
                key.removeprefix("decision_"): value
                for key, value in raw_input.items()
                if isinstance(key, str) and key.startswith("decision_")
            }
            if decisions:
                result["decisions"] = decisions
        if protocol_choice == "epic":
            mode = raw_input.get("epic_launch_mode", "launch")
            if mode not in {"launch", "detached", "skip"}:
                raise ValueError(f"unsupported epic launch mode: {mode}")
            # Transitional compatibility for pre-upgrade agents, which launch
            # the epic themselves unless the host owner is explicit.
            result["epic_launch_owner"] = "host"
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result, sort_keys=True))
    return 0


def _reject_turn_waits_on_pre_upgrade_bundle(
    envelope: object,
    option_id: str,
    wait_spec: object,
) -> None:
    """Fail turn-scoped waits answered on a gate that predates turn waits.

    Bundles embed their result schemas with ``additionalProperties: false``,
    so a pre-upgrade bundle still rejects ``wait_turn_agents``. Answers that
    request no turn entries keep working there; only turn entries fail, with
    a message that names the fix.
    """
    turn_agents = getattr(wait_spec, "turn_target_agents", ())
    if not turn_agents:
        return
    properties: dict[str, object] = {}
    if isinstance(envelope, dict):
        options = envelope.get("options")
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict) and option.get("id") == option_id:
                    schema = option.get("result_schema")
                    if isinstance(schema, dict):
                        raw = schema.get("properties")
                        if isinstance(raw, dict):
                            properties = raw
                    break
    if "wait_turn_agents" not in properties:
        raise ValueError(
            "this gate predates turn waits; answer without turn= or re-create the gate"
        )
