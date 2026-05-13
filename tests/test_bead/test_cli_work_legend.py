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
from sase.bead.work import _LegendEpicAssignment, LegendWorkPlan

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
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: pytest.fail("dry run must not commit"),
    )

    bead_cli.handle_bead_work(make_args(legend_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    assert f"Legend {legend_id}" in out
    assert "2 epic agent(s) plus 1 land agent" in out
    assert f"%name:!{legend_id}.1.0" in out
    assert f"%name:!{legend_id}.2.0" in out
    assert f"%name:!{legend_id}" in out
    assert out.count(f"%group:{legend_id}") == 3
    assert f"%w:{legend_id}.1" in out
    assert f"#bd/land_legend:{legend_id}" in out
    assert "%epic" in out
    prompt = out.split("--- Multi-prompt (dry run) ---", 1)[1].strip()
    segments = prompt.split("\n---\n")
    assert len(segments) == 3
    for segment in segments[:2]:
        assert f"%group:{legend_id}" in segment
        assert "%epic" in segment
        assert "%approve" not in segment
    assert f"%group:{legend_id}" in segments[2]
    assert "%epic" not in segments[2]
    assert "%approve" in segments[2]
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
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(legend_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    prompt = out.split("--- Multi-prompt (dry run) ---", 1)[1].strip()
    segments = prompt.split("\n---\n")
    assert len(segments) == 4
    for number, segment in enumerate(segments[:3], start=1):
        assert f"%name:!{legend_id}.{number}.0" in segment
        assert f"%group:{legend_id}" in segment
        assert f"epic #{number} from the legend plan" in segment
        assert "%epic" in segment
        assert "%approve" not in segment
    assert f"%w:{legend_id}.1" in segments[1]
    assert f"%w:{legend_id}.2" in segments[2]
    assert "%w:" not in segments[0]
    assert f"%name:!{legend_id}" in segments[3]
    assert f"%group:{legend_id}" in segments[3]
    assert f"%w:{legend_id}.3" in segments[3]
    assert f"#bd/land_legend:{legend_id}" in segments[3]
    assert "%epic" not in segments[3]
    assert "%approve" in segments[3]
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
    commit_calls: list[tuple[Path, str, str, str]] = []

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        launch_calls.append(query)
        captured["query"] = query
        captured["extra_env"] = extra_env
        captured["segment_extra_env"] = segment_extra_env
        return FakeLaunchResult()

    def fake_commit(
        beads_dir: Path,
        bead_id: str,
        title: str,
        *,
        kind: str,
    ) -> bool:
        commit_calls.append((beads_dir, bead_id, title, kind))
        return True

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr("sase.bead.sync.commit_bead_work_launch", fake_commit)

    bead_cli.handle_bead_work(make_args(legend_id, yes=True))

    assert len(launch_calls) == 1
    query = captured["query"]
    assert query.count("%epic") == 3
    assert query.count("%approve") == 1
    assert query.count(f"%group:{legend_id}") == 4
    assert query.count("#epic") == 3
    assert query.count("---") == 3
    assert f"%name:{legend_id}.1.0" in query
    assert f"%name:{legend_id}.2.0" in query
    assert f"%name:{legend_id}.3.0" in query
    assert f"%name:{legend_id}" in query
    assert f"%w:{legend_id}.1" in query
    assert f"%w:{legend_id}.2" in query
    assert f"%w:{legend_id}.3" in query
    assert f"#bd/land_legend:{legend_id}" in query
    assert captured["extra_env"] is None
    assert captured["segment_extra_env"] == tuple(
        {"SASE_BEAD_ID": legend_id} for _ in range(4)
    )
    assert commit_calls == [
        (project_dir / "sdd/beads", legend_id, "Legend roadmap", "legend")
    ]
    with BeadProject(project_dir) as proj:
        legend = proj.show(legend_id)
        assert legend.is_ready_to_work is True
        assert proj.get_epic_children(legend_id) == []

    out = capsys.readouterr().out
    assert "Launched 4 agents for legend" in out
    assert "3 epic-planning, 1 land" in out


def test_legend_work_rolls_back_ready_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legend_id = seed_legend(project_dir)

    def boom(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        raise RuntimeError("workspace claim failed")

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", boom)
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: pytest.fail("failed launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(legend_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        assert proj.show(legend_id).is_ready_to_work is False
        assert proj.get_epic_children(legend_id) == []

    err = capsys.readouterr().err
    assert "launch failed" in err
    assert "Rolling back is_ready_to_work flag" in err


def test_legend_work_commit_failure_reports_after_successful_launch(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import BeadWorkLaunchCommitError

    legend_id = seed_legend(project_dir)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )

    def boom(*args: Any, **kwargs: Any) -> bool:
        raise BeadWorkLaunchCommitError("git commit failed")

    monkeypatch.setattr("sase.bead.sync.commit_bead_work_launch", boom)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(legend_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        legend = proj.show(legend_id)
        assert legend.is_ready_to_work is True
        assert proj.get_epic_children(legend_id) == []

    captured = capsys.readouterr()
    assert "Launched" in captured.out
    assert (
        f"agents launched for legend {legend_id}, but committing "
        "sdd/beads/issues.jsonl failed: git commit failed"
    ) in captured.err


def test_legend_work_retry_keeps_already_ready_flag_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legend_id = seed_legend(project_dir)

    def boom(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
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


def test_legend_work_stale_owner_round_trip_wipes_and_rewrites(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale name registry entries are wiped, and the launcher sees a rewritten prompt."""
    legend_id = seed_legend(project_dir, epic_count=2)
    captured: dict[str, Any] = {}
    wiped: list[list[str]] = []

    def fake_wipe(names: list[str]) -> None:
        wiped.append(list(names))

    monkeypatch.setattr(
        "sase.agent.launch_validation.wipe_names_for_forced_reuse",
        fake_wipe,
    )

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(legend_id, yes=True))

    query = captured["query"]
    # Launcher receives the rewritten prompt: ordinary %name:<n> (no '!').
    assert "%name:!" not in query
    assert f"%name:{legend_id}.1.0\n" in query
    assert f"%name:{legend_id}.2.0\n" in query
    assert f"%name:{legend_id}\n" in query

    assert len(wiped) == 1
    assert set(wiped[0]) == {
        f"{legend_id}.1.0",
        f"{legend_id}.2.0",
        legend_id,
    }


def test_legend_collision_helpers_report_live_planning_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = LegendWorkPlan(
        legend_id="l1",
        plan_file="sdd/legends/202605/roadmap.md",
        assignments=(
            _LegendEpicAssignment(epic_number=1, agent_name="l1.1.0", waits_on=()),
            _LegendEpicAssignment(
                epic_number=2, agent_name="l1.2.0", waits_on=("l1.1",)
            ),
        ),
        land_agent_name="l1",
        land_waits_on=("l1.2",),
    )
    monkeypatch.setattr(
        "sase.agent.names.get_live_agent_name_subset",
        lambda expected: {
            name: path
            for name, path in {
                "l1.2.0": "/tmp/l1.2.0",
                "l1": "/tmp/l1",
                "other": "/tmp/other",
            }.items()
            if name in expected
        },
    )

    assert _expected_legend_agent_names(plan) == {"l1.1.0", "l1.2.0", "l1"}
    assert _find_live_legend_name_collisions(plan) == {
        "l1.2.0": "/tmp/l1.2.0",
        "l1": "/tmp/l1",
    }
