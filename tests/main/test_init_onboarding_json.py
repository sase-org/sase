"""JSON check-payload tests for ``sase init --check --json``."""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

import pytest

from sase.main import init_onboarding
from sase.main.init_onboarding import run_init_onboarding, run_init_onboarding_all
from sase.main.init_plan import INIT_CHECK_JSON_SCHEMA_VERSION, InitAction, InitPlan
from sase.main.init_project_scope import InitProjectInventory
from sase.main.init_registry import InitCommandSpec
from tests.main.init_onboarding_helpers import (
    _args,
    _changed_action,
    _plan,
    _reject_prompt,
    _spec,
)
from tests.main.test_init_onboarding_all import _target


def _payload(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.out.strip().startswith("{")
    return json.loads(captured.out)


def test_json_current_project_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.main.init_check_json.resolve_cwd_init_project_identity",
        lambda: ("demo", "Demo"),
    )
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory", summary="memory current"), calls),
        _spec("repo", _plan("repo", summary="repos current"), calls),
    )

    exit_code = run_init_onboarding(
        _args(check=True, json=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == []
    payload = _payload(capsys)
    assert payload["schema_version"] == INIT_CHECK_JSON_SCHEMA_VERSION
    assert payload["status"] == "current"
    projects = payload["projects"]
    assert isinstance(projects, list)
    assert len(projects) == 1
    project = projects[0]
    assert isinstance(project, dict)
    assert project["name"] == "demo"
    assert project["display_name"] == "Demo"
    assert project["status"] == "current"
    assert project["unavailable_reason"] is None
    planners = project["planners"]
    assert isinstance(planners, list)
    assert [planner["name"] for planner in planners] == ["memory", "repo"]
    assert all(planner["has_changes"] is False for planner in planners)
    assert all(planner["runnable"] is True for planner in planners)
    assert all(planner["requires_tty"] is False for planner in planners)


def test_json_drift_includes_action_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.main.init_check_json.resolve_cwd_init_project_identity",
        lambda: ("demo", "demo"),
    )
    plan = InitPlan(
        command="memory",
        label="Memory",
        summary="create memory files",
        actions=(
            InitAction(
                Path("memory/sase.md"),
                "create",
                "project memory",
                new_content="# SASE\n",
            ),
        ),
    )
    specs = (_spec("memory", plan, []),)

    exit_code = run_init_onboarding(
        _args(check=True, json=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    payload = _payload(capsys)
    assert payload["status"] == "drift"
    project = payload["projects"][0]
    assert isinstance(project, dict)
    assert project["status"] == "needs_attention"
    planner = project["planners"][0]
    assert planner["has_changes"] is True
    assert planner["runnable"] is True
    assert planner["actions"][0]["new_content"] == "# SASE\n"
    assert planner["action_count"] == 1
    assert "actions_truncated" not in planner


def test_json_blocked_is_distinct_from_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.main.init_check_json.resolve_cwd_init_project_identity",
        lambda: ("demo", "demo"),
    )
    specs = (
        _spec(
            "memory",
            _plan(
                "memory",
                actions=(_changed_action(),),
                summary="update generated memory",
                blockers=("invalid sibling repo config",),
            ),
            [],
        ),
    )

    exit_code = run_init_onboarding(
        _args(check=True, json=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    payload = _payload(capsys)
    assert payload["status"] == "blocked"
    project = payload["projects"][0]
    assert isinstance(project, dict)
    assert project["status"] == "failed"
    planner = project["planners"][0]
    assert planner["runnable"] is False
    assert planner["blockers"] == ["invalid sibling repo config"]
    assert planner["has_changes"] is True


def test_json_requires_tty_on_classified_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.main.init_check_json.resolve_cwd_init_project_identity",
        lambda: ("demo", "demo"),
    )
    specs = (
        _spec(
            "config",
            _plan(
                "config",
                actions=(_changed_action(".sase/machine_name"),),
                summary="choose a machine identity",
                requires_tty=True,
            ),
            [],
        ),
    )

    exit_code = run_init_onboarding(
        _args(check=True, json=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    payload = _payload(capsys)
    planner = payload["projects"][0]["planners"][0]
    assert planner["requires_tty"] is True
    assert planner["runnable"] is True


def test_json_batch_named_projects_and_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    alpha = _target(tmp_path, "alpha", display_name="Alpha")
    missing = _target(
        tmp_path,
        "missing",
        display_name="Missing",
        unavailable="primary workspace is unavailable: /gone",
    )
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory((alpha, missing)),
    )

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        return InitPlan(
            command="memory",
            label="Memory",
            summary="update memory",
            actions=(InitAction(Path("AGENTS.md"), "update", "changed"),),
        )

    spec = InitCommandSpec(name="memory", label="Memory", plan=plan, run=lambda a: 0)

    exit_code = run_init_onboarding_all(
        _args(check=True, json=True, project=["alpha", "missing"]),
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    payload = _payload(capsys)
    assert payload["status"] == "blocked"
    projects = {row["name"]: row for row in payload["projects"]}
    assert projects["alpha"]["status"] == "needs_attention"
    assert projects["alpha"]["planners"][0]["has_changes"] is True
    assert projects["missing"]["status"] == "failed"
    assert projects["missing"]["unavailable_reason"] == (
        "primary workspace is unavailable: /gone"
    )
    assert projects["missing"]["planners"] == []
