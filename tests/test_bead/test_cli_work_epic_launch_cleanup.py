"""Forced name-reuse cleanup failure tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Status
from sase.bead.project import BeadProject

from .cli_work_helpers import FakeLaunchResult, make_args, seed_diamond

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


@pytest.mark.parametrize(
    ("conflict_target", "container_kind"),
    [
        pytest.param("phase", "clan", id="phase-clan-container"),
        pytest.param("land", "clan", id="land-clan-container"),
    ],
)
def test_work_expected_name_container_conflict_aborts_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    conflict_target: str,
    container_kind: str,
) -> None:
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    conflict_name = phase_ids[0] if conflict_target == "phase" else f"{epic_id}.land"

    def fake_wipe(name: str) -> AgentNameWipeResult:
        if name == conflict_name:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                skipped_container_kind=container_kind,
            )
        return AgentNameWipeResult(target_name=name, found=False)

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    monkeypatch.setattr(
        "sase.agent.names.find_agent_clan",
        lambda name: (
            type("Clan", (), {"members": (object(),)})()
            if name == conflict_name
            else None
        ),
    )
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: pytest.fail("aborted launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert (
        f"agent name '{conflict_name}' is reserved by a {container_kind} container"
        in err
    )
    assert "cannot be force-reused" in err
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            phase = proj.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


@pytest.mark.parametrize(
    "failure_mode",
    [
        pytest.param("member-errors", id="member-wipe-errors"),
        pytest.param("residual-family", id="residual-family-reservation"),
    ],
)
def test_work_family_cleanup_failure_aborts_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    from types import SimpleNamespace

    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    family_name = phase_ids[0]
    plan_name = f"{family_name}--plan"
    code_name = f"{family_name}--code"

    monkeypatch.setattr(
        "sase.agent.names.find_agent_family",
        lambda name: (
            SimpleNamespace(
                members=(
                    SimpleNamespace(name=plan_name, outcome="completed"),
                    SimpleNamespace(name=code_name, outcome=None),
                )
            )
            if name == family_name
            else None
        ),
    )

    def fake_wipe(name: str) -> AgentNameWipeResult:
        if name == family_name:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                skipped_container_kind="family",
            )
        if name == plan_name and failure_mode == "member-errors":
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                errors=("kaboom",),
            )
        if name in {plan_name, code_name}:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                registry_names_removed=(name,),
            )
        return AgentNameWipeResult(target_name=name, found=False)

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    monkeypatch.setattr(
        "sase.agent.names.rebuild_name_registry",
        lambda: {
            "entries": {family_name: {}} if failure_mode == "residual-family" else {}
        },
    )
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: pytest.fail("aborted launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            phase = proj.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


@pytest.mark.parametrize(
    "failure_mode",
    [
        pytest.param("raise", id="wipe-raises"),
        pytest.param("errors", id="wipe-reports-errors"),
        pytest.param("residual", id="name-still-reserved"),
    ],
)
def test_work_force_reuse_cleanup_failure_aborts_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_mode: str,
) -> None:
    """A failed forced-reuse wipe aborts before any bead mutation or launch."""
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)

    def fake_wipe(name: str) -> AgentNameWipeResult:
        if failure_mode == "raise":
            raise RuntimeError("kaboom")
        if failure_mode == "errors":
            return AgentNameWipeResult(target_name=name, found=True, errors=("kaboom",))
        # residual: found but never removed from the registry.
        return AgentNameWipeResult(
            target_name=name, found=True, registry_names_removed=()
        )

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)

    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: pytest.fail("aborted launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "forced reuse cleanup" in err
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""
