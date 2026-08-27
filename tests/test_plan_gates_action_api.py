"""Plan approval action-API preset, alias, and legacy-response coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.service import create_gate
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    execute_plan_approval_response,
)
from sase.plan_gate import (
    build_plan_approval_gate_spec,
    plan_context_from_envelope,
    translate_plan_gate_response,
)

from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers the gate_home fixture)
    plan_host_archive_stub,  # noqa: F401
    write_plan,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.fixture(autouse=True)
def _stub_host_archive(stub_host_plan_archive: Path) -> Path:
    return stub_host_plan_archive


def test_plan_action_api_executes_selected_approval_options(
    gate_home: Path,
    stub_host_plan_archive: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "action-api.md", VALID_TALE_PLAN),
            "action-api",
        )
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
                "plan_archive_owner": "host",
                "plan_archive_state": "archived",
                "plan_archive_protocol": "host_v2",
                "plan_archive_ref": "plan:202608/host-archived-plan.md",
                "saved_plan_path": str(stub_host_plan_archive),
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
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "action-tale.md", VALID_TALE_PLAN),
            "action-tale",
        )
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
    stub_host_plan_archive: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "action-commit.md", VALID_TALE_PLAN),
            "action-commit",
        )
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
        "plan_archive_owner": "host",
        "plan_archive_state": "archived",
        "plan_archive_protocol": "host_v2",
        "plan_archive_ref": "plan:202608/host-archived-plan.md",
        "saved_plan_path": str(stub_host_plan_archive),
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
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, f"preset-{choice}.md", VALID_TALE_PLAN),
            f"preset-{choice}",
        )
    )

    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    execution = execute_plan_approval_response(
        plan_context_from_envelope(gate.bundle_path, envelope), choice
    )
    translated = translate_plan_gate_response(gate.bundle_path, execution.response_json)

    assert translated["commit_plan"] is expected_commit
    assert translated["run_coder"] is expected_run


def test_legacy_plan_approval_remains_answerable(gate_home: Path) -> None:
    plan = write_plan(gate_home, "legacy.md", VALID_TALE_PLAN)
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
