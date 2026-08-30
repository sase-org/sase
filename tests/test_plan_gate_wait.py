"""Accept ``wait`` on tale and epic plan-gate approval options."""

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
from sase.llm_provider._plan_utils import plan_approval_result_from_gate_response
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
from sase.xprompt.directive_edit import PromptWaitDirective
from sase.xprompt.directives import extract_prompt_directives
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import run_plan_approval
from tests._axe_run_agent_exec_plan_helpers import patched_plan_deps
from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers the gate_home fixture)
    write_plan,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN

_WAIT_SPEC = "sase-s7.2,bead=sase-64.3"
_WAIT_DIRECTIVE = PromptWaitDirective(agents=("sase-s7.2",), beads=("sase-64.3",))


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


def test_execute_plan_gate_command_accepts_a_valid_wait_spec(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "cmd-wait.md", VALID_TALE_PLAN),
            "cmd-wait",
        )
    )

    code, stdout, stderr = _command_result(
        monkeypatch, capsys, gate.bundle_path, "approve", {"wait": _WAIT_SPEC}
    )

    assert code == 0
    assert stderr == ""
    result = json.loads(stdout)
    assert result["wait_agents"] == ["sase-s7.2"]
    assert result["wait_beads"] == ["sase-64.3"]


def test_execute_plan_gate_command_exits_2_on_an_invalid_wait_spec(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "cmd-wait-bad.md", VALID_TALE_PLAN),
            "cmd-wait-bad",
        )
    )

    code, stdout, stderr = _command_result(
        monkeypatch, capsys, gate.bundle_path, "approve", {"wait": "time=5m"}
    )

    assert code == 2
    assert stdout == ""
    assert "time=" in stderr


def test_tale_gate_selection_translates_wait_into_runner_protocol(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "tale-wait.md", VALID_TALE_PLAN),
            "tale-wait",
        )
    )

    execution = execute_gate_selection(
        gate.bundle_path, ["approve"], {"wait": _WAIT_SPEC}
    )
    translated = translate_plan_gate_response(gate.bundle_path, execution.response)

    assert translated["wait_agents"] == ["sase-s7.2"]
    assert translated["wait_beads"] == ["sase-64.3"]
    primary = execution.response["option_results"][0]["result"]
    assert primary["wait_agents"] == ["sase-s7.2"]
    assert primary["wait_beads"] == ["sase-64.3"]


def test_commit_only_selection_drops_wait_from_the_translated_response(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "commit-wait.md", VALID_TALE_PLAN),
            "commit-wait",
        )
    )

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        return_value=str(gate_home / "saved-commit-wait.md"),
    ):
        execution = execute_gate_selection(
            gate.bundle_path, ["commit"], {"wait": _WAIT_SPEC}
        )
    translated = translate_plan_gate_response(gate.bundle_path, execution.response)

    assert "wait_agents" not in translated
    assert "wait_beads" not in translated
    assert "wait_agents" not in execution.response["option_results"][0]["result"]


def test_invalid_wait_fails_the_option_command(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "bad-wait.md", VALID_TALE_PLAN),
            "bad-wait",
        )
    )

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(gate.bundle_path, ["approve"], {"wait": "time=5m"})

    assert exc_info.value.code == "command_failed"
    assert "time=" in str(exc_info.value)
    assert not gate.response_path.exists()


def test_epic_adapter_forwards_wait_onto_the_launch_argv(gate_home: Path) -> None:
    from sase.notification_gates.registry import adapter_for_kind

    plan = write_plan(gate_home, "epic-wait.md", VALID_EPIC_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "epic-wait"))
    response = {
        "selected_option_ids": ["approve"],
        "input": {"epic_launch_mode": "launch", "wait": _WAIT_SPEC},
        "option_results": [
            {
                "id": "approve",
                "result": {
                    "action": "epic",
                    "commit_plan": True,
                    "run_coder": True,
                    "epic_launch_owner": "host",
                    "wait_agents": ["sase-s7.2"],
                    "wait_beads": ["sase-64.3"],
                },
            }
        ],
        "source": "tui",
    }

    with (
        patch("sase.plan_approval_actions.run_plan_side_effects"),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(monitor_id="mon-wait"),
        ) as prepare,
    ):
        adapter_for_kind("epic_plan").apply_side_effects(
            bundle_path=gate.bundle_path,
            response=response,
        )

    assert prepare.call_args.kwargs["wait_spec"] == _WAIT_DIRECTIVE
    argv = build_epic_launch_argv(str(plan), wait_spec=_WAIT_DIRECTIVE)
    assert argv[argv.index("--wait") + 1] == _WAIT_SPEC
    assert response["epic_launch_monitor_id"] == "mon-wait"


def test_epic_gate_command_path_hands_wait_to_prepare_epic_launch(
    gate_home: Path,
) -> None:
    plan = write_plan(gate_home, "epic-cmd-wait.md", VALID_EPIC_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "epic-cmd-wait"))

    with patch(
        "sase.plan_approval_actions.prepare_epic_launch",
        return_value=SimpleNamespace(monitor_id="mon-cmd-wait"),
    ) as prepare:
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"wait": _WAIT_SPEC, "epic_launch_mode": "launch"},
        )

    assert prepare.call_args.kwargs["wait_spec"] == _WAIT_DIRECTIVE
    argv = build_epic_launch_argv(
        str(plan), wait_spec=prepare.call_args.kwargs["wait_spec"]
    )
    assert "--wait" in argv
    assert argv[argv.index("--wait") + 1] == _WAIT_SPEC


def test_neutral_approval_puts_raw_wait_in_shared_input(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "neutral-wait.md", VALID_TALE_PLAN),
            "neutral-wait",
        )
    )
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    from sase.plan_gate import plan_context_from_envelope

    result = execute_plan_approval_response(
        plan_context_from_envelope(gate.bundle_path, envelope),
        "approve",
        commit_plan=False,
        run_coder=True,
        wait=_WAIT_SPEC,
    )

    assert result.response_json["input"]["wait"] == _WAIT_SPEC
    translated = translate_plan_gate_response(gate.bundle_path, result.response_json)
    assert translated["wait_agents"] == ["sase-s7.2"]
    assert translated["wait_beads"] == ["sase-64.3"]


def test_invalid_wait_is_rejected_before_the_gate_is_consumed(
    gate_home: Path,
) -> None:
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "reject-wait.md", VALID_TALE_PLAN),
            "reject-wait",
        )
    )
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    from sase.plan_gate import plan_context_from_envelope

    with pytest.raises(PlanApprovalActionError) as exc_info:
        execute_plan_approval_response(
            plan_context_from_envelope(gate.bundle_path, envelope),
            "approve",
            wait="time=5m",
        )

    assert exc_info.value.code == "invalid_request"
    assert exc_info.value.target == "wait"
    assert "time=" in str(exc_info.value)
    assert not gate.response_path.exists()


def test_legacy_approval_emits_parsed_wait_fields(gate_home: Path) -> None:
    plan = write_plan(gate_home, "legacy-wait.md", VALID_TALE_PLAN)
    response_dir = gate_home / "legacy-wait-approval"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}\n", encoding="utf-8")

    result = execute_plan_approval_response(
        PlanApprovalActionContext(
            id="legacy-wait",
            host_files=(str(plan),),
            host_action_data={"response_dir": str(response_dir)},
        ),
        "approve",
        wait=_WAIT_SPEC,
    )

    assert result.response_json["wait_agents"] == ["sase-s7.2"]
    assert result.response_json["wait_beads"] == ["sase-64.3"]


def test_plan_response_json_drops_wait_on_commit_only() -> None:
    result, _message = plan_response_json(
        "commit",
        feedback=None,
        commit_plan=None,
        run_coder=None,
        coder_prompt=None,
        coder_model=None,
        wait_spec=_WAIT_DIRECTIVE,
    )

    assert "wait_agents" not in result
    assert "wait_beads" not in result


def test_pre_upgrade_plan_gate_rejects_wait_set_with_ordinary_error(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = build_plan_approval_gate_spec(
        write_plan(gate_home, "pre-upgrade.md", VALID_TALE_PLAN),
        "pre-upgrade-wait",
    )
    for option in spec["options"]:
        properties = option.get("input_schema", {}).get("properties")
        if isinstance(properties, dict):
            properties.pop("wait", None)
    gate = create_gate(spec)

    code = _run_gate(
        "answer",
        "-i",
        "pre-upgrade-wait",
        "-k",
        "plan",
        "-o",
        "approve",
        "-s",
        f"wait={_WAIT_SPEC}",
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "no selected option accepts that input" in err
    assert "coder_prompt" in err
    assert not gate.response_path.exists()


def test_tale_gate_wait_stamps_coder_successor_prompt(gate_home: Path) -> None:
    plan = write_plan(gate_home, "coder-wait.md", VALID_TALE_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "coder-wait"))
    execution = execute_gate_selection(
        gate.bundle_path, ["approve"], {"wait": _WAIT_SPEC}
    )
    approval = plan_approval_result_from_gate_response(
        gate.bundle_path, execution.response
    )
    assert approval is not None
    assert approval.wait_agents == ("sase-s7.2",)
    assert approval.wait_beads == ("sase-64.3",)

    coder_root = gate_home / "coder-workspace"
    coder_root.mkdir()
    with patched_plan_deps():
        _, state, _ = run_plan_approval(
            coder_root,
            approval=approval,
            agent_model="opus",
            agent_llm_provider="claude",
        )

    assert "%wait(sase-s7.2)" in state.current_prompt
    assert "%wait(bead=sase-64.3)" in state.current_prompt
    _, directives = extract_prompt_directives(state.current_prompt)
    assert directives.wait == ["sase-s7.2"]
    assert directives.wait_beads == ["sase-64.3"]
    assert "%model:@small" in state.current_prompt
    assert "#gh:sase" in state.current_prompt
    assert f"@{approval.plan_file}" in state.current_prompt
