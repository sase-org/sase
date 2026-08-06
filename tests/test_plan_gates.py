"""Tiered neutral plan-gate request envelope and presentation coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notifications.store import load_notifications
from sase.plan_gate import (
    PlanGateTier,
    create_plan_approval_gate,
    plan_context_from_envelope,
    plan_gate_option_icon,
    plan_gate_option_ids,
    plan_gate_query,
)

from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers the gate_home fixture)
    write_plan,
)
from tests.plan_validation_helpers import (
    VALID_EPIC_PLAN,
    VALID_TALE_PLAN,
)


def test_authored_tier_routes_to_distinct_typed_actions(gate_home: Path) -> None:
    tale = create_plan_approval_gate(
        write_plan(gate_home, "tale.md", VALID_TALE_PLAN),
        "tale-request",
        agent_name="planner.tale",
    )
    epic = create_plan_approval_gate(
        write_plan(gate_home, "epic.md", VALID_EPIC_PLAN),
        "epic-request",
        agent_name="planner.epic",
    )

    tale_request = json.loads(tale.request_path.read_text(encoding="utf-8"))
    epic_request = json.loads(epic.request_path.read_text(encoding="utf-8"))
    assert tale_request["kind"] == "plan"
    assert epic_request["kind"] == "epic_plan"
    assert tale_request["query"] == plan_gate_query("tale")
    assert epic_request["query"] == plan_gate_query("epic")
    assert tale_request["primary_branch"] == ["approve", "commit"]
    assert epic_request["primary_branch"] == ["approve"]
    assert tale_request["branches"] == [
        ["approve", "commit"],
        ["reject"],
        ["feedback"],
    ]
    assert epic_request["branches"] == [
        ["approve"],
        ["reject"],
        ["feedback"],
    ]
    assert [option["id"] for option in tale_request["options"]] == list(
        plan_gate_option_ids("tale")
    )
    assert [option["id"] for option in epic_request["options"]] == list(
        plan_gate_option_ids("epic")
    )
    tale_approve = tale_request["options"][0]
    assert tale_approve["id"] == "approve"
    assert tale_approve["label"] == "Launch coder agent"
    assert tale_approve["icon"] == "🚀"
    epic_approve = epic_request["options"][0]
    assert epic_approve["id"] == "approve"
    assert epic_approve["label"] == "Epic"
    assert epic_approve["icon"] == "✅"
    assert epic_approve["default_selected"] is True
    assert epic_approve["input_schema"] == {
        "type": "object",
        "properties": {"epic_launch_mode": {"enum": ["detached", "skip"]}},
        "additionalProperties": False,
    }
    assert epic_approve["result_schema"] == {
        "type": "object",
        "required": ["action", "commit_plan", "run_coder"],
        "properties": {
            "action": {"const": "epic"},
            "commit_plan": {"type": "boolean"},
            "run_coder": {"type": "boolean"},
            "coder_prompt": {"type": "string"},
            "coder_model": {"type": "string"},
            "epic_launch_owner": {"const": "host"},
        },
        "additionalProperties": False,
    }
    assert tale_request["options"][1]["id"] == "commit"
    assert tale_request["options"][1]["label"] == (
        "Commit plan file to the plans sidecar"
    )
    assert tale_request["options"][1]["icon"] == "💾"
    assert [option["label"] for option in tale_request["options"][2:]] == [
        "Reject",
        "Send Feedback",
    ]
    assert all(option["default_selected"] for option in tale_request["options"])
    assert tale_request["groups"] == [
        {"options": ["approve", "commit"], "label": "Tale", "icon": "✅"}
    ]
    assert epic_request["groups"] == []
    assert tale_request["operations"] == [
        {"id": "edit_plan", "kind": "edit_file", "target": "plan.md"}
    ]
    assert epic_request["operations"] == tale_request["operations"]
    assert (tale.bundle_path / "plan.md").read_text() == VALID_TALE_PLAN
    assert (epic.bundle_path / "plan.md").read_text() == VALID_EPIC_PLAN
    assert tale_request["presentation"]["action_data"]["original_plan_file"] == str(
        gate_home / "tale.md"
    )
    assert epic_request["presentation"]["action_data"]["original_plan_file"] == str(
        gate_home / "epic.md"
    )

    actions = {row.action for row in load_notifications()}
    assert actions == {"PlanApproval", "EpicApproval"}


def test_plan_gate_project_dir_uses_runtime_neutral_env_contract(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_project_dir = gate_home / "active-project"
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(active_project_dir))

    gate = create_plan_approval_gate(
        write_plan(gate_home, "active.md", VALID_TALE_PLAN),
        "active-project-request",
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["presentation"]["action_data"]["project_dir"] == str(
        active_project_dir
    )


@pytest.mark.parametrize(
    ("tier", "option_id", "expected"),
    [
        ("tale", "approve", "🚀"),
        ("epic", "approve", "✅"),
        ("tale", "commit", "💾"),
        ("tale", "reject", "❌"),
        ("tale", "feedback", "💬"),
    ],
)
def test_plan_gate_option_icons_are_tier_aware(
    tier: PlanGateTier, option_id: str, expected: str
) -> None:
    assert plan_gate_option_icon(option_id, tier=tier) == expected


def test_plan_context_recovers_original_file_from_old_bundle_payload(
    gate_home: Path,
) -> None:
    plan = write_plan(gate_home, "old.md", VALID_TALE_PLAN)
    gate = create_plan_approval_gate(plan, "old-request")
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    envelope["presentation"]["action_data"].pop("original_plan_file")

    context = plan_context_from_envelope(gate.bundle_path, envelope)

    assert context.host_action_data["original_plan_file"] == str(plan)
