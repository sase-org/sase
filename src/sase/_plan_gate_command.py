"""Command-script generation and execution for plan gate options."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sase.notification_gates.entrypoints import gate_command_entrypoint

from ._plan_gate_metadata import plan_gate_option_ids
from ._plan_gate_shared import (
    PLAN_APPROVE_OPTION_ID,
    PLAN_FEEDBACK_OPTION_ID,
    PLAN_REJECT_OPTION_ID,
    PLAN_RESOURCE_PATH,
    PlanGateTier,
    plan_gate_optional_text,
)


def plan_gate_command_script(option_id: str) -> str:
    """Return the hashed adapter-owned command wrapper for *option_id*."""
    return (
        f"#!{sys.executable}\n"
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

        protocol_choice = (
            "epic"
            if tier == "epic" and option_id == PLAN_APPROVE_OPTION_ID
            else option_id
        )
        result, _message = plan_response_json(
            protocol_choice,
            feedback=feedback,
            commit_plan=None,
            run_coder=None,
            coder_prompt=plan_gate_optional_text(raw_input.get("coder_prompt")),
            coder_model=plan_gate_optional_text(raw_input.get("coder_model")),
        )
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
