"""Launch-name preflight must fail before bead-store mutations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.agent.names import (
    RegisteredNameReservationBatchError,
    claim_registered_name,
)
from sase.bead.cli_work_handler import BeadWorkError, launch_epic_bead_work
from sase.bead.cli_work_name_preflight import preflight_bead_work_launch_names
from sase.bead.cli_work_task import TaskBeadWorkError, launch_task_bead_work
from sase.bead.project import BeadProject
from sase.bead.work import VCSLaunchContext
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests._agent_loader_helpers import _empty_artifact_snapshot

from .cli_work_helpers import seed_diamond, seed_task, write_bead_agent_meta

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


@pytest.fixture(autouse=True)
def task_vcs_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_work_task.resolve_task_vcs_launch_context",
        lambda: VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )


@pytest.fixture(autouse=True)
def empty_agent_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.scan_agent_artifacts",
        lambda *_args, **_kwargs: _empty_artifact_snapshot(),
    )


def _configure_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )


def test_epic_preflight_blocks_before_preclaim(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    claimed: dict[str, Any] = {}

    from sase.bead.cli_work_cleanup import prepare_selected_bead_work_force_reuse

    real_prepare = prepare_selected_bead_work_force_reuse

    def after_prepare(query: str, *, selection: Any, **kwargs: Any) -> str:
        result = real_prepare(query, selection=selection, **kwargs)
        name = sorted(selection.launch_names)[0]
        artifact_dir = write_bead_agent_meta(
            fake_home,
            name,
            artifact_suffix="concurrent-owner",
            waiting=True,
        )
        claim_registered_name(name, artifact_dir)
        claimed["name"] = name
        claimed["path"] = artifact_dir
        return result

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.prepare_selected_bead_work_force_reuse",
        after_prepare,
    )
    monkeypatch.setattr(
        BeadProject,
        "preclaim_epic_work",
        lambda *_args, **_kwargs: pytest.fail("preflight must not preclaim"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: pytest.fail("preflight must not checkpoint"),
    )

    with BeadProject(project_dir) as project:
        with pytest.raises(BeadWorkError) as excinfo:
            launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                yes_to_all=True,
                no_push=True,
            )

    message = str(excinfo.value)
    assert str(claimed["path"]) in message
    assert f"sase bead work {epic_id}" in message
    assert "try '" not in message
    with BeadProject(project_dir) as project:
        assert project.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            phase = project.show(phase_id)
            assert phase.assignee == ""


def test_task_preflight_blocks_before_preclaim(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    task_id = seed_task(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    claimed: dict[str, Any] = {}

    from sase.bead.cli_work_cleanup import prepare_selected_bead_work_force_reuse

    real_prepare = prepare_selected_bead_work_force_reuse

    def after_prepare(query: str, *, selection: Any, **kwargs: Any) -> str:
        result = real_prepare(query, selection=selection, **kwargs)
        artifact_dir = write_bead_agent_meta(
            fake_home,
            task_id,
            artifact_suffix="concurrent-owner",
            waiting=True,
        )
        claim_registered_name(task_id, artifact_dir)
        claimed["path"] = artifact_dir
        return result

    monkeypatch.setattr(
        "sase.bead.cli_work_task.prepare_selected_bead_work_force_reuse",
        after_prepare,
    )
    monkeypatch.setattr(
        BeadProject,
        "update",
        lambda *_args, **_kwargs: pytest.fail("preflight must not preclaim"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: pytest.fail("preflight must not checkpoint"),
    )

    with BeadProject(project_dir) as project:
        with pytest.raises(TaskBeadWorkError) as excinfo:
            launch_task_bead_work(
                project,
                task_id,
                dry_run=False,
                yes=True,
                yes_to_all=True,
                no_push=True,
            )

    message = str(excinfo.value)
    assert str(claimed["path"]) in message
    assert f"sase bead work {task_id}" in message
    assert "try '" not in message


def test_launch_time_collision_rolls_back_and_explains_owner(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    rollback_calls: list[dict[str, Any]] = []
    preflight_calls = {"n": 0}
    claimed: dict[str, Any] = {}
    real_preflight = preflight_bead_work_launch_names

    def wrapped_preflight(
        launch_names: Any,
        *,
        resume_command: str,
        timer: Any = None,
    ) -> None:
        preflight_calls["n"] += 1
        if preflight_calls["n"] == 1:
            real_preflight(launch_names, resume_command=resume_command, timer=timer)
            name = sorted(launch_names)[0]
            artifact_dir = write_bead_agent_meta(
                fake_home,
                name,
                artifact_suffix="late-owner",
                waiting=True,
            )
            claim_registered_name(name, artifact_dir)
            claimed["name"] = name
            claimed["path"] = artifact_dir
            return
        real_preflight(launch_names, resume_command=resume_command, timer=timer)

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.preflight_bead_work_launch_names",
        wrapped_preflight,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_name_preflight.preflight_bead_work_launch_names",
        wrapped_preflight,
    )

    from sase.bead.cli_work_handler import rollback_work_launch as real_rollback

    def wrapped_rollback(*args: Any, **kwargs: Any) -> None:
        rollback_calls.append(dict(kwargs))
        return real_rollback(*args, **kwargs)

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.rollback_work_launch",
        wrapped_rollback,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: True,
    )
    colliding = phase_ids[0]
    monkeypatch.setattr(
        "sase.agent.names.mutate_registered_name_reservations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RegisteredNameReservationBatchError(
                [
                    {
                        "request_id": "bead-work-name-0",
                        "detail": (
                            f"agent name '{colliding}' is already taken; "
                            f"try '{colliding}1'"
                        ),
                    }
                ]
            )
        ),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_bead_work_agents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RegisteredNameReservationBatchError(
                [
                    {
                        "request_id": "bead-work-name-0",
                        "detail": (
                            f"agent name '{colliding}' is already taken; "
                            f"try '{colliding}1'"
                        ),
                    }
                ]
            )
        ),
    )

    with BeadProject(project_dir) as project:
        with pytest.raises(BeadWorkError) as excinfo:
            launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                yes_to_all=True,
                no_push=True,
            )
        assert project.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            assert project.show(phase_id).assignee == ""

    message = str(excinfo.value)
    assert rollback_calls, "launch-time collision must roll back"
    assert str(claimed["path"]) in message
    assert f"sase bead work {epic_id}" in message
    assert preflight_calls["n"] >= 2


def test_preflight_ownerless_compatibility_does_not_crash(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: AgentIdentitySnapshot.unconfigured()),
    )
    fake_home = project_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    preflight_bead_work_launch_names(
        ("ownerless-name",),
        resume_command="sase bead work foo",
    )

    from sase.agent.names import NameCollisionError, lookup_registered_name

    from sase.bead.cli_work_name_preflight import (
        explain_bead_work_launch_name_collision,
    )

    detail = explain_bead_work_launch_name_collision(
        NameCollisionError("agent name 'ownerless-name' is already taken"),
        ("ownerless-name",),
        resume_command="sase bead work foo",
    )
    assert detail is not None
    assert "sase bead work foo" in detail
    assert lookup_registered_name("ownerless-name") is None
