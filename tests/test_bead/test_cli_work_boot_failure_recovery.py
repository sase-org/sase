"""Boot-failure nameless-registry recovery for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.names import (
    AgentNameWipeResult,
    claim_registered_name,
)
from sase.bead import cli as bead_cli
from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import BeadWorkSlot
from sase.bead.model import Status
from sase.bead.project import BeadProject

from .cli_work_helpers import (
    FakeLaunchResult,
    make_args,
    seed_diamond,
    write_bead_agent_meta,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_macros")

_BOOT_FAILURE_DETAIL = (
    "no agent identity metadata; boot-failed launch owned by its registry reservation"
)
_DEAD_STOPPED_AT = "2026-11-12T05:29:56Z"


def _stub_wipe(monkeypatch: pytest.MonkeyPatch, member_names: set[str]) -> list[str]:
    wiped: list[str] = []

    def fake_wipe(name: str) -> AgentNameWipeResult:
        wiped.append(name)
        if name in member_names:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                registry_names_removed=(name,),
            )
        return AgentNameWipeResult(target_name=name, found=False)

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    monkeypatch.setattr(
        "sase.agent.names.rebuild_name_registry", lambda: {"entries": {}}
    )
    return wiped


def _stub_launch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None, origin=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    return launched


def _write_boot_failure_stub(
    home: Path,
    owner_name: str,
    *,
    live: bool,
) -> Path:
    return write_bead_agent_meta(
        home,
        owner_name,
        bead_id=None,
        nameless=True,
        stopped_at=None if live else _DEAD_STOPPED_AT,
    )


def _phase_slot(phase_id: str) -> BeadWorkSlot:
    return BeadWorkSlot(
        slot_id=phase_id,
        owner_name=phase_id,
        expected_bead_id=phase_id,
        launch_name=phase_id,
    )


def test_work_dead_boot_failure_stub_auto_recovers(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    owner = phase_ids[0]
    artifact_dir = _write_boot_failure_stub(fake_home, owner, live=False)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    claim_registered_name(owner, artifact_dir, replace_existing=True)
    wiped = _stub_wipe(monkeypatch, {owner})
    launched = _stub_launch(monkeypatch)

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    err = capsys.readouterr().err
    assert "not associated with expected bead" not in err
    assert "BLOCKED" not in err
    assert _BOOT_FAILURE_DETAIL in err
    assert owner in wiped
    assert len(launched) == 1
    assert f"%id({owner}, bead={owner})" in launched[0]


def test_work_live_boot_failure_stub_is_preserved(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    owner = phase_ids[0]
    artifact_dir = _write_boot_failure_stub(fake_home, owner, live=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    claim_registered_name(owner, artifact_dir, replace_existing=True)

    selection = select_bead_work_launch(
        slots=(_phase_slot(owner),),
        bead_assignees={},
    )
    assert selection.blocked_targets == ()
    assert selection.launch_names == frozenset()
    assert len(selection.targets) == 1
    target = selection.targets[0]
    assert (target.action, target.current_state) == ("PRESERVE", "STARTING")
    assert _BOOT_FAILURE_DETAIL in target.detail

    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: pytest.fail(f"live boot stub must not be wiped: {name}"),
    )
    launched = _stub_launch(monkeypatch)

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    err = capsys.readouterr().err
    assert "not associated with expected bead" not in err
    assert "BLOCKED" not in err
    assert len(launched) == 1
    assert f"%id({owner}, bead={owner})" not in launched[0]
    assert f"%w(bead={owner})" in launched[0]
    with BeadProject(project_dir) as project:
        phase = project.show(owner)
        assert phase.status == Status.OPEN
        assert phase.assignee == ""


def test_work_dead_boot_failure_land_slot_auto_recovers(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    land_name = f"{epic_id}.land"
    artifact_dir = _write_boot_failure_stub(fake_home, land_name, live=False)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    claim_registered_name(land_name, artifact_dir, replace_existing=True)
    wiped = _stub_wipe(monkeypatch, {land_name})
    launched = _stub_launch(monkeypatch)

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    err = capsys.readouterr().err
    assert "not associated with expected bead" not in err
    assert "BLOCKED" not in err
    assert _BOOT_FAILURE_DETAIL in err
    assert land_name in wiped
    assert len(launched) == 1
    assert f"%id(land, clan={epic_id}, bead={epic_id})" in launched[0]
