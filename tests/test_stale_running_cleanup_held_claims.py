"""Tests for stale RUNNING cleanup of held (pinned) workspace claims."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.scheduler.stale_running_cleanup import (
    _held_claim_exceeds_ttl,
    _parse_claim_timestamp,
    cleanup_stale_running_entries,
)
from sase.running_field import WorkspaceClaim


def _pinned_dead_claim(
    *,
    artifacts_timestamp: str = "20260901120000",
) -> WorkspaceClaim:
    return WorkspaceClaim(
        workspace_num=17,
        workflow="run",
        cl_name="feature",
        pid=11111,
        artifacts_timestamp=artifacts_timestamp,
        pinned=True,
    )


def _run_pinned_cleanup(
    *,
    artifacts_exist: bool,
    done_marker_exists: bool,
    ttl_days: int = 14,
    claim: WorkspaceClaim | None = None,
    now: datetime | None = None,
) -> tuple[int, MagicMock]:
    pinned = claim or _pinned_dead_claim()
    project_file = "/tmp/projects/proj/proj.sase"
    clock = now or datetime(2026, 9, 7, 12, 0, 0)
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[pinned],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup._held_agent_artifacts_exist",
            return_value=artifacts_exist,
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup._held_done_marker_exists",
            return_value=done_marker_exists,
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup._held_claim_ttl_days",
            return_value=ttl_days,
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup._now",
            return_value=clock,
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup._matching_hijack_record",
            return_value=None,
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        released = cleanup_stale_running_entries()
    return released, release


def test_cleanup_keeps_held_workspace_while_artifacts_and_done_marker_exist() -> None:
    released, release = _run_pinned_cleanup(
        artifacts_exist=True,
        done_marker_exists=True,
        ttl_days=0,
    )
    assert released == 0
    release.assert_not_called()


def test_cleanup_keeps_terminal_hold_until_configured_ttl_expires() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0)
    recent_stamp = (now - timedelta(days=13)).strftime("%Y%m%d%H%M%S")
    released, release = _run_pinned_cleanup(
        artifacts_exist=True,
        done_marker_exists=True,
        ttl_days=14,
        claim=_pinned_dead_claim(artifacts_timestamp=recent_stamp),
        now=now,
    )
    assert released == 0
    release.assert_not_called()


def test_cleanup_releases_held_workspace_without_done_marker() -> None:
    released, release = _run_pinned_cleanup(
        artifacts_exist=True,
        done_marker_exists=False,
        ttl_days=0,
    )
    assert released == 1
    release.assert_called_once_with(
        "/tmp/projects/proj/proj.sase",
        17,
        "run",
        "feature",
        caller_tag="stale-cleanup",
        expected_pid=11111,
        artifacts_timestamp="20260901120000",
    )


def test_cleanup_releases_held_workspace_after_artifacts_are_deleted() -> None:
    released, release = _run_pinned_cleanup(
        artifacts_exist=False,
        done_marker_exists=False,
        ttl_days=0,
    )
    assert released == 1
    release.assert_called_once_with(
        "/tmp/projects/proj/proj.sase",
        17,
        "run",
        "feature",
        caller_tag="stale-cleanup",
        expected_pid=11111,
        artifacts_timestamp="20260901120000",
    )


def test_cleanup_releases_held_workspace_older_than_ttl() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0)
    old_stamp = (now - timedelta(days=15)).strftime("%Y%m%d%H%M%S")
    released, release = _run_pinned_cleanup(
        artifacts_exist=True,
        done_marker_exists=True,
        ttl_days=14,
        claim=_pinned_dead_claim(artifacts_timestamp=old_stamp),
        now=now,
    )
    assert released == 1
    release.assert_called_once_with(
        "/tmp/projects/proj/proj.sase",
        17,
        "run",
        "feature",
        caller_tag="stale-cleanup",
        expected_pid=11111,
        artifacts_timestamp=old_stamp,
    )


def test_cleanup_keeps_held_workspace_younger_than_ttl() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0)
    young_stamp = (now - timedelta(days=13)).strftime("%Y%m%d%H%M%S")
    released, release = _run_pinned_cleanup(
        artifacts_exist=True,
        done_marker_exists=True,
        ttl_days=14,
        claim=_pinned_dead_claim(artifacts_timestamp=young_stamp),
        now=now,
    )
    assert released == 0
    release.assert_not_called()


def test_cleanup_ttl_zero_disables_age_based_release() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0)
    ancient_stamp = (now - timedelta(days=400)).strftime("%Y%m%d%H%M%S")
    released, release = _run_pinned_cleanup(
        artifacts_exist=True,
        done_marker_exists=True,
        ttl_days=0,
        claim=_pinned_dead_claim(artifacts_timestamp=ancient_stamp),
        now=now,
    )
    assert released == 0
    release.assert_not_called()


def test_cleanup_keeps_held_workspace_with_unparseable_timestamp() -> None:
    released, release = _run_pinned_cleanup(
        artifacts_exist=True,
        done_marker_exists=True,
        ttl_days=14,
        claim=_pinned_dead_claim(artifacts_timestamp="not-a-timestamp"),
    )
    assert released == 0
    release.assert_not_called()


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("20260907120000", datetime(2026, 9, 7, 12, 0, 0)),
        ("20260907_120000", datetime(2026, 9, 7, 12, 0, 0)),
        ("260907_120000", datetime(2026, 9, 7, 12, 0, 0)),
        ("nope", None),
    ],
)
def test_parse_claim_timestamp(stamp: str, expected: datetime | None) -> None:
    assert _parse_claim_timestamp(stamp) == expected


def test_held_claim_exceeds_ttl_boundaries() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0)
    older = (now - timedelta(days=15)).strftime("%Y%m%d%H%M%S")
    younger = (now - timedelta(days=13)).strftime("%Y%m%d%H%M%S")
    assert _held_claim_exceeds_ttl(older, 14, now=now) is True
    assert _held_claim_exceeds_ttl(younger, 14, now=now) is False
    assert _held_claim_exceeds_ttl(older, 0, now=now) is False
    assert _held_claim_exceeds_ttl("not-a-timestamp", 14, now=now) is False


@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize("age,ttl", [(13, 14), (15, 14), (400, 0)])
def test_staged_origin_retains_claim_before_and_after_receipt(
    tmp_path, monkeypatch, pinned, age, ttl
):
    """Pending adoption keeps custody until settlement or ownership transfer."""
    import sase.ace.scheduler.stale_running_cleanup as cleanup

    artifacts = tmp_path / "origin"
    artifacts.mkdir()
    claim = WorkspaceClaim(
        workspace_num=2,
        workflow="ace-run",
        cl_name="agent",
        pid=12345,
        artifacts_timestamp="20200101120000",
        pinned=pinned,
    )
    monkeypatch.setattr(
        cleanup, "_get_all_project_files", lambda: [str(tmp_path / "proj/proj.sase")]
    )
    monkeypatch.setattr(cleanup, "get_claimed_workspaces", lambda _: [claim])
    monkeypatch.setattr(cleanup, "is_process_running", lambda _: False)
    monkeypatch.setattr(cleanup, "_held_claim_ttl_days", lambda: ttl)
    monkeypatch.setattr(
        cleanup, "_now", lambda: datetime(2020, 1, 1, 12) + timedelta(days=age)
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
        lambda *_: artifacts,
    )
    release = MagicMock()
    monkeypatch.setattr(cleanup, "release_workspace", release)
    (artifacts / ".sase_handoff_staged.json").write_text(
        "malformed evidence still owns custody"
    )
    expired = pinned and ttl > 0 and age > ttl
    assert cleanup_stale_running_entries() == int(expired)
    (artifacts / ".sase_handoff_adopted.json").write_text('{"outcome":"adopted"}')
    assert cleanup_stale_running_entries() == int(expired)
    assert release.call_count == (2 if expired else 0)
