"""Monitor retention lifecycle: resume, retry, and failure-pinning paths.

Covers resume settlement with and without live successor custody, stale-owner
and fresh-interpreter failures, successor-collection and pending-write
failures, and fresh-interpreter timeouts.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.monitor._settlement_retention import release_monitor_claim
from sase.monitor.followup import FollowupLaunchResult
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import make_starter_agent, write_project_file
from ._retention_fixtures import (
    RETENTION_CLAIM_WORKFLOW,
    fail_fresh_python_c,
    init_retention_repo,
    make_retention_monitor,
    pending_retention_record,
    persist_retention_delivery,
    read_retention_meta,
    retention_record,
    transfer_retention_to_successor,
    write_retention_meta,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def test_resume_success_label_without_proof_leaves_hold(tmp_path: Path) -> None:
    """A success label without live successor custody cannot clear unresolved."""
    from sase.monitor.resume import _settle_retention_after_resume
    from sase.workspace_provider.retention_record import (
        read_workspace_retention_record,
    )

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, _project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    assert retention_record(artifacts_dir) is not None

    _settle_retention_after_resume(
        artifacts_dir,
        FollowupLaunchResult(launched=True, agent_name="acme--mon@1"),
        "acme--mon@1",
    )

    record = retention_record(artifacts_dir)
    assert record is not None
    assert record.get("settled") is not True
    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None
    assert typed.unresolved is True


def test_resume_degraded_and_failed_leave_hold(tmp_path: Path) -> None:
    """Degraded or failed resumes must not clear the original hold."""
    from sase.monitor.resume import _settle_retention_after_resume

    cases = (
        FollowupLaunchResult(
            launched=True,
            degraded_reason="fell back to workspace #0",
            agent_name="acme--mon@1",
        ),
        FollowupLaunchResult(launched=False, error="boom"),
    )
    for index, launch in enumerate(cases):
        repo = init_retention_repo(tmp_path / f"ws-{index}", dirty=True)
        write_project_file(
            "proj",
            running_claims=[
                WorkspaceClaim(
                    10 + index,
                    RETENTION_CLAIM_WORKFLOW,
                    "acme",
                    pid=os.getpid(),
                    artifacts_timestamp=f"2026090612000{index}",
                )
            ],
        )
        artifacts_dir = make_starter_agent(
            "proj",
            f"2026090612000{index}",
            "acme--mon",
            agent_session="acme",
            agent_session_role="monitor",
            monitor_id="abc123def456",
            monitor_command="true",
            monitor_cwd=str(repo),
            monitor_reason="test",
            monitor_start_status="MONITORING",
            monitor_stop_status="MONITORED",
            monitor_timeout_seconds=30.0,
            monitor_state="failed",
            cl_name="acme",
            workspace_dir=str(repo),
            workspace_num=10 + index,
            pid=os.getpid(),
            monitor_continuation_protocol=MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
            monitor_next_action="Report it.",
        )
        meta = read_retention_meta(artifacts_dir)
        assert (
            release_monitor_claim(
                meta, project_name="proj", artifacts_dir=artifacts_dir
            )
            is None
        )
        assert retention_record(artifacts_dir) is not None

        _settle_retention_after_resume(artifacts_dir, launch, "acme--mon@1")

        record = retention_record(artifacts_dir)
        assert record is not None
        assert record.get("settled") is not True
        assert record["disposition"] == "retain"


def test_resume_transfer_with_live_successor_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume settles a hold only after live successor custody is proven."""
    from sase.monitor.resume import _settle_retention_after_resume
    from sase.workspace_provider.occupant import read_occupant_record
    from sase.workspace_provider.retention_record import read_workspace_retention_record

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    assert retention_record(artifacts_dir) is not None

    successor_pid = os.getpid() + 17
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_followup_agent"] = "acme--mon@1"
    meta["monitor_followup_outcome"] = "launched"
    meta["project_file"] = project_file
    meta["project_name"] = "proj"
    write_retention_meta(artifacts_dir, meta)
    persist_retention_delivery(
        artifacts_dir, meta, agent="acme--mon@1", disposition="acknowledged"
    )
    transfer_retention_to_successor(
        project_file,
        repo,
        from_pid=os.getpid(),
        to_pid=successor_pid,
        timestamp="20260906120100",
    )
    monkeypatch.setattr(
        "sase.monitor.settlement_fresh_owner._receiver_is_live",
        lambda *_args, **_kwargs: True,
    )

    _settle_retention_after_resume(
        artifacts_dir,
        FollowupLaunchResult(launched=True, agent_name="acme--mon@1"),
        "acme--mon@1",
    )

    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None
    assert typed.unresolved is False
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pid == successor_pid
    occupant = read_occupant_record(str(repo))
    assert occupant is not None
    assert occupant.pid == successor_pid
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_stale_owner_and_unavailable_fresh_interpreter_pins_monitor_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure pin uses the monitor artifact timestamp, never parent_timestamp."""
    import sase.monitor._settlement_retention as settlement_mod

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    meta["parent_timestamp"] = "20260906115900"
    write_retention_meta(artifacts_dir, meta)

    def _stale_owner(*_args: object, **_kwargs: object) -> object:
        raise AttributeError("stale owner adapter")

    monkeypatch.setattr(settlement_mod, "_build_retention_owner", _stale_owner)
    monkeypatch.setattr(
        subprocess,
        "run",
        fail_fresh_python_c(OSError("fresh interpreter unavailable")),
    )

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is not None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == "20260906120000"
    pending = pending_retention_record(artifacts_dir)
    assert pending is not None
    assert pending["artifacts_timestamp"] == "20260906120000"
    assert pending["pid"] == os.getpid()
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_successor_collection_failure_pins_dirty_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successor-proof collection failure pins the exact owner instead of releasing."""
    import sase.monitor._settlement_retention as settlement_mod

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("successor collection failed")

    monkeypatch.setattr(settlement_mod, "_retention_successor_from_meta", _boom)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is not None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == "20260906120000"
    pending = pending_retention_record(artifacts_dir)
    assert pending is not None
    assert pending["artifacts_timestamp"] == "20260906120000"
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_pending_write_failure_still_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed pending write still pins the exact matching claim."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    monkeypatch.setattr(
        "sase.turns.workspace_retention_pending.write_pending_retention_identity",
        lambda *_args, **_kwargs: None,
    )

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == "20260906120000"
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    assert pending_retention_record(artifacts_dir) is None


def test_fresh_interpreter_timeout_pins_dirty_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timed-out fresh interpreter still pins the original dirty claim."""
    from sase.turns import workspace_retention as _adapter

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)

    def _stale(*_args: object, **_kwargs: object) -> object:
        raise TypeError("old release_workspace signature")

    monkeypatch.setattr(_adapter, "settle_stranded_workspace", _stale)
    monkeypatch.setattr(
        subprocess,
        "run",
        fail_fresh_python_c(
            subprocess.TimeoutExpired(cmd=["python", "-c"], timeout=60)
        ),
    )

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is not None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == "20260906120000"
    pending = pending_retention_record(artifacts_dir)
    assert pending is not None
    assert pending["artifacts_timestamp"] == "20260906120000"
    assert (repo / "tracked.txt").read_text() == "session owned\n"
