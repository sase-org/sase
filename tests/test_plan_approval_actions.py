"""Protocol, gate settlement, and artifact-dir tests for plan approval actions.

Archive side effects live in ``test_plan_approval_actions_archive``.
Headless epic launch lives in ``test_plan_approval_actions_epic``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.notification_gates.service import create_gate
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    execute_plan_approval_response,
    plan_response_json_for_selection,
    resolve_plan_agent_artifacts_dir,
)
from sase.plan_gate import build_plan_approval_gate_spec
from sase.plan_shell.create import plan_gate_shell_block
from sase.xprompt.directive_edit import PromptWaitDirective
from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers fixture)
    write_plan,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (("approve",), {"action": "approve", "commit_plan": False, "run_coder": True}),
        (("commit",), {"action": "approve", "commit_plan": True, "run_coder": False}),
        (
            ("approve", "commit"),
            {"action": "approve", "commit_plan": True, "run_coder": True},
        ),
    ],
)
def test_runner_protocol_is_derived_from_selected_options(
    selected: tuple[str, ...], expected: dict[str, object]
) -> None:
    response, _message = plan_response_json_for_selection(selected, tier="tale")
    assert response == expected


def test_wait_spec_is_emitted_for_coder_and_epic_and_dropped_for_commit() -> None:
    spec = PromptWaitDirective(agents=("sase-s7.2",), beads=("sase-64.3",))
    approve, _ = plan_response_json_for_selection(
        ("approve",), tier="tale", wait_spec=spec
    )
    assert approve["wait_agents"] == ["sase-s7.2"]
    assert approve["wait_beads"] == ["sase-64.3"]

    both, _ = plan_response_json_for_selection(
        ("approve", "commit"), tier="tale", wait_spec=spec
    )
    assert both["wait_agents"] == ["sase-s7.2"]
    assert both["wait_beads"] == ["sase-64.3"]

    commit, _ = plan_response_json_for_selection(
        ("commit",), tier="tale", wait_spec=spec
    )
    assert "wait_agents" not in commit
    assert "wait_beads" not in commit

    epic, _ = plan_response_json_for_selection(
        ("approve",), tier="epic", wait_spec=spec
    )
    assert epic["wait_agents"] == ["sase-s7.2"]
    assert epic["wait_beads"] == ["sase-64.3"]

    empty, _ = plan_response_json_for_selection(
        ("approve",), tier="tale", wait_spec=PromptWaitDirective()
    )
    assert "wait_agents" not in empty
    assert "wait_beads" not in empty


def test_neutral_plan_approval_settles_shell_backed_gate(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_plan(gate_home, "shell-plan.md", VALID_TALE_PLAN)
    spec = build_plan_approval_gate_spec(
        plan,
        "shell-plan",
        auto_enabled=False,
        auto_argument=None,
        agent_name="agent",
        agent_model="gpt-5",
        agent_llm_provider="openai",
        agent_runtime="1m",
        agent_vcs_tag=None,
    )
    spec["shell"] = plan_gate_shell_block("tale")
    gate = create_gate(spec)
    member = gate_home / "member"
    member.mkdir()
    shell_record = SimpleNamespace(artifacts_dir=str(member))
    monkeypatch.setattr(
        "sase.gate_shell.store.find_gate_shell_by_gate_id",
        lambda _project, gate_id: shell_record if gate_id == "shell-plan" else None,
    )
    settled: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.gate_shell.settlement.settle_gate_shell",
        lambda record, **kwargs: settled.append({"record": record, **kwargs}),
    )

    result = execute_plan_approval_response(
        PlanApprovalActionContext(
            id="shell-plan",
            host_files=(str(gate.bundle_path / "plan.md"),),
            host_action_data={
                "bundle_path": str(gate.bundle_path),
                "request_id": "shell-plan",
                "request_kind": "plan",
            },
        ),
        "approve",
        commit_plan=False,
        run_coder=True,
    )

    assert result.message == "Plan approved"
    assert settled == [
        {
            "record": shell_record,
            "gate_state": "answered",
            "reason": "plan approval answered",
        }
    ]
    assert result.response_json["selected_option_ids"] == ["approve"]


def test_resolve_plan_agent_artifacts_dir_from_project_file_and_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    project_dir = tmp_path / "home" / "projects" / "proj"
    artifact_dir = project_dir / "artifacts" / "ace-run" / "20260708120000"
    artifact_dir.mkdir(parents=True)
    project_file = project_dir / "proj.sase"
    project_file.write_text("WORKSPACE_DIR: /workspace/proj\n", encoding="utf-8")

    resolved = resolve_plan_agent_artifacts_dir(
        {
            "agent_project_file": str(project_file),
            "agent_timestamp": "20260708120000",
        }
    )

    assert resolved == str(artifact_dir)
