"""Checkpoint and push tests for epic ``sase bead work``."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Status
from sase.bead.project import BeadProject

from .cli_work_helpers import FakeLaunchResult, make_args, seed_diamond

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_invokes_push_when_config_flag_enabled(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import _PushOutcome

    epic_id, _ = seed_diamond(project_dir)
    events: list[str] = []

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            events.append("launch") or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: events.append("commit") or True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.bead_state_is_clean",
        lambda _beads_dir: True,
    )

    def fake_push(beads_dir: Path, **_kwargs: object) -> _PushOutcome:
        assert beads_dir == project_dir / "sdd/beads"
        events.append("push")
        return _PushOutcome(pushed=True, skipped_no_remote=False, error=None)

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": True}},
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert events == ["commit", "push", "launch"]
    out = capsys.readouterr().out
    assert f"Committed epic launch checkpoint for {epic_id}." in out
    assert "Pushed to remote." in out


def test_work_uses_sync_push_even_when_config_flag_disabled(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = seed_diamond(project_dir)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )
    pushes: list[Path] = []
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir, **_kwargs: (
            pushes.append(beads_dir)
            or type(
                "Outcome",
                (),
                {"pushed": True, "skipped_no_remote": False, "error": None},
            )()
        ),
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": False}},
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert pushes == [project_dir / "sdd/beads"]
    out = capsys.readouterr().out
    assert f"Committed epic launch checkpoint for {epic_id}." in out
    assert "Pushed to remote." in out


def test_work_no_push_flag_overrides_config(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = seed_diamond(project_dir)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )
    # Config asks for a push, but --no-push wins for this invocation.
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": True}},
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir: pytest.fail("--no-push must skip the push"),
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch_async",
        lambda beads_dir: pytest.fail("--no-push must skip the push"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True, no_push=True))

    out = capsys.readouterr().out
    assert f"Committed epic launch checkpoint for {epic_id}." in out
    assert "Pushed to remote." not in out
    assert "background" not in out


def test_work_no_push_rejects_detached_store_before_launch(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_commit._requires_remote_publication",
        lambda _beads_dir: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", lambda _path: True)
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launches.append(query) or FakeLaunchResult()
        ),
    )

    with pytest.raises(SystemExit):
        bead_cli.handle_bead_work(
            make_args(epic_id, yes=True, no_push=True),
        )

    assert launches == []
    assert "--no-push cannot launch workers" in capsys.readouterr().err
    with BeadProject(project_dir) as project:
        assert project.show(epic_id).is_ready_to_work is True
        assert project.show(epic_id).assignee == f"{epic_id}.land"
        assert [project.show(phase_id).assignee for phase_id in phase_ids] == phase_ids


def test_work_async_config_is_upgraded_to_sync_prelaunch_push(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = seed_diamond(project_dir)
    events: list[str] = []

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            events.append("launch") or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": "async"}},
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir, **_kwargs: (
            events.append("sync-push")
            or type(
                "Outcome",
                (),
                {"pushed": True, "skipped_no_remote": False, "error": None},
            )()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch_async",
        lambda beads_dir: pytest.fail("epic checkpoint must never push async"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert events == ["sync-push", "launch"]
    out = capsys.readouterr().out
    assert f"Committed epic launch checkpoint for {epic_id}." in out
    assert "Pushed to remote." in out
    assert "background" not in out


def test_work_push_failure_stops_before_launch_and_preserves_checkpoint(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import _PushOutcome

    epic_id, _ = seed_diamond(project_dir)
    launches: list[str] = []

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launches.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", lambda _path: True)
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir, **_kwargs: _PushOutcome(
            pushed=False, skipped_no_remote=False, error="git push failed: nope"
        ),
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": True}},
    )

    with pytest.raises(SystemExit):
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    captured = capsys.readouterr()
    assert "Launched" not in captured.out
    assert launches == []
    assert "git push failed: nope" in captured.err
    with BeadProject(project_dir) as project:
        assert project.show(epic_id).is_ready_to_work is True
        assert project.show(epic_id).status is Status.IN_PROGRESS


def test_checkpoint_epic_work_launch_reports_contention_timeout_with_resume_flags(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_commit import (
        EpicLaunchCheckpointError,
        checkpoint_epic_work_launch,
    )
    from sase.bead.sync import _PushOutcome

    epic_id, _ = seed_diamond(project_dir)
    log_path = project_dir / "sync.log"

    class Timer:
        def stage(self, *_args: object, **_kwargs: object) -> Any:
            return nullcontext()

    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", lambda _path: True)
    monkeypatch.setattr(
        "sase.bead.cli_work_commit._requires_remote_publication",
        lambda _beads_dir: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _beads_dir, **_kwargs: _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=None,
            skipped_locked=True,
            log_path=log_path,
        ),
    )

    with pytest.raises(EpicLaunchCheckpointError) as excinfo:
        checkpoint_epic_work_launch(
            project_dir / "sdd/beads",
            epic_id,
            no_push=False,
            timer=Timer(),  # type: ignore[arg-type]
        )

    assert excinfo.value.checkpoint_created is True
    assert excinfo.value.retry_requires_push is True
    message = str(excinfo.value)
    assert "held the store lock" in message
    assert "detached bead store has no push remote" not in message
    assert f"managed sync log: {log_path}" in message


def test_work_retry_push_failure_preserves_existing_checkpoint(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.sync import _PushOutcome, bead_state_is_clean
    from sase.bead.work import build_epic_work_plan_from_beads_dir

    epic_id, phase_ids = seed_diamond(project_dir)
    with BeadProject(project_dir) as project:
        project.mark_ready_to_work(epic_id)
        plan = build_epic_work_plan_from_beads_dir(project.beads_dir, epic_id)
        project.preclaim_epic_work(
            epic_id,
            [
                (assignment.bead_id, assignment.agent_name)
                for wave in plan.waves
                for assignment in wave
            ],
            plan.land_agent_name,
        )
        assert bead_state_is_clean(project.beads_dir)

    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", lambda _path: True)
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _beads_dir, **_kwargs: _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="git push failed: retry",
        ),
    )
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda *_args, **_kwargs: pytest.fail("failed retry must not spawn"),
    )

    with pytest.raises(SystemExit):
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    with BeadProject(project_dir) as project:
        assert project.show(epic_id).is_ready_to_work is True
        assert project.show(epic_id).assignee == f"{epic_id}.land"
        assert [project.show(phase_id).assignee for phase_id in phase_ids] == phase_ids
