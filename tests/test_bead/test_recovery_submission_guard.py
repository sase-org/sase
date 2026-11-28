"""Execution-time close-token guard tests for the bead-work launch path.

Proves that a recovery proc reaching ``launch_epic_bead_work`` launches only
the land agent while the close token is current, and aborts before any
readiness, preclaim, cleanup, or spawn work once a child reopens or a later
close event supersedes the claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead.cli_work_handler import launch_epic_bead_work
from sase.bead.cli_work_handler_errors import BeadWorkError
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.bead.recovery_submit import RecoveryLaunchGuard
from sase.bead.work import SASE_BEAD_ID_ENV
from sase.bead.zombie import ZombieReport
from sase.core.zombie_facade import ZombieEvaluationReport, ZombieVerdict

from .cli_work_helpers import FakeLaunchResult, seed_diamond

pytestmark = pytest.mark.usefixtures("fake_cli_work_macros")

PROJECT = "alpha"
TOKEN = "epic.4:evt-1"
NEWER_TOKEN = "epic.4:evt-2"


def _verdict(
    epic_id: str,
    *,
    token: str = TOKEN,
    state: str = "zombie",
    eligible: bool = True,
) -> ZombieVerdict:
    return ZombieVerdict(
        plan_id=epic_id,
        title="Diamond epic",
        state=state,
        zombie=state == "zombie",
        recovery_eligible=eligible,
        close_token=token,
    )


def _report(epic_id: str, **kwargs: Any) -> ZombieReport:
    return ZombieReport(
        report=ZombieEvaluationReport(rows=(_verdict(epic_id, **kwargs),)),
        project=PROJECT,
        titles={},
        generated_at=0.0,
    )


def _close_all_phases(project_dir: Path) -> tuple[str, list[str]]:
    epic_id, phase_ids = seed_diamond(project_dir)
    with BeadProject(project_dir) as project:
        project.mark_ready_to_work(epic_id)
        for index, phase_id in enumerate(phase_ids):
            project.update(
                phase_id,
                status=Status.IN_PROGRESS.value,
                assignee=f"completed-phase-{index}",
            )
        project.close(phase_ids)
    return epic_id, phase_ids


def _stub_land_only_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_launch(
        query: str,
        *,
        segment_extra_env: tuple[dict[str, str], ...],
        expected_names: set[str],
        launch_context: Any,
    ) -> list[FakeLaunchResult]:
        captured["expected_names"] = expected_names
        captured["segment_extra_env"] = segment_extra_env
        return [FakeLaunchResult()]

    monkeypatch.setattr(
        "sase.bead.cli_work_handler_publish.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler_publish.launch_bead_work_agents", fake_launch
    )
    return captured


def _forbid_every_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        BeadProject,
        "mark_ready_to_work",
        lambda *_args, **_kwargs: pytest.fail("guard must run first"),
    )
    monkeypatch.setattr(
        BeadProject,
        "preclaim_epic_work",
        lambda *_args, **_kwargs: pytest.fail("guard must run first"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler_publish.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: pytest.fail("guard must run first"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler_publish.launch_bead_work_agents",
        lambda *_args, **_kwargs: pytest.fail("guard must run first"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler_launch.prepare_selected_bead_work_force_reuse",
        lambda *_args, **_kwargs: pytest.fail("guard must run first"),
    )


def test_guard_with_current_token_launches_only_the_lander(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epic_id, _ = _close_all_phases(project_dir)
    land_name = f"{epic_id}.land"
    captured = _stub_land_only_launch(monkeypatch)
    seen_projects: list[str] = []

    def fake_load(project: str) -> ZombieReport:
        seen_projects.append(project)
        return _report(epic_id)

    monkeypatch.setattr("sase.bead.recovery_submit.load_zombie_report", fake_load)

    with BeadProject(project_dir) as project:
        result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=True,
            yes_to_all=False,
            no_push=False,
            recovery_guard=RecoveryLaunchGuard(
                project=PROJECT, expected_close_token=TOKEN
            ),
        )

    assert result.launch_state == "launched"
    assert result.launched_agent_names == (land_name,)
    assert captured["expected_names"] == {land_name}
    assert seen_projects == [PROJECT]
    assert [env[SASE_BEAD_ID_ENV] for env in captured["segment_extra_env"]] == [epic_id]


def test_guard_with_stale_token_aborts_before_any_mutation(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later close event supersedes the claim: no phase worker launches."""
    epic_id, phase_ids = _close_all_phases(project_dir)
    _forbid_every_mutation(monkeypatch)
    monkeypatch.setattr(
        "sase.bead.recovery_submit.load_zombie_report",
        lambda project: _report(epic_id, token=NEWER_TOKEN),
    )

    with BeadProject(project_dir) as project:
        with pytest.raises(BeadWorkError, match="close token changed"):
            launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                yes_to_all=False,
                no_push=False,
                recovery_guard=RecoveryLaunchGuard(
                    project=PROJECT, expected_close_token=TOKEN
                ),
            )

    with BeadProject(project_dir) as project:
        epic = project.show(epic_id)
        assert (epic.status, epic.assignee) == (Status.OPEN, "")
        for phase_id in phase_ids:
            assert project.show(phase_id).status is Status.CLOSED


def test_guard_with_reopened_child_aborts_before_any_mutation(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epic_id, _ = _close_all_phases(project_dir)
    _forbid_every_mutation(monkeypatch)
    monkeypatch.setattr(
        "sase.bead.recovery_submit.load_zombie_report",
        lambda project: _report(epic_id, state="open", eligible=False),
    )

    with BeadProject(project_dir) as project:
        with pytest.raises(BeadWorkError, match="no longer an eligible zombie"):
            launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                yes_to_all=False,
                no_push=False,
                recovery_guard=RecoveryLaunchGuard(
                    project=PROJECT, expected_close_token=TOKEN
                ),
            )


def test_guard_with_unknown_evidence_aborts_before_any_mutation(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epic_id, _ = _close_all_phases(project_dir)
    _forbid_every_mutation(monkeypatch)
    monkeypatch.setattr(
        "sase.bead.recovery_submit.load_zombie_report",
        lambda project: ZombieReport(
            report=ZombieEvaluationReport(rows=()),
            project=project,
            titles={},
            generated_at=0.0,
            collection_failed=True,
            failure_reason="store unreadable",
        ),
    )

    with BeadProject(project_dir) as project:
        with pytest.raises(BeadWorkError, match="cannot verify"):
            launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                yes_to_all=False,
                no_push=False,
                recovery_guard=RecoveryLaunchGuard(
                    project=PROJECT, expected_close_token=TOKEN
                ),
            )


def test_manual_launch_without_guard_is_unchanged(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runs that never set the carrier keep the existing launch behavior."""
    epic_id, _ = _close_all_phases(project_dir)
    land_name = f"{epic_id}.land"
    captured = _stub_land_only_launch(monkeypatch)
    monkeypatch.setattr(
        "sase.bead.recovery_submit.load_zombie_report",
        lambda project: (_ for _ in ()).throw(
            AssertionError("manual runs must not consult the zombie report")
        ),
    )

    with BeadProject(project_dir) as project:
        result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=True,
            yes_to_all=False,
            no_push=False,
        )

    assert result.launch_state == "launched"
    assert result.launched_agent_names == (land_name,)
    assert captured["expected_names"] == {land_name}
