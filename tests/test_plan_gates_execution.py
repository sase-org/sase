"""Plan-gate selection execution, epic launch, and auto-resolution coverage."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.main.plan_pending import plan_context_from_notification
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notifications.store import load_notifications
from sase.plan_approval_actions import execute_plan_approval_response
from sase.plan_gate import (
    create_plan_approval_gate,
    translate_plan_gate_response,
)

from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers the gate_home fixture)
    write_plan,
)
from tests.plan_validation_helpers import (
    VALID_EPIC_PLAN,
    VALID_TALE_PLAN,
)


@pytest.mark.parametrize(
    ("source", "expected_origin"),
    [
        ("telegram", "telegram"),
        ("tui", "ace"),
    ],
)
def test_epic_gate_host_launch_uses_durable_plan_path(
    gate_home: Path,
    source: str,
    expected_origin: str,
) -> None:
    from sase.notification_gates.registry import adapter_for_kind

    plan = write_plan(gate_home, "durable_epic.md", VALID_EPIC_PLAN)
    gate = create_plan_approval_gate(plan, "durable-launch")
    response = {
        "selected_option_ids": ["approve"],
        "input": {"epic_launch_mode": "detached"},
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
        "source": source,
    }

    with (
        patch("sase.plan_approval_actions.run_plan_side_effects"),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(monitor_id="mon-durable"),
        ) as prepare,
    ):
        adapter_for_kind("epic_plan").apply_side_effects(
            bundle_path=gate.bundle_path,
            response=response,
        )

    assert prepare.call_args.args[1] == plan
    assert prepare.call_args.kwargs["mode"] == "detached"
    assert prepare.call_args.kwargs["origin"] == expected_origin
    assert response["epic_launch_monitor_id"] == "mon-durable"


def test_epic_gate_unresolvable_launch_raises_with_resume_hint(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.env_contracts import PROVIDER_PROJECT_DIR_ENV_VARS

    for env_name in PROVIDER_PROJECT_DIR_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.delenv("SASE_AGENT_PROJECT_FILE", raising=False)
    plan = write_plan(gate_home, "unclaimable_epic.md", VALID_EPIC_PLAN)
    gate = create_plan_approval_gate(plan, "unclaimable-launch")

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"epic_launch_mode": "detached"},
        )

    assert exc_info.value.code == "epic_launch_failed"
    assert "sase bead work" in str(exc_info.value)
    assert "--yes-to-all" in str(exc_info.value)
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    result = response["option_results"][0]["result"]
    assert result["epic_launch_owner"] == "host"


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
    with (
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(monitor_id="mon-auto"),
        ),
        # This fixture's action data names no project, so archiving cannot
        # run; its failure report is out of scope for the notification
        # assertion below.
        patch("sase._plan_archive_approval.report_plan_archive_failure"),
    ):
        gate = create_plan_approval_gate(
            write_plan(gate_home, f"{expected_kind}-{argument}.md", content),
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
    plan = write_plan(gate_home, "conflict.md", VALID_TALE_PLAN)
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
        write_plan(gate_home, "feedback.md", VALID_TALE_PLAN),
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
        write_plan(gate_home, "race.md", VALID_TALE_PLAN),
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
        write_plan(
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
