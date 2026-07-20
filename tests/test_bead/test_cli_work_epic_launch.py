"""Confirmed launch contract tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.bead.work import (
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_PHASE_BEAD_ID_ENV,
)
from sase.xprompt.directives import extract_prompt_directives

from .cli_work_helpers import (
    FakeLaunchResult,
    bead_wait_lines,
    epic_clan_declaration,
    make_args,
    seed_diamond,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_launches_and_passes_rendered_multi_prompt(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    plan_ref = "sdd/plans/202607/diamond.md"
    with BeadProject(project_dir) as project:
        project.update(epic_id, design=plan_ref)
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
    membership = epic_clan_declaration(epic_id)
    assert query.count(membership) == 1
    assert "%family" not in query
    assert "%group:" not in query
    for index, pid in enumerate(phase_ids):
        assert f"#bd/work_phase_bead:{pid}" in query
        if index == 0:
            assert f"%id({pid}, bead={pid})\n{membership}" in query
        else:
            suffix = pid.removeprefix(f"{epic_id}.")
            assert f"%id({suffix}, clan={epic_id}, bead={pid})" in query
    land_segment = query.split("\n---\n")[-1]
    assert f"%id(land, clan={epic_id}, bead={epic_id})" in land_segment
    assert membership not in land_segment
    assert f"#bd/land_epic:{epic_id}" in query
    assert bead_wait_lines(land_segment) == [
        f"%w(bead={phase_id})" for phase_id in phase_ids
    ]
    assert captured["extra_env"] is None
    assert captured["segment_extra_env"] == tuple(
        [
            {
                SASE_BEAD_ID_ENV: phase_id,
                SASE_EPIC_BEAD_ID_ENV: epic_id,
                SASE_EPIC_CLAN_TRIBE_ENV: "epic",
                SASE_EPIC_PLAN_REF_ENV: plan_ref,
                SASE_PHASE_BEAD_ID_ENV: phase_id,
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            }
            for phase_id in phase_ids
        ]
        + [
            {
                SASE_BEAD_ID_ENV: epic_id,
                SASE_EPIC_BEAD_ID_ENV: epic_id,
                SASE_EPIC_CLAN_TRIBE_ENV: "epic",
                SASE_EPIC_PLAN_REF_ENV: plan_ref,
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            }
        ]
    )
    for segment, env in zip(
        query.split("\n---\n"), captured["segment_extra_env"], strict=True
    ):
        _, directives = extract_prompt_directives(segment)
        assert directives.bead_id == env[SASE_BEAD_ID_ENV]
    assert commit_calls == [
        (project_dir / "sdd/beads", epic_id, "Diamond epic", "epic")
    ]

    # Launch approval owns readiness; mocked runners have not claimed anything.
    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is True
        assert epic.status == Status.OPEN
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    out = capsys.readouterr().out
    assert "Launched" in out
