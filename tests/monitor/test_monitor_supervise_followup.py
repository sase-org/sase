"""Follow-up launch and workspace-claim tests for :mod:`sase.monitor.supervise`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.monitor.followup import FollowupLaunchResult
from sase.monitor.supervise import run_supervisor
from sase.notifications.store import load_notifications
from sase.running_field import get_claimed_workspaces

from ._supervise import _make_member, _restore_signal_handlers, _sandbox_home


def test_run_supervisor_holds_the_claim_when_the_followup_launch_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir, project_file = _make_member(
        tmp_path, command="true", next_action="Report that it finished."
    )
    import sase.monitor.supervise as supervise_module

    done_path = Path(artifacts_dir) / "done.json"

    def fake_launch_success(
        _artifacts_dir: str, meta: dict[str, object], **_kwargs: object
    ) -> bool:
        assert not done_path.exists()
        meta["monitor_followup_agent"] = "acme--1"
        return True

    monkeypatch.setattr(supervise_module, "launch_followup_agent", fake_launch_success)

    run_supervisor(artifacts_dir)

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"
    assert meta["monitor_settled"] is True
    assert done_path.exists()
    # engine-next transfers this claim to the follow-up agent it launches;
    # the supervisor itself must never release it on success.
    assert len(get_claimed_workspaces(project_file)) == 1


def test_run_supervisor_persists_stopped_at_after_followup_start_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir, _project_file = _make_member(
        tmp_path, command="true", next_action="Report that it finished."
    )
    followup_dir = tmp_path / "followup"
    followup_dir.mkdir()
    import sase.monitor.supervise as supervise_module

    done_path = Path(artifacts_dir) / "done.json"
    wait_calls: list[tuple[str, int | None]] = []

    def fake_launch_success(
        _artifacts_dir: str, meta: dict[str, object], **_kwargs: object
    ) -> FollowupLaunchResult:
        on_disk = json.loads((Path(_artifacts_dir) / "agent_meta.json").read_text())
        assert "stopped_at" not in on_disk
        assert isinstance(meta.get("stopped_at"), str)
        meta["monitor_followup_agent"] = "acme--1"
        return FollowupLaunchResult(
            launched=True,
            agent_name="acme--1",
            artifacts_dir=str(followup_dir),
            pid=123,
        )

    def fake_wait(artifacts_dir_arg: str, pid: int | None) -> bool:
        on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
        assert "stopped_at" not in on_disk
        assert not done_path.exists()
        wait_calls.append((artifacts_dir_arg, pid))
        return False

    monkeypatch.setattr(supervise_module, "launch_followup_agent", fake_launch_success)
    monkeypatch.setattr(supervise_module, "wait_for_followup_started", fake_wait)

    run_supervisor(artifacts_dir)

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert wait_calls == [(str(followup_dir), 123)]
    assert isinstance(meta.get("stopped_at"), str)
    assert meta["monitor_settled"] is True
    assert done_path.exists()


def test_run_supervisor_records_degraded_followup_and_releases_monitor_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir, project_file = _make_member(
        tmp_path, command="true", next_action="Report that it finished."
    )
    followup_dir = tmp_path / "followup"
    followup_dir.mkdir()
    import sase.monitor.supervise as supervise_module

    wait_calls: list[tuple[str, int | None]] = []

    def fake_launch_degraded(
        _artifacts_dir: str, meta: dict[str, object], **_kwargs: object
    ) -> FollowupLaunchResult:
        meta["monitor_followup_agent"] = "acme--1"
        return FollowupLaunchResult(
            launched=True,
            degraded_reason="fresh claim on the same workspace",
            agent_name="acme--1",
            artifacts_dir=str(followup_dir),
            pid=456,
        )

    def fake_wait(artifacts_dir_arg: str, pid: int | None) -> bool:
        wait_calls.append((artifacts_dir_arg, pid))
        return True

    monkeypatch.setattr(supervise_module, "launch_followup_agent", fake_launch_degraded)
    monkeypatch.setattr(supervise_module, "wait_for_followup_started", fake_wait)

    run_supervisor(artifacts_dir)

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert wait_calls == [(str(followup_dir), 456)]
    assert meta["monitor_followup_outcome"] == "launched-degraded"
    assert meta["monitor_followup_degraded_reason"] == (
        "fresh claim on the same workspace"
    )
    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["monitor_followup_outcome"] == "launched-degraded"
    assert done["monitor_followup_degraded_reason"] == (
        "fresh claim on the same workspace"
    )
    assert "monitor_followup_error" not in done
    assert get_claimed_workspaces(project_file) == []


def test_run_supervisor_releases_the_claim_when_the_followup_launch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir, project_file = _make_member(
        tmp_path, command="true", next_action="Report that it finished."
    )
    import sase.monitor.supervise as supervise_module

    def fake_launch_failure(
        _artifacts_dir: str, meta: dict[str, object], **_kwargs: object
    ) -> bool:
        assert not (Path(_artifacts_dir) / "done.json").exists()
        meta["monitor_followup_error"] = "boom"
        return False

    monkeypatch.setattr(supervise_module, "launch_followup_agent", fake_launch_failure)
    monkeypatch.setattr(
        supervise_module,
        "wait_for_followup_started",
        lambda *_args: pytest.fail("failed follow-up launch should not wait"),
    )

    run_supervisor(artifacts_dir)

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"
    assert meta["monitor_settled"] is True
    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["monitor_state"] == "completed"
    assert done["monitor_followup_error"] == "boom"
    # A failed follow-up launch must not leave the workspace claimed forever.
    assert get_claimed_workspaces(project_file) == []
    # A dropped follow-up remains diagnosable via done.json/agent_meta.json
    # fields above -- it must not also raise an alarm notification.
    assert load_notifications() == []


def test_run_supervisor_release_matches_only_monitor_workflow(tmp_path: Path) -> None:
    artifacts_dir, project_file = _make_member(
        tmp_path, command="true", claim_workflow="ace-run"
    )

    run_supervisor(artifacts_dir)

    claims = get_claimed_workspaces(project_file)
    assert [(claim.workspace_num, claim.workflow) for claim in claims] == [
        (1, "ace-run")
    ]
