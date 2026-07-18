"""Tiered neutral plan-gate contract and compatibility coverage."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.plan_pending import plan_context_from_notification
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate, refresh_gate_after_edit
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    PlanApprovalValidationError,
    execute_plan_approval_response,
)
from sase.plan_gate import (
    _build_plan_gate_spec,
    create_plan_approval_gate,
    plan_context_from_envelope,
    plan_gate_option_ids,
    plan_gate_query,
    translate_plan_gate_response,
)

from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


@pytest.fixture()
def gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sase.notification_gates import paths
    from sase.notifications import store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy-pending.json",
    )
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    store._LOAD_CACHE.clear()
    return tmp_path


def _write_plan(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.write_text(content, encoding="utf-8")
    return path


def test_authored_tier_routes_to_distinct_typed_actions(gate_home: Path) -> None:
    tale = create_plan_approval_gate(
        _write_plan(gate_home, "tale.md", VALID_TALE_PLAN),
        "tale-request",
        agent_name="planner.tale",
    )
    epic = create_plan_approval_gate(
        _write_plan(gate_home, "epic.md", VALID_EPIC_PLAN),
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
    assert tale_approve["icon"] == "✅"
    epic_approve = epic_request["options"][0]
    assert epic_approve["id"] == "approve"
    assert epic_approve["label"] == "Epic"
    assert epic_approve["icon"] == "✅"
    assert epic_approve["default_selected"] is True
    assert epic_approve["input_schema"] == {
        "type": "object",
        "properties": {
            "epic_launch_mode": {"enum": ["detached", "foreground", "skip"]}
        },
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


def test_edit_revalidates_tier_then_refreshes_review_hashes(gate_home: Path) -> None:
    plan = _write_plan(gate_home, "edit.md", VALID_TALE_PLAN)
    gate = create_plan_approval_gate(plan, "edit-request")
    reviewed = gate.bundle_path / "plan.md"
    request_before = json.loads(gate.request_path.read_text(encoding="utf-8"))
    reviewed.write_text("# missing frontmatter\n", encoding="utf-8")

    with pytest.raises(PlanApprovalValidationError):
        refresh_gate_after_edit(gate.bundle_path, "edit_plan")
    assert json.loads(gate.request_path.read_text())["review_revision"] == 1

    edited = VALID_TALE_PLAN.replace(
        "Implement the requested change.", "Implement and verify the requested change."
    )
    reviewed.write_text(edited, encoding="utf-8")
    hashes = refresh_gate_after_edit(gate.bundle_path, "edit_plan")
    request_after = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request_after["review_revision"] == 2
    assert hashes["request"] != request_before["hashes"]["request"]
    assert (
        hashes["resources"]["plan.md"]
        != request_before["hashes"]["resources"]["plan.md"]
    )
    assert execute_gate_selection(gate.bundle_path, ["approve"]).response[
        "selected_option_ids"
    ] == ["approve"]
    assert plan.read_text(encoding="utf-8") == edited


def test_plan_context_recovers_original_file_from_old_bundle_payload(
    gate_home: Path,
) -> None:
    plan = _write_plan(gate_home, "old.md", VALID_TALE_PLAN)
    gate = create_plan_approval_gate(plan, "old-request")
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    envelope["presentation"]["action_data"].pop("original_plan_file")

    context = plan_context_from_envelope(gate.bundle_path, envelope)

    assert context.host_action_data["original_plan_file"] == str(plan)


def test_epic_gate_host_launch_uses_durable_plan_path(gate_home: Path) -> None:
    from sase.notification_gates.registry import adapter_for_kind

    plan = _write_plan(gate_home, "durable_epic.md", VALID_EPIC_PLAN)
    gate = create_plan_approval_gate(plan, "durable-launch")
    response = {
        "selected_option_ids": ["approve"],
        "input": {"epic_launch_mode": "foreground"},
        "option_results": [
            {
                "id": "approve",
                "result": {
                    "action": "epic",
                    "commit_plan": True,
                    "run_coder": True,
                    "epic_launch_owner": "host",
                },
            }
        ],
        "source": "test",
    }

    with (
        patch("sase.plan_approval_actions.run_plan_side_effects"),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch", return_value=True
        ) as prepare,
    ):
        adapter_for_kind("epic_plan").apply_side_effects(
            bundle_path=gate.bundle_path,
            response=response,
        )

    assert prepare.call_args.args[1] == plan


@pytest.mark.parametrize(
    ("content", "argument", "expected_kind"),
    [
        (VALID_TALE_PLAN, None, "plan"),
        (VALID_TALE_PLAN, "tale", "plan"),
        (VALID_EPIC_PLAN, None, "epic_plan"),
        (VALID_EPIC_PLAN, "epic", "epic_plan"),
    ],
)
def test_auto_uses_the_manual_executor_and_tier_owned_aliases(
    content: str,
    argument: str | None,
    expected_kind: str,
    gate_home: Path,
) -> None:
    gate = create_plan_approval_gate(
        _write_plan(gate_home, f"{expected_kind}-{argument}.md", content),
        f"auto-{expected_kind}-{argument or 'bare'}",
        auto_enabled=True,
        auto_argument=argument,
    )

    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["kind"] == expected_kind
    assert response["selected_option_ids"] == (
        ["approve", "commit"] if expected_kind == "plan" else ["approve"]
    )
    if expected_kind == "plan":
        assert (
            translate_plan_gate_response(gate.bundle_path, response)["commit_plan"]
            is True
        )
        assert (
            translate_plan_gate_response(gate.bundle_path, response)["run_coder"]
            is True
        )
    assert response["source"] == "auto_resolution"
    assert gate.notification_id is None
    assert load_notifications(include_dismissed=True) == []


def test_auto_rejects_unknown_and_cross_tier_arguments_before_publication(
    gate_home: Path,
) -> None:
    plan = _write_plan(gate_home, "conflict.md", VALID_TALE_PLAN)
    for argument in ("epic", "foo"):
        with pytest.raises(GateError) as exc_info:
            create_plan_approval_gate(
                plan,
                f"conflict-{argument}",
                auto_enabled=True,
                auto_argument=argument,
            )
        assert exc_info.value.code == "invalid_auto_argument"
    assert load_notifications(include_dismissed=True) == []


def test_shared_host_executor_handles_feedback_rejection_and_races(
    gate_home: Path,
) -> None:
    create_plan_approval_gate(
        _write_plan(gate_home, "feedback.md", VALID_TALE_PLAN),
        "feedback-request",
    )
    [feedback_notification] = load_notifications()
    feedback_result = execute_plan_approval_response(
        plan_context_from_notification(feedback_notification),
        "feedback",
        feedback="Add rollback coverage",
    )
    assert feedback_result.response_file == "response.json"
    assert feedback_result.response_json["selected_option_ids"] == ["feedback"]
    assert feedback_result.response_json["option_results"] == [
        {
            "id": "feedback",
            "result": {
                "action": "reject",
                "feedback": "Add rollback coverage",
            },
        }
    ]
    assert feedback_result.response_json["feedback"] == "Add rollback coverage"

    race_gate = create_plan_approval_gate(
        _write_plan(gate_home, "race.md", VALID_TALE_PLAN),
        "race-request",
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda _: execute_gate_selection(race_gate.bundle_path, ["reject"]),
                range(2),
            )
        )
    assert sorted(outcome.already_completed for outcome in outcomes) == [False, True]
    assert json.loads(race_gate.response_path.read_text())["selected_option_ids"] == [
        "reject"
    ]


def test_plan_toctou_and_unregistered_command_contract_are_rejected(
    gate_home: Path,
) -> None:
    plan = _write_plan(gate_home, "toctou.md", VALID_TALE_PLAN)
    gate = create_plan_approval_gate(plan, "toctou-request")
    (gate.bundle_path / "plan.md").write_text(
        VALID_TALE_PLAN + "\nUnreviewed mutation\n", encoding="utf-8"
    )
    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(gate.bundle_path, ["approve"])
    assert exc_info.value.code == "hash_mismatch"
    assert not gate.response_path.exists()

    forged = _build_plan_gate_spec(
        plan,
        "forged-request",
        tier="tale",
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    commands = forged["resources"]
    assert isinstance(commands, list)
    commands[1]["content"] = "#!/bin/sh\nexit 0\n"
    with pytest.raises(GateError) as exc_info:
        create_gate(forged)
    assert exc_info.value.code == "invalid_plan_command"


@pytest.mark.parametrize(
    ("selected_option_ids", "expected_commit", "expected_run"),
    [
        (("commit",), True, False),
        (("approve",), False, True),
        (("approve", "commit"), True, True),
    ],
)
def test_tale_selection_derives_runner_protocol(
    gate_home: Path,
    selected_option_ids: tuple[str, ...],
    expected_commit: bool,
    expected_run: bool,
) -> None:
    gate = create_plan_approval_gate(
        _write_plan(
            gate_home,
            f"selection-{expected_commit}-{expected_run}.md",
            VALID_TALE_PLAN,
        ),
        f"selection-{expected_commit}-{expected_run}",
    )

    execution = execute_gate_selection(
        gate.bundle_path,
        selected_option_ids,
    )
    translated = translate_plan_gate_response(gate.bundle_path, execution.response)

    assert execution.response["selected_option_ids"] == list(selected_option_ids)
    assert translated["commit_plan"] is expected_commit
    assert translated["run_coder"] is expected_run


def test_plan_action_api_executes_selected_approval_options(gate_home: Path) -> None:
    gate = create_plan_approval_gate(
        _write_plan(gate_home, "action-api.md", VALID_TALE_PLAN),
        "action-api",
    )
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))

    action_result = execute_plan_approval_response(
        plan_context_from_envelope(gate.bundle_path, envelope),
        "approve",
        commit_plan=True,
        run_coder=False,
    )

    assert action_result.response_json["selected_option_ids"] == ["commit"]
    assert action_result.response_json["option_results"] == [
        {
            "id": "commit",
            "result": {
                "action": "approve",
                "commit_plan": True,
                "run_coder": False,
            },
        }
    ]
    translated = translate_plan_gate_response(
        gate.bundle_path, action_result.response_json
    )
    assert translated["commit_plan"] is True
    assert translated["run_coder"] is False


def test_plan_action_api_filters_protocol_overrides_for_tale_preset(
    gate_home: Path,
) -> None:
    gate = create_plan_approval_gate(
        _write_plan(gate_home, "action-tale.md", VALID_TALE_PLAN),
        "action-tale",
    )
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))

    action_result = execute_plan_approval_response(
        plan_context_from_envelope(gate.bundle_path, envelope),
        "tale",
        commit_plan=True,
        run_coder=True,
    )

    assert action_result.response_json["selected_option_ids"] == [
        "approve",
        "commit",
    ]
    assert action_result.response_json["input"] == {}
    translated = translate_plan_gate_response(
        gate.bundle_path, action_result.response_json
    )
    assert translated["commit_plan"] is True
    assert translated["run_coder"] is True


def test_plan_action_api_filters_coder_options_for_commit_preset(
    gate_home: Path,
) -> None:
    gate = create_plan_approval_gate(
        _write_plan(gate_home, "action-commit.md", VALID_TALE_PLAN),
        "action-commit",
    )
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))

    action_result = execute_plan_approval_response(
        plan_context_from_envelope(gate.bundle_path, envelope),
        "commit",
        coder_prompt="#review+",
    )

    assert action_result.response_json["selected_option_ids"] == ["commit"]
    assert action_result.response_json["input"] == {}
    assert action_result.response_json["option_results"][0]["result"] == {
        "action": "approve",
        "commit_plan": True,
        "run_coder": False,
    }


@pytest.mark.parametrize(
    ("choice", "expected_commit", "expected_run"),
    [
        ("approve", True, True),
        ("run", False, True),
        ("tale", True, True),
        ("commit", True, False),
    ],
)
def test_local_action_aliases_map_to_option_selections(
    gate_home: Path,
    choice: str,
    expected_commit: bool,
    expected_run: bool,
) -> None:
    gate = create_plan_approval_gate(
        _write_plan(gate_home, f"preset-{choice}.md", VALID_TALE_PLAN),
        f"preset-{choice}",
    )

    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    execution = execute_plan_approval_response(
        plan_context_from_envelope(gate.bundle_path, envelope), choice
    )
    translated = translate_plan_gate_response(gate.bundle_path, execution.response_json)

    assert translated["commit_plan"] is expected_commit
    assert translated["run_coder"] is expected_run


def test_plan_adapter_rejects_non_registered_query_shape(
    gate_home: Path,
) -> None:
    plan = _write_plan(gate_home, "forged-query.md", VALID_TALE_PLAN)
    spec = _build_plan_gate_spec(
        plan,
        "forged-query",
        tier="tale",
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    spec["query"] = "approve OR commit OR reject OR feedback"
    spec["primary_branch"] = ["approve"]
    spec["groups"] = []

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)
    assert exc_info.value.code == "invalid_plan_query"


def test_plan_adapter_accepts_tale_group_and_rejects_stale_label(
    gate_home: Path,
) -> None:
    plan = _write_plan(gate_home, "group-label.md", VALID_TALE_PLAN)
    canonical = _build_plan_gate_spec(
        plan,
        "canonical-group-label",
        tier="tale",
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )

    result = create_gate(canonical)
    request = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert request["groups"] == [
        {"options": ["approve", "commit"], "label": "Tale", "icon": "✅"}
    ]

    stale = _build_plan_gate_spec(
        plan,
        "stale-group-label",
        tier="tale",
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    stale["groups"][0]["label"] = "Approve"

    with pytest.raises(GateError) as exc_info:
        create_gate(stale)
    assert exc_info.value.code == "invalid_plan_group"
    assert exc_info.value.target == "groups[0].label"
    assert str(exc_info.value) == "tale plan submit group label must be 'Tale'"


def test_legacy_plan_approval_remains_answerable(gate_home: Path) -> None:
    plan = _write_plan(gate_home, "legacy.md", VALID_TALE_PLAN)
    response_dir = gate_home / "legacy-plan-approval"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}\n", encoding="utf-8")
    result = execute_plan_approval_response(
        PlanApprovalActionContext(
            id="legacy-notification",
            host_files=(str(plan),),
            host_action_data={"response_dir": str(response_dir)},
        ),
        "reject",
    )

    assert result.response_file == "plan_response.json"
    assert json.loads(result.response_path.read_text()) == {"action": "reject"}
