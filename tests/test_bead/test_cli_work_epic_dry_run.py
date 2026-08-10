"""Dry-run rendering tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, PhaseSize, Status
from sase.bead.project import BeadProject

from .cli_work_helpers import (
    FakeLaunchResult,
    bead_wait_lines,
    epic_clan_declaration,
    make_args,
    seed_diamond,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_dry_run_never_mutates_or_launches(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    launch_calls: list[str] = []

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        launch_calls.append(query)
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: pytest.fail("dry run must not commit"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    out = capsys.readouterr().out
    assert "Multi-prompt (dry run)" in out
    assert f"land agent ({epic_id}.land)" in out
    assert f"Clan: {epic_id} · Tribe: @epic" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert out.count(epic_clan_declaration(epic_id)) == 1
    assert "%family" not in out
    assert "%group:" not in out


def test_work_dry_run_matches_confirmed_launch_before_force_reuse_rewrite(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agent.launch_validation import rewrite_force_reuse_name_directives
    from sase.agent.names import AgentNameWipeResult

    epic_id, _ = seed_diamond(project_dir)

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))
    dry_output = capsys.readouterr().out
    dry_query = dry_output.split("--- Multi-prompt (dry run) ---\n", 1)[1].rstrip()

    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: AgentNameWipeResult(target_name=name, found=False),
    )
    launched_queries: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched_queries.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert launched_queries == [rewrite_force_reuse_name_directives(dry_query)]
    assert bead_wait_lines(launched_queries[0]) == bead_wait_lines(dry_query)


def test_work_dry_run_renders_model_directives(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Models epic", IssueType.PLAN, model="claude/opus")
        p1 = proj.create(
            "P1",
            IssueType.PHASE,
            parent_id=epic.id,
            model="codex/gpt-5.6-sol",
        )
        p2 = proj.create("P2", IssueType.PHASE, parent_id=epic.id)
    epic_id, p1_id, p2_id = epic.id, p1.id, p2.id

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    out = capsys.readouterr().out
    membership = epic_clan_declaration(epic_id)
    assert (
        f"%id(!{p1_id}, bead={p1_id})\n{membership}\n"
        "%model:codex/gpt-5.6-sol\n%auto\n" in out
    )
    # Phase without size metadata defaults to the small-phase role alias.
    p2_suffix = p2_id.removeprefix(f"{epic_id}.")
    assert (
        f"%id(!{p2_suffix}, clan={epic_id}, bead={p2_id})\n"
        "%model:@small_worker\n%auto\n" in out
    )
    # The epic's explicit land model still wins over the epic-lander alias.
    assert (
        f"%id(!land, clan={epic_id}, bead={epic_id})\n"
        "%model:claude/opus\n%auto\n" in out
    )
    assert out.count(epic_clan_declaration(epic_id)) == 1
    assert "%family" not in out
    assert "%group:" not in out
    # Three %model directives: explicit phase, phase-worker phase, and land.
    assert out.count("%model:") == 3
    assert out.count("\n%auto\n") == 3
    assert "%auto:tale" not in out


def test_work_dry_run_relaunches_from_stored_phase_sizes(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Sized epic", IssueType.PLAN)
        small = project.create(
            "Small",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.SMALL,
            model="claude/sonnet",
        )
        medium = project.create(
            "Medium",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.MEDIUM,
            model="@medium_worker",
        )
        large = project.create(
            "Large",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.LARGE,
            model="codex/gpt-5.6-sol",
        )

    bead_cli.handle_bead_work(make_args(epic.id, dry_run=True, yes=True))

    prompt = capsys.readouterr().out.split("--- Multi-prompt (dry run) ---\n", 1)[1]
    segments = prompt.split("\n---\n")
    by_bead = {
        bead.id: next(
            segment
            for segment in segments
            if f"#bd/work_phase_bead:{bead.id}" in segment
        )
        for bead in (small, medium, large)
    }
    assert "%model:claude/sonnet" in by_bead[small.id]
    assert "#plan" not in by_bead[small.id].splitlines()
    assert "%model:@medium_worker" in by_bead[medium.id]
    assert "#plan" not in by_bead[medium.id].splitlines()
    assert "%model:codex/gpt-5.6-sol" in by_bead[large.id]
    assert by_bead[large.id].rstrip().endswith(f"#bd/work_phase_bead:{large.id}\n#plan")


def test_work_dry_run_uses_custom_big_epic_threshold(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.bead.config.load_merged_config",
        lambda: {"bead": {"big_epic_phase_threshold": 3}},
    )
    with BeadProject(project_dir) as project:
        epic = project.create("Custom threshold epic", IssueType.PLAN)
        for index in range(3):
            project.create(f"P{index}", IssueType.PHASE, parent_id=epic.id)

    bead_cli.handle_bead_work(make_args(epic.id, dry_run=True, yes=True))

    out = capsys.readouterr().out
    land_segment = out.split("\n---\n")[-1]
    assert f"%id(!land, clan={epic.id}, bead={epic.id})" in land_segment
    assert "%model:@big_epic_lander" in land_segment
