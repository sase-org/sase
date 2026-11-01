"""Tests for stale RUNNING cleanup of ace-monitor and ace-gate claims."""

import importlib.abc
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries
from sase.running_field import WorkspaceClaim


def test_cleanup_keeps_dead_monitor_claim_when_member_not_terminal() -> None:
    """A dead-pid ace-monitor claim is not released until the member is terminal."""
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-monitor",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260813125344"),
        ),
        patch(
            "sase.monitor.store.read_monitor_marker",
            return_value=MagicMock(is_terminal=False),
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 0
    release.assert_not_called()


def test_cleanup_releases_dead_monitor_claim_once_member_is_terminal() -> None:
    """A dead-pid ace-monitor claim releases once the member's own record settles."""
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-monitor",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260813125344"),
        ),
        patch(
            "sase.monitor.store.read_monitor_marker",
            return_value=MagicMock(is_terminal=True),
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 1
    release.assert_called_once_with(
        project_file, 10, "ace-monitor", "feature", caller_tag="stale-cleanup"
    )


def test_cleanup_keeps_dead_gate_claim_when_member_not_terminal() -> None:
    """A dead-pid ace-gate claim is held while its gate shell is pending."""
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-gate",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260813125344"),
        ),
        patch(
            "sase.gate_turn.store.read_gate_turn_marker",
            return_value=MagicMock(is_terminal=False),
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 0
    release.assert_not_called()


def test_cleanup_releases_dead_gate_claim_once_member_is_terminal() -> None:
    """A dead-pid ace-gate claim releases only after shell settlement."""
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-gate",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260813125344"),
        ),
        patch(
            "sase.gate_turn.store.read_gate_turn_marker",
            return_value=MagicMock(is_terminal=True),
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 1
    release.assert_called_once_with(
        project_file, 10, "ace-gate", "feature", caller_tag="stale-cleanup"
    )


def test_cleanup_skip_monitor_claims_leaves_ace_monitor_claims_untouched() -> None:
    """skip_monitor_claims=True never releases ace-monitor claims this sweep."""
    monitor_claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-monitor",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    other_claim = WorkspaceClaim(
        workspace_num=11,
        workflow="run",
        cl_name="other",
        pid=44444,
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[monitor_claim, other_claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.monitor.store.read_monitor_marker",
            return_value=MagicMock(is_terminal=True),
        ) as read_marker,
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        released = cleanup_stale_running_entries(skip_monitor_claims=True)

    assert released == 1
    release.assert_called_once_with(
        project_file, 11, "run", "other", caller_tag="stale-cleanup"
    )
    read_marker.assert_not_called()


def _block_monitor_start_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``sase.monitor.start`` raise SyntaxError on import."""

    import sase.monitor as monitor_pkg

    class _BrokenMonitorStart(importlib.abc.MetaPathFinder):
        def find_spec(
            self,
            fullname: str,
            path: object = None,
            target: object = None,
        ) -> None:
            del path, target
            if fullname == "sase.monitor.start":
                raise SyntaxError("simulated sase.monitor.start syntax error")
            return None

    monkeypatch.setattr(sys, "meta_path", [_BrokenMonitorStart(), *sys.meta_path])
    monkeypatch.delitem(sys.modules, "sase.monitor.start", raising=False)
    if hasattr(monitor_pkg, "start"):
        monkeypatch.delattr(monitor_pkg, "start")


def test_cleanup_skip_monitor_claims_survives_unimportable_monitor_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skip_monitor_claims=True must not import sase.monitor.start."""
    _block_monitor_start_import(monkeypatch)
    monitor_claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-monitor",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    other_claim = WorkspaceClaim(
        workspace_num=11,
        workflow="run",
        cl_name="other",
        pid=44444,
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[monitor_claim, other_claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        released = cleanup_stale_running_entries(skip_monitor_claims=True)

    assert isinstance(released, int)
    assert released == 1
    release.assert_called_once_with(
        project_file, 11, "run", "other", caller_tag="stale-cleanup"
    )


def test_cleanup_imports_monitor_start_when_not_skipping_monitor_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skip_monitor_claims=False still imports sase.monitor.start."""
    _block_monitor_start_import(monkeypatch)
    with pytest.raises(SyntaxError, match="simulated sase.monitor.start syntax error"):
        cleanup_stale_running_entries(skip_monitor_claims=False)
