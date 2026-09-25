"""Bead-work selection repairs or blocks agent-name registry drift."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.names import (
    rebuild_name_registry,
    reset_name_registry_caches_for_tests,
)
from sase.agent.names._registry_store import registry_path
from sase.bead.cli_work_cleanup_apply import revalidate_bead_work_launch_selection
from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import BeadWorkLaunchSelection, BeadWorkSlot
from sase.bead.cli_work_handler import BeadWorkError, launch_epic_bead_work
from sase.bead.cli_work_name_cleanup import ForcedReuseCleanupError
from sase.bead.project import BeadProject

from .cli_work_helpers import seed_diamond, write_bead_agent_meta

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def _slot(name: str, *, launch: bool = True) -> BeadWorkSlot:
    return BeadWorkSlot(
        slot_id=name,
        owner_name=name,
        expected_bead_id=name,
        launch_name=name if launch else None,
        allow_populated_clan_skip=not launch,
    )


def _drop_registry_entry(name: str) -> None:
    path = registry_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["entries"]
    dropped = [key for key in list(entries) if key == name or key.endswith(name)]
    assert dropped, f"expected registry to contain {name}"
    for key in dropped:
        del entries[key]
    path.write_text(json.dumps(data), encoding="utf-8")
    reset_name_registry_caches_for_tests()


def _seed_incident_owners(home: Path) -> tuple[str, ...]:
    names = tuple(f"sase-19i.{index}" for index in range(1, 7)) + ("sase-19i.land",)
    for name in names:
        waiting = name.endswith(".6")
        write_bead_agent_meta(
            home,
            name,
            bead_id=name,
            waiting=waiting,
            done=not waiting,
            outcome="failed",
        )
    return names


def test_select_repairs_missing_registry_owner_from_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    names = _seed_incident_owners(home)
    drifted = "sase-19i.6"
    monkeypatch.setattr(Path, "home", lambda: home)
    rebuild_name_registry()
    _drop_registry_entry(drifted)

    rebuild_calls = 0
    real_rebuild = rebuild_name_registry

    def tracked_rebuild(*args: Any, **kwargs: Any) -> Any:
        nonlocal rebuild_calls
        rebuild_calls += 1
        return real_rebuild(*args, **kwargs)

    monkeypatch.setattr("sase.agent.names.rebuild_name_registry", tracked_rebuild)

    selection = select_bead_work_launch(
        slots=tuple(_slot(name) for name in names),
        bead_assignees={},
    )

    assert rebuild_calls == 1
    err = capsys.readouterr().err
    assert drifted in err
    assert "rebuilding the registry before cleanup selection" in err
    by_name = {target.name: target for target in selection.targets}
    assert by_name[drifted].action == "KILL"
    assert drifted in selection.launch_names
    assert selection.blocked_targets == ()


def test_unrepairable_drift_blocks_before_preclaim(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    drifted = phase_ids[-1]
    land_name = f"{epic_id}.land"
    fake_home = project_dir / "home"
    fake_home.mkdir()
    for phase_id in phase_ids:
        write_bead_agent_meta(
            fake_home,
            phase_id,
            bead_id=phase_id,
            waiting=phase_id == drifted,
            done=phase_id != drifted,
            outcome="failed",
        )
    write_bead_agent_meta(
        fake_home, land_name, bead_id=epic_id, done=True, outcome="failed"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    rebuild_name_registry()
    _drop_registry_entry(drifted)
    monkeypatch.setattr(
        "sase.agent.names.rebuild_name_registry", lambda *args, **kwargs: None
    )

    def fail_preclaim(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("unrepairable registry drift must not preclaim")

    monkeypatch.setattr(BeadProject, "preclaim_epic_work", fail_preclaim)
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: pytest.fail("must not checkpoint"),
    )

    with BeadProject(project_dir) as project:
        with pytest.raises(BeadWorkError, match="does not record even after a rebuild"):
            launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                yes_to_all=True,
                no_push=True,
            )


def test_select_does_not_rebuild_when_registry_matches_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    names = _seed_incident_owners(home)
    monkeypatch.setattr(Path, "home", lambda: home)
    rebuild_name_registry()

    def fail_rebuild(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("matching registry must not rebuild")

    monkeypatch.setattr("sase.agent.names.rebuild_name_registry", fail_rebuild)

    selection = select_bead_work_launch(
        slots=tuple(_slot(name) for name in names),
        bead_assignees={},
    )
    assert "sase-19i.6" in selection.launch_names
    assert selection.blocked_targets == ()


def test_revalidate_raises_when_drift_appears_after_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    names = tuple(f"sase-19i.{index}" for index in range(1, 6))
    monkeypatch.setattr(Path, "home", lambda: home)
    for name in names:
        write_bead_agent_meta(home, name, bead_id=name, done=True, outcome="failed")
    rebuild_name_registry()
    slots = tuple(_slot(name) for name in names) + (_slot("sase-19i.6"),)
    previous = select_bead_work_launch(slots=slots, bead_assignees={})
    assert "sase-19i.6" in previous.launch_names
    assert all(target.name != "sase-19i.6" for target in previous.targets)

    write_bead_agent_meta(home, "sase-19i.6", bead_id="sase-19i.6", waiting=True)
    reset_name_registry_caches_for_tests()

    with pytest.raises(
        ForcedReuseCleanupError, match="owner changed after cleanup preview"
    ):
        revalidate_bead_work_launch_selection(previous, bead_assignees={})
