"""Accept ``capacity`` on epic plan-gate approval options."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.epic_launch import build_epic_launch_argv
from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    PlanApprovalActionError,
    execute_plan_approval_response,
    plan_response_json,
)
from sase.plan_gate import (
    build_plan_approval_gate_spec,
    execute_plan_gate_command,
    translate_plan_gate_response,
)
from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers the gate_home fixture)
    write_plan,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _run_gate(*argv: str) -> int:
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["gate", *argv])
    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)
    return int(excinfo.value.code or 0)


def _command_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bundle_path: Path,
    option_id: str,
    payload: dict[str, object],
) -> tuple[int, str, str]:
    monkeypatch.chdir(bundle_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = execute_plan_gate_command(option_id)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_execute_plan_gate_command_accepts_explicit_zero_capacity(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "cmd-capacity.md", VALID_EPIC_PLAN),
            "cmd-capacity",
        )
    )

    code, stdout, stderr = _command_result(
        monkeypatch,
        capsys,
        gate.bundle_path,
        "approve",
        {"capacity": 0, "epic_launch_mode": "launch"},
    )

    assert code == 0
    assert stderr == ""
    result = json.loads(stdout)
    assert result["capacity"] == 0
    assert result["action"] == "epic"


def test_execute_plan_gate_command_omits_capacity_when_absent(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "cmd-capacity-omit.md", VALID_EPIC_PLAN),
            "cmd-capacity-omit",
        )
    )

    code, stdout, stderr = _command_result(
        monkeypatch,
        capsys,
        gate.bundle_path,
        "approve",
        {"epic_launch_mode": "launch"},
    )

    assert code == 0
    assert stderr == ""
    result = json.loads(stdout)
    assert "capacity" not in result


def test_execute_plan_gate_command_exits_2_on_an_invalid_capacity(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "cmd-capacity-bad.md", VALID_EPIC_PLAN),
            "cmd-capacity-bad",
        )
    )

    code, stdout, stderr = _command_result(
        monkeypatch,
        capsys,
        gate.bundle_path,
        "approve",
        {"capacity": -1, "epic_launch_mode": "launch"},
    )

    assert code == 2
    assert stdout == ""
    assert "non-negative" in stderr or "capacity" in stderr


def test_execute_plan_gate_command_rejects_boolean_capacity(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "cmd-capacity-bool.md", VALID_EPIC_PLAN),
            "cmd-capacity-bool",
        )
    )

    code, stdout, stderr = _command_result(
        monkeypatch,
        capsys,
        gate.bundle_path,
        "approve",
        {"capacity": True, "epic_launch_mode": "launch"},
    )

    assert code == 2
    assert stdout == ""
    assert "boolean" in stderr.lower() or "non-negative" in stderr


def test_epic_gate_selection_translates_capacity_into_runner_protocol(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "epic-capacity.md", VALID_EPIC_PLAN),
            "epic-capacity",
        )
    )

    with patch(
        "sase.plan_approval_actions.prepare_epic_launch",
        return_value=SimpleNamespace(monitor_id="mon-capacity"),
    ):
        execution = execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"capacity": 3, "epic_launch_mode": "launch"},
        )
    translated = translate_plan_gate_response(gate.bundle_path, execution.response)

    assert translated["capacity"] == 3
    primary = execution.response["option_results"][0]["result"]
    assert primary["capacity"] == 3


def test_tale_gate_selection_rejects_capacity_as_unknown_input(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "tale-capacity.md", VALID_TALE_PLAN),
            "tale-capacity",
        )
    )

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(gate.bundle_path, ["approve"], {"capacity": 3})

    assert exc_info.value.code == "schema_validation_failed"
    assert not gate.response_path.exists()


def test_invalid_capacity_fails_before_the_gate_is_consumed(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "bad-capacity.md", VALID_EPIC_PLAN),
            "bad-capacity",
        )
    )

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"capacity": -1, "epic_launch_mode": "launch"},
        )

    assert exc_info.value.code == "schema_validation_failed"
    assert not gate.response_path.exists()


def test_epic_adapter_forwards_capacity_onto_the_launch_argv(gate_home: Path) -> None:
    from sase.notification_gates.registry import adapter_for_kind

    plan = write_plan(gate_home, "epic-capacity-adapter.md", VALID_EPIC_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "epic-capacity-adapter"))
    response = {
        "selected_option_ids": ["approve"],
        "input": {"epic_launch_mode": "launch", "capacity": 0},
        "option_results": [
            {
                "id": "approve",
                "result": {
                    "action": "epic",
                    "commit_plan": True,
                    "run_coder": True,
                    "epic_launch_owner": "host",
                    "capacity": 0,
                },
            }
        ],
        "source": "tui",
    }

    with (
        patch("sase.plan_approval_actions.run_plan_side_effects"),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(monitor_id="mon-capacity"),
        ) as prepare,
    ):
        adapter_for_kind("epic_plan").apply_side_effects(
            bundle_path=gate.bundle_path,
            response=response,
        )

    assert prepare.call_count == 1
    assert prepare.call_args.kwargs["capacity"] == 0
    argv = build_epic_launch_argv(str(plan), capacity=0)
    assert argv[argv.index("--capacity") + 1] == "0"
    assert response["epic_launch_monitor_id"] == "mon-capacity"


def test_epic_gate_command_path_hands_capacity_to_prepare_epic_launch(
    gate_home: Path,
) -> None:
    plan = write_plan(gate_home, "epic-cmd-capacity.md", VALID_EPIC_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "epic-cmd-capacity"))

    with patch(
        "sase.plan_approval_actions.prepare_epic_launch",
        return_value=SimpleNamespace(monitor_id="mon-cmd-capacity"),
    ) as prepare:
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"capacity": 3, "epic_launch_mode": "launch"},
        )

    assert prepare.call_count == 1
    assert prepare.call_args.kwargs["capacity"] == 3
    argv = build_epic_launch_argv(
        str(plan), capacity=prepare.call_args.kwargs["capacity"]
    )
    assert "--capacity" in argv
    assert argv[argv.index("--capacity") + 1] == "3"


def test_skip_mode_does_not_launch_even_with_capacity(gate_home: Path) -> None:
    plan = write_plan(gate_home, "epic-skip-capacity.md", VALID_EPIC_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "epic-skip-capacity"))

    with patch("sase.plan_approval_actions.prepare_epic_launch") as prepare:
        execution = execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"capacity": 3, "epic_launch_mode": "skip"},
        )

    prepare.assert_not_called()
    assert execution.response["option_results"][0]["result"]["capacity"] == 3


def test_reject_does_not_launch_or_record_capacity(gate_home: Path) -> None:
    plan = write_plan(gate_home, "epic-reject-capacity.md", VALID_EPIC_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "epic-reject-capacity"))

    with patch("sase.plan_approval_actions.prepare_epic_launch") as prepare:
        execution = execute_gate_selection(gate.bundle_path, ["reject"], {})

    prepare.assert_not_called()
    result = execution.response["option_results"][0]["result"]
    assert result["action"] == "reject"
    assert "capacity" not in result


def test_neutral_approval_puts_capacity_in_shared_input(gate_home: Path) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "neutral-capacity.md", VALID_EPIC_PLAN),
            "neutral-capacity",
        )
    )
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    from sase.plan_gate import plan_context_from_envelope

    with patch(
        "sase.plan_approval_actions.prepare_epic_launch",
        return_value=SimpleNamespace(monitor_id="mon-neutral-capacity"),
    ):
        result = execute_plan_approval_response(
            plan_context_from_envelope(gate.bundle_path, envelope),
            "epic",
            capacity=0,
        )

    assert result.response_json["input"]["capacity"] == 0
    translated = translate_plan_gate_response(gate.bundle_path, result.response_json)
    assert translated["capacity"] == 0


def test_invalid_capacity_is_rejected_before_the_gate_is_consumed(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "reject-capacity.md", VALID_EPIC_PLAN),
            "reject-capacity",
        )
    )
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    from sase.plan_gate import plan_context_from_envelope

    with pytest.raises(PlanApprovalActionError) as exc_info:
        execute_plan_approval_response(
            plan_context_from_envelope(gate.bundle_path, envelope),
            "epic",
            capacity=-1,
        )

    assert exc_info.value.code == "invalid_request"
    assert exc_info.value.target == "capacity"
    assert not gate.response_path.exists()


def test_legacy_approval_emits_capacity_field(gate_home: Path) -> None:
    plan = write_plan(gate_home, "legacy-capacity.md", VALID_EPIC_PLAN)
    response_dir = gate_home / "legacy-capacity-approval"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}\n", encoding="utf-8")

    with (
        patch(
            "sase.plan_approval_actions.can_claim_epic_launch",
            return_value=True,
        ),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(monitor_id="mon-legacy-capacity"),
        ),
    ):
        result = execute_plan_approval_response(
            PlanApprovalActionContext(
                id="legacy-capacity",
                host_files=(str(plan),),
                host_action_data={"response_dir": str(response_dir)},
            ),
            "epic",
            capacity=3,
        )

    assert result.response_json["capacity"] == 3
    assert result.response_json["action"] == "epic"


def test_plan_response_json_drops_capacity_on_non_epic() -> None:
    result, _message = plan_response_json(
        "commit",
        feedback=None,
        commit_plan=None,
        run_coder=None,
        coder_prompt=None,
        coder_model=None,
        capacity=3,
    )

    assert "capacity" not in result


def test_gate_answer_set_coerces_capacity_integer(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "set-capacity.md", VALID_EPIC_PLAN),
            "set-capacity",
        )
    )

    with patch(
        "sase.plan_approval_actions.prepare_epic_launch",
        return_value=SimpleNamespace(monitor_id="mon-set-capacity"),
    ):
        code = _run_gate(
            "answer",
            "-i",
            "set-capacity",
            "-k",
            "epic_plan",
            "-o",
            "approve",
            "-s",
            "capacity=3",
            "-s",
            "epic_launch_mode=launch",
        )

    capsys.readouterr()
    assert code == 0
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["option_inputs"]["approve"]["capacity"] == 3
    assert response["option_results"][0]["result"]["capacity"] == 3


def test_pre_upgrade_plan_gate_rejects_capacity_set_with_ordinary_error(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = build_plan_approval_gate_spec(
        write_plan(gate_home, "pre-upgrade.md", VALID_EPIC_PLAN),
        "pre-upgrade-capacity",
    )
    for option in spec["options"]:
        properties = option.get("input_schema", {}).get("properties")
        if isinstance(properties, dict):
            properties.pop("capacity", None)
    gate = create_gate(spec)

    code = _run_gate(
        "answer",
        "-i",
        "pre-upgrade-capacity",
        "-k",
        "epic_plan",
        "-o",
        "approve",
        "-s",
        "capacity=3",
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "no selected option accepts that input" in err
    assert not gate.response_path.exists()
