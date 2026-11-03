"""Monitor retention: stopped, lost, and failed settlement paths.

Covers the monitor-retention phase through the real settlement entry point
(:func:`sase.monitor.settlement.settle_claim_and_followup`) and the
retention-aware claim releaser for stopped monitors, reboot-lost monitors,
failed follow-ups, degraded successors, blocked continuation capture, and
same-workspace successor proof.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_LEGACY,
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.monitor.followup import FollowupLaunchResult
from sase.monitor.output import OutputCapture
from sase.monitor._settlement_retention import release_monitor_claim
from sase.monitor.settlement import settle_claim_and_followup
from sase.running_field import get_claimed_workspaces

from ._retention_fixtures import (
    init_retention_repo,
    make_retention_monitor,
    no_launch_followup,
    read_retention_meta,
    retention_record,
    write_retention_meta,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _failed_launch(*_args: object, **_kwargs: object) -> FollowupLaunchResult:
    return FollowupLaunchResult(launched=False, error="follow-up launch failed")


def _degraded_launch(*_args: object, **_kwargs: object) -> FollowupLaunchResult:
    return FollowupLaunchResult(
        launched=True,
        degraded_reason="claim transfer failed; fell back to workspace #0",
        agent_name="acme--mon@1",
        artifacts_dir="/tmp/other",
        pid=999999,
    )


@pytest.mark.parametrize(
    "protocol",
    [MONITOR_CONTINUATION_PROTOCOL_LEGACY, MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1],
)
def test_stopped_dirty_monitor_pins_claim_and_keeps_files(
    tmp_path: Path, protocol: str
) -> None:
    """Stopped monitors with uncommitted work retain the workspace on both protocols."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo, protocol=protocol)
    meta = read_retention_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=no_launch_followup,
    )

    assert result.error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record["terminal_reason"] == "stopped"
    assert record["monitor_state"] == "stopped"
    from sase.workspace_provider.retention_record import (
        read_workspace_retention_record,
        workspace_retention_lines,
    )

    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None and typed.unresolved is True
    assert typed.monitor_resume_eligible is False
    joined = "\n".join(workspace_retention_lines(typed))
    assert "sase monitor resume" not in joined
    assert "Dismiss this agent to release the workspace." in joined


@pytest.mark.parametrize(
    "protocol",
    [MONITOR_CONTINUATION_PROTOCOL_LEGACY, MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1],
)
def test_stopped_clean_monitor_releases_claim(tmp_path: Path, protocol: str) -> None:
    """Stopped monitors with no dirty work keep the normal release path."""
    repo = init_retention_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(repo, protocol=protocol)
    meta = read_retention_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=0,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=no_launch_followup,
    )

    assert result.error is None
    assert get_claimed_workspaces(project_file) == []
    assert retention_record(artifacts_dir) is None


def test_reboot_lost_dirty_monitor_retains(tmp_path: Path) -> None:
    """A reboot-lost monitor (unknown outcome) retains dirty work."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo, next_action="Report it.")
    meta = read_retention_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="lost",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=no_launch_followup,
    )

    assert result.error is not None  # lost follow-up cannot launch
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_failed_monitor_with_failed_followup_retains_dirty(tmp_path: Path) -> None:
    """Launch failure with unresolved dirt retains the original workspace."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(
        repo, monitor_state="failed", next_action="Report it."
    )
    meta = read_retention_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_failed_launch,
    )

    assert result.error is not None
    assert result.launch_result is not None
    assert result.launch_result.launched is False
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record.get("monitor_state") == "failed"
    assert record.get("monitor_next_action") == "Report it."
    from sase.workspace_provider.retention_record import (
        read_workspace_retention_record,
        workspace_retention_lines,
    )

    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None and typed.monitor_resume_eligible is True
    assert any(
        "sase monitor resume abc123def456" in line
        for line in workspace_retention_lines(typed)
    )


def test_failed_monitor_with_failed_followup_releases_when_clean(
    tmp_path: Path,
) -> None:
    """Launch failure with a proven-clean tree keeps the release path."""
    repo = init_retention_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(repo, next_action="Report it.")
    meta = read_retention_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_failed_launch,
    )

    assert result.error is not None  # the launch failure is still reported
    assert get_claimed_workspaces(project_file) == []


def test_degraded_followup_retains_original_dirty_workspace(
    tmp_path: Path,
) -> None:
    """A follow-up in another checkout does not discharge the dirty original."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo, next_action="Report it.")
    meta = read_retention_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_degraded_launch,
    )

    assert result.error is None
    assert result.launch_result is not None
    assert result.launch_result.launched is True
    assert result.launch_result.degraded_reason
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record["policy_reason"] in {
        "session_owned_dirt",
        "missing_baseline_with_custody",
        "evidence_unavailable",
    }


def test_blocked_continuation_capture_retains_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocked dispatch (records protocol) retains instead of direct release."""
    import sase.monitor._settlement_followup as settlement

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(
        repo,
        monitor_state="failed",
        next_action="Report it.",
        protocol=MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
    )
    meta = read_retention_meta(artifacts_dir)
    monkeypatch.setattr(
        settlement, "_continuation_dispatch_blocked_reason", lambda _m: "blocked"
    )
    monkeypatch.setattr(
        settlement, "_repair_missing_starter_parent", lambda _a, _m: False
    )

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=no_launch_followup,
    )

    assert result.error is not None
    assert result.launch_result is not None
    assert result.launch_result.launched is False
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_same_workspace_successor_does_not_hold(tmp_path: Path) -> None:
    """A confirmed same-workspace successor keeps custody without a hold."""
    from sase.monitor.delivery import (
        new_delivery_record,
        persist_delivery_record,
        transition_delivery,
    )

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(
        repo, outcome="launched", protocol=MONITOR_CONTINUATION_PROTOCOL_LEGACY
    )
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_followup_agent"] = "acme--mon@1"
    write_retention_meta(artifacts_dir, meta)
    key = {
        "monitor_id": "abc123def456",
        "result_id": meta.get("monitor_result_id") or "result",
        "branch": "failed",
    }
    record = new_delivery_record(key, selected_action="continue")
    reserved = transition_delivery(record, "reserved", reserved_identity="acme--mon@1")
    dispatching = transition_delivery(reserved, "dispatching")
    acknowledged = transition_delivery(
        dispatching, "acknowledged", acknowledged_by="acme--mon@1"
    )
    persist_delivery_record(artifacts_dir, acknowledged)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []


def test_stale_launch_label_without_proof_retains_dirty(tmp_path: Path) -> None:
    """A bare launched label with a still-owned dirty claim must retain."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(
        repo, outcome="launched", protocol=MONITOR_CONTINUATION_PROTOCOL_LEGACY
    )
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
