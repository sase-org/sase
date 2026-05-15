"""Launch and rendering tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import BeadProject

from .cli_work_helpers import (
    FakeLaunchResult,
    make_args,
    seed_changespec_epic,
    seed_diamond,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_launches_and_passes_rendered_multi_prompt(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    captured: dict[str, Any] = {}
    commit_calls: list[tuple[Path, str, str, str]] = []

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
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

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    # Launcher was called exactly once with a multi-prompt referencing every phase.
    query = captured["query"]
    assert "---" in query
    assert query.count(f"%group:{epic_id}") == len(phase_ids) + 1
    for pid in phase_ids:
        assert f"#bd/work_phase_bead:{pid}" in query
    assert f"#bd/land_epic:{epic_id}" in query
    assert captured["extra_env"] is None
    assert captured["segment_extra_env"] == tuple(
        {"SASE_BEAD_ID": bead_id} for bead_id in [*phase_ids, epic_id]
    )
    assert commit_calls == [
        (project_dir / "sdd/beads", epic_id, "Diamond epic", "epic")
    ]

    # Each phase was pre-claimed.
    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is True
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.IN_PROGRESS
            assert phase.assignee == pid

    out = capsys.readouterr().out
    assert "Launched" in out


def test_work_linked_legend_epic_uses_legend_tag_and_links(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as proj:
        legend = proj.create(
            "Legend roadmap",
            IssueType.PLAN,
            tier=BeadTier.LEGEND,
            design="sdd/legends/202605/roadmap.md",
            epic_count=1,
        )
        epic = proj.create("Legend child epic", IssueType.PLAN, parent_id=legend.id)
        p1 = proj.create("P1", IssueType.PHASE, parent_id=epic.id)
        p2 = proj.create("P2", IssueType.PHASE, parent_id=epic.id)
        proj.add_dependency(p2.id, p1.id)

    captured: dict[str, Any] = {}

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        captured["query"] = query
        captured["extra_env"] = extra_env
        captured["segment_extra_env"] = segment_extra_env
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic.id, yes=True))

    query = captured["query"]
    assert query.count(f"%group:{legend.id}") == 3
    assert f"%group:{epic.id}" not in query
    assert f"#bd/work_phase_bead:{p1.id}" in query
    assert f"#bd/work_phase_bead:{p2.id}" in query
    assert f"#bd/land_epic:{epic.id}" in query

    assert captured["extra_env"] is None
    assert captured["segment_extra_env"] == (
        {"SASE_BEAD_ID": p1.id},
        {"SASE_BEAD_ID": p2.id},
        {"SASE_BEAD_ID": epic.id},
    )


def test_work_stale_owner_round_trip_wipes_and_rewrites(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale name registry entries are wiped, and the launcher sees a rewritten prompt."""
    epic_id, phase_ids = seed_diamond(project_dir)
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

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    query = captured["query"]
    # Launcher receives the rewritten prompt: ordinary %name:<n> (no '!').
    assert "%name:!" not in query
    for pid in phase_ids:
        assert f"%name:{pid}\n" in query
    assert f"%name:{epic_id}\n" in query

    assert len(wiped) == 1
    expected_names = {*phase_ids, epic_id}
    assert set(wiped[0]) == expected_names


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
        "sase.bead.sync.commit_bead_work_launch",
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
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert out.count(f"%group:{epic_id}") == len(phase_ids) + 1


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
            model="codex/gpt-5.5",
        )
        p2 = proj.create("P2", IssueType.PHASE, parent_id=epic.id)
    epic_id, p1_id, p2_id = epic.id, p1.id, p2.id

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    out = capsys.readouterr().out
    assert f"%name:!{p1_id}\n%group:{epic_id}\n%model:codex/gpt-5.5\n%approve" in out
    # Phase without model has no %model directive between %group and %approve.
    assert f"%name:!{p2_id}\n%group:{epic_id}\n%approve" in out
    assert f"%name:!{epic_id}\n%group:{epic_id}\n%model:claude/opus\n%approve" in out
    # Two %model directives: one phase, one land.
    assert out.count("%model:") == 2


def test_work_dry_run_regular_epic_renders_vcs_launch_wrappers(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = tmp_path / "home"
    project_root = fake_home / ".sase" / "projects" / "sase"
    project_root.mkdir(parents=True)
    (project_root / "sase.sase").write_text(
        "WORKSPACE_DIR: /tmp/sase\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda: "sase",
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda project_file: "git",
    )

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    for pid in phase_ids:
        assert f"#git:sase\n%name:!{pid}\n%group:{epic_id}" in out
        assert f"#bd/work_phase_bead:{pid}" in out
    assert f"#git:sase\n%name:!{epic_id}\n%group:{epic_id}" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(f"%group:{epic_id}") == len(phase_ids) + 1

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


def test_work_dry_run_renders_changespec_launch_wrappers(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_changespec_epic(project_dir)
    fake_home = tmp_path / "home"
    project_root = fake_home / ".sase" / "projects" / "sase"
    project_root.mkdir(parents=True)
    (project_root / "sase.sase").write_text(
        "WORKSPACE_DIR: /tmp/sase\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda: "sase",
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda project_file: "git",
    )

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    assert "#git:sase #pr(name=feature_epic, bug_id=12345)" in out
    assert (
        f"#git:sase #pr(name=feature_epic, bug_id=12345)\n%name:!{phase_ids[0]}\n%group:{epic_id}"
        in out
    )
    assert f"#git:feature_epic\n%name:!{phase_ids[1]}\n%group:{epic_id}" in out
    assert f"#git:feature_epic\n%name:!{epic_id}\n%group:{epic_id}" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(f"%group:{epic_id}") == len(phase_ids) + 1

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""
