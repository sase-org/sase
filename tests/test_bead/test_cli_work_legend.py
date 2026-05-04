"""Legend coverage for ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_work import (
    _expected_legend_agent_names,
    _find_live_legend_name_collisions,
)
from sase.bead.project import BeadProject
from sase.bead.work import LegendEpicAssignment, LegendWorkPlan

from .cli_work_helpers import FakeLaunchResult, make_args, seed_legend

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_legend_work_dry_run_never_mutates_or_launches(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legend_id = seed_legend(project_dir, epic_count=2)
    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(make_args(legend_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    assert f"Legend {legend_id}" in out
    assert "2 epic agent(s)" in out
    assert f"%name:{legend_id}.1.0" in out
    assert f"%name:{legend_id}.2.0" in out
    assert f"%w:{legend_id}.1" in out
    assert "%epic" in out
    with BeadProject(project_dir) as proj:
        legend = proj.show(legend_id)
        assert legend.is_ready_to_work is False
        assert proj.get_epic_children(legend_id) == []


def test_legend_work_dry_run_renders_three_epic_chain(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legend_id = seed_legend(project_dir, epic_count=3)
    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(make_args(legend_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    prompt = out.split("--- Multi-prompt (dry run) ---", 1)[1].strip()
    segments = prompt.split("\n---\n")
    assert len(segments) == 3
    for number, segment in enumerate(segments, start=1):
        assert f"%name:{legend_id}.{number}.0" in segment
        assert f"epic #{number} from the legend plan" in segment
        assert "%epic" in segment
    assert f"%w:{legend_id}.1" in segments[1]
    assert f"%w:{legend_id}.2" in segments[2]
    assert "%w:" not in segments[0]
    with BeadProject(project_dir) as proj:
        legend = proj.show(legend_id)
        assert legend.is_ready_to_work is False
        assert proj.get_epic_children(legend_id) == []


def test_legend_work_live_launch_marks_ready_and_does_not_preclaim_children(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legend_id = seed_legend(project_dir, epic_count=3)
    launch_calls: list[str] = []
    captured: dict[str, Any] = {}

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
        launch_calls.append(query)
        captured["query"] = query
        captured["extra_env"] = extra_env
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(legend_id, yes=True))

    assert len(launch_calls) == 1
    query = captured["query"]
    assert query.count("%epic") == 3
    assert query.count("#epic") == 3
    assert query.count("---") == 2
    assert f"%name:{legend_id}.1.0" in query
    assert f"%name:{legend_id}.2.0" in query
    assert f"%name:{legend_id}.3.0" in query
    assert f"%w:{legend_id}.1" in query
    assert f"%w:{legend_id}.2" in query
    with BeadProject(project_dir) as proj:
        legend = proj.show(legend_id)
        assert legend.is_ready_to_work is True
        assert proj.get_epic_children(legend_id) == []

    out = capsys.readouterr().out
    assert "Launched 3 epic agents for legend" in out


def test_legend_work_rolls_back_ready_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legend_id = seed_legend(project_dir)

    def boom(query: str, extra_env: Any = None) -> FakeLaunchResult:
        raise RuntimeError("workspace claim failed")

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", boom)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(legend_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        assert proj.show(legend_id).is_ready_to_work is False
        assert proj.get_epic_children(legend_id) == []

    err = capsys.readouterr().err
    assert "launch failed" in err
    assert "Rolling back is_ready_to_work flag" in err


def test_legend_work_retry_keeps_already_ready_flag_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legend_id = seed_legend(project_dir)

    def boom(query: str, extra_env: Any = None) -> FakeLaunchResult:
        raise RuntimeError("workspace claim failed")

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", boom)
    with BeadProject(project_dir) as proj:
        proj.mark_ready_to_work(legend_id)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(legend_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        assert proj.show(legend_id).is_ready_to_work is True

    captured = capsys.readouterr()
    assert "already ready; retrying epic agent launch" in captured.out
    assert "Rolling back is_ready_to_work flag" not in captured.err


def test_legend_collision_helpers_report_live_planning_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = LegendWorkPlan(
        legend_id="l1",
        plan_file="sdd/legends/202605/roadmap.md",
        assignments=(
            LegendEpicAssignment(epic_number=1, agent_name="l1.1.0", waits_on=()),
            LegendEpicAssignment(
                epic_number=2, agent_name="l1.2.0", waits_on=("l1.1",)
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.agent.names.get_live_agent_name_map",
        lambda: {"l1.2.0": "/tmp/l1.2.0", "other": "/tmp/other"},
    )

    assert _expected_legend_agent_names(plan) == {"l1.1.0", "l1.2.0"}
    assert _find_live_legend_name_collisions(plan) == {"l1.2.0": "/tmp/l1.2.0"}
