"""All-active epic retries must skip destructive cleanup and publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead.cli_work_handler import launch_epic_bead_work
from sase.bead.model import Status
from sase.bead.project import BeadProject

from .cli_work_helpers import seed_diamond, write_bead_agent_meta

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_all_active_retry_skips_cleanup_reservations_and_publication(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    land_name = f"{epic_id}.land"
    fake_home = project_dir / "home"
    fake_home.mkdir()
    for phase_id in phase_ids:
        write_bead_agent_meta(fake_home, phase_id, bead_id=phase_id)
    write_bead_agent_meta(fake_home, land_name, bead_id=epic_id)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    def fail(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("all-active retry must not mutate launch state")

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owners", fail
    )
    monkeypatch.setattr("sase.agent.names.reserve_registered_names", fail)
    monkeypatch.setattr("sase.agent.names.mutate_registered_name_reservations", fail)
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fail)
    monkeypatch.setattr("sase.bead.cli_work_handler.checkpoint_epic_work_launch", fail)
    monkeypatch.setattr("sase.bead.cli_work_handler.launch_bead_work_agents", fail)

    with BeadProject(project_dir) as project:
        result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=True,
            yes_to_all=True,
            no_push=False,
            before_agent_launch=lambda *_args: pytest.fail(
                "must not run visibility hook"
            ),
        )
        assert result.launch_state == "already_running"
        assert result.launched_agent_names == ()
        assert set(result.preserved_agent_names) == {*phase_ids, land_name}
        assert project.show(epic_id).is_ready_to_work is False
        assert all(
            project.show(phase_id).status is Status.OPEN for phase_id in phase_ids
        )


def test_all_active_retry_does_not_scan_unrelated_history(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.names import rebuild_name_registry
    from sase.core.agent_scan_facade import scan_agent_artifacts

    epic_id, phase_ids = seed_diamond(project_dir)
    land_name = f"{epic_id}.land"
    fake_home = project_dir / "home"
    fake_home.mkdir()
    for phase_id in phase_ids:
        write_bead_agent_meta(fake_home, phase_id, bead_id=phase_id)
    write_bead_agent_meta(fake_home, land_name, bead_id=epic_id)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    rebuild_name_registry()

    scan_calls = 0
    real_scan = scan_agent_artifacts

    def tracked_scan(*args: object, **kwargs: object) -> object:
        nonlocal scan_calls
        scan_calls += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.scan_agent_artifacts",
        tracked_scan,
    )

    with BeadProject(project_dir) as project:
        result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=True,
            yes_to_all=True,
            no_push=False,
        )
        assert result.launch_state == "already_running"
    assert scan_calls == 0
