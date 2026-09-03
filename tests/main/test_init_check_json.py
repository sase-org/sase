"""Structured ``sase init --check --json`` payload tests."""

from __future__ import annotations

import argparse
from io import StringIO
import json
from pathlib import Path

import pytest

from sase.main.init_onboarding import run_init_onboarding, run_init_onboarding_all
from sase.main.init_plan import INIT_CHECK_JSON_SCHEMA_VERSION, InitAction, InitPlan
from sase.main.init_project_scope import InitProjectInventory, InitProjectTarget
from sase.main.init_registry import InitCommandSpec
from tests.main.init_onboarding_helpers import _args, _reject_prompt


def _target(tmp_path: Path, name: str) -> InitProjectTarget:
    workspace = tmp_path / name
    workspace.mkdir()
    project_file = tmp_path / f"{name}.sase"
    project_file.write_text("NAME: test\n", encoding="utf-8")
    return InitProjectTarget(
        project_name=name,
        display_name=name.title(),
        project_file=project_file,
        workspace_dir=workspace,
    )


def _spec(plan: InitPlan) -> InitCommandSpec:
    return InitCommandSpec(
        name=plan.command,
        label=plan.label,
        plan=lambda args: plan,
        run=lambda args: 0,
    )


def _stub_cwd_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.main import init_onboarding

    monkeypatch.setattr(
        init_onboarding,
        "cwd_init_project_target",
        lambda: InitProjectTarget(
            project_name="cwd",
            display_name="cwd",
            project_file=Path("."),
            workspace_dir=Path("."),
        ),
    )


def test_json_check_current_project(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_cwd_target(monkeypatch)
    plan = InitPlan(command="memory", label="Memory", summary="current")
    exit_code = run_init_onboarding(
        _args(check=True, json_output=True),
        specs=(_spec(plan),),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == INIT_CHECK_JSON_SCHEMA_VERSION
    assert payload["status"] == "current"
    planner = payload["projects"][0]["planners"][0]
    assert planner["name"] == "memory"
    assert planner["has_changes"] is False
    assert planner["runnable"] is True
    assert planner["requires_tty"] is False


def test_json_check_distinguishes_drift_from_blocked(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_cwd_target(monkeypatch)
    drifted = InitPlan(
        command="memory",
        label="Memory",
        summary="update memory",
        actions=(
            InitAction(Path("AGENTS.md"), "update", "changed", new_content="x\n"),
        ),
    )
    blocked = InitPlan(
        command="config",
        label="Config",
        summary="held",
        blockers=("cannot repair identity",),
        requires_tty=True,
    )

    drift_code = run_init_onboarding(
        _args(check=True, json_output=True),
        specs=(_spec(drifted),),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )
    drift_payload = json.loads(capsys.readouterr().out)
    blocked_code = run_init_onboarding(
        _args(check=True, json_output=True),
        specs=(_spec(blocked),),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )
    blocked_payload = json.loads(capsys.readouterr().out)

    assert drift_code == 1
    assert blocked_code == 1
    assert drift_payload["status"] == "drift"
    assert blocked_payload["status"] == "blocked"
    assert drift_payload["projects"][0]["status"] == "needs_attention"
    assert blocked_payload["projects"][0]["status"] == "failed"
    assert drift_payload["projects"][0]["planners"][0]["actions"][0]["new_content"] == (
        "x\n"
    )
    assert blocked_payload["projects"][0]["planners"][0]["requires_tty"] is True
    assert blocked_payload["projects"][0]["planners"][0]["runnable"] is False


def test_json_check_named_projects_emit_one_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    alpha = _target(tmp_path, "alpha")
    beta = _target(tmp_path, "beta")
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory((alpha, beta)),
    )

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        name = Path.cwd().name
        if name == "beta":
            return InitPlan(
                command="memory",
                label="Memory",
                summary="update",
                actions=(InitAction(Path("AGENTS.md"), "update"),),
            )
        return InitPlan(command="memory", label="Memory", summary="current")

    spec = InitCommandSpec(name="memory", label="Memory", plan=plan, run=lambda a: 0)
    exit_code = run_init_onboarding_all(
        _args(check=True, json_output=True, project=["alpha", "beta"]),
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["schema_version"] == INIT_CHECK_JSON_SCHEMA_VERSION
    assert payload["status"] == "drift"
    assert [project["name"] for project in payload["projects"]] == ["alpha", "beta"]
    assert payload["projects"][0]["status"] == "current"
    assert payload["projects"][1]["status"] == "needs_attention"
    assert "SASE initialization check" not in captured
    assert "Initialization summary" not in captured


def test_json_check_does_not_truncate_actions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.doctor.checks_config_common import MAX_DETAIL_ROWS

    _stub_cwd_target(monkeypatch)
    actions = tuple(
        InitAction(Path(f"file-{index}.md"), "update", new_content=f"{index}\n")
        for index in range(MAX_DETAIL_ROWS + 5)
    )
    plan = InitPlan(
        command="memory",
        label="Memory",
        summary="many updates",
        actions=actions,
    )
    exit_code = run_init_onboarding(
        _args(check=True, json_output=True),
        specs=(_spec(plan),),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    payload = json.loads(capsys.readouterr().out)
    planner = payload["projects"][0]["planners"][0]
    assert exit_code == 1
    assert payload["status"] == "drift"
    assert len(planner["actions"]) == MAX_DETAIL_ROWS + 5
    assert planner["action_count"] == MAX_DETAIL_ROWS + 5
    assert "truncated" not in planner
    assert planner["actions"][-1]["new_content"] == f"{MAX_DETAIL_ROWS + 4}\n"
