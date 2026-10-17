"""Workspace preparation and stale git-lock tests for axe runner utils.

Split from ``tests.test_axe_runner_utils``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from sase.axe.runner_workspace import (
    WorkspacePreparationError,
    clear_stale_git_index_lock,
    prepare_workspace,
)
from sase.vcs_provider import VCS_DEFAULT_REVISION

__all__ = [
    "test_clear_stale_git_index_lock_keeps_fresh_lock",
    "test_clear_stale_git_index_lock_no_lock_is_noop",
    "test_clear_stale_git_index_lock_removes_abandoned_lock",
    "test_prepare_workspace_clean_fails",
    "test_prepare_workspace_clears_stale_lock_before_clean",
    "test_prepare_workspace_default_parent_sync_failure_fails",
    "test_prepare_workspace_default_parent_sync_not_implemented_passes",
    "test_prepare_workspace_default_parent_syncs_after_checkout",
    "test_prepare_workspace_non_sentinel_passes_through",
    "test_prepare_workspace_update_fails",
]


def _make_index_lock(workspace: Path, *, age_seconds: float) -> Path:
    """Create a ``.git/index.lock`` aged *age_seconds* into the past."""
    git_dir = workspace / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    lock = git_dir / "index.lock"
    lock.write_bytes(b"")
    old = time.time() - age_seconds
    os.utime(lock, (old, old))
    return lock


def test_prepare_workspace_clean_fails() -> None:
    """Test prepare_workspace raises carrying the clean stderr."""
    with (
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean",
            return_value=(False, "clean error"),
        ),
        pytest.raises(WorkspacePreparationError) as exc_info,
    ):
        prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )
    assert "clean error" in exc_info.value.reason
    assert exc_info.value.step == "clean"
    assert exc_info.value.workspace_dir == "/workspace"


def test_prepare_workspace_update_fails() -> None:
    """Test prepare_workspace raises carrying the checkout stderr."""
    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (False, "sase_hg_update failed: update error")
    mock_provider.get_default_parent_revision.return_value = "p4head"

    with (
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean", return_value=(True, None)
        ),
        patch(
            "sase.axe.runner_workspace_prepare.get_vcs_provider",
            return_value=mock_provider,
        ),
        pytest.raises(WorkspacePreparationError) as exc_info,
    ):
        prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )
    assert "update error" in exc_info.value.reason
    assert "p4head" in exc_info.value.reason
    assert exc_info.value.step == "checkout"
    mock_provider.sync_workspace.assert_not_called()


def test_prepare_workspace_default_parent_syncs_after_checkout() -> None:
    """Test default-parent workspace prep checks out then syncs."""
    mock_provider = MagicMock()
    mock_provider.get_default_parent_revision.return_value = "origin/master"
    mock_provider.checkout.return_value = (True, None)
    mock_provider.sync_workspace.return_value = (True, None)

    with (
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean", return_value=(True, None)
        ),
        patch(
            "sase.axe.runner_workspace_prepare.get_vcs_provider",
            return_value=mock_provider,
        ),
    ):
        prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )

    mock_provider.get_default_parent_revision.assert_called_once_with("/workspace")
    mock_provider.checkout.assert_called_once_with("origin/master", "/workspace")
    mock_provider.sync_workspace.assert_called_once_with("/workspace")
    assert mock_provider.method_calls == [
        call.get_default_parent_revision("/workspace"),
        call.checkout("origin/master", "/workspace"),
        call.sync_workspace("/workspace"),
    ]


def test_prepare_workspace_default_parent_sync_failure_fails() -> None:
    """Test default-parent workspace prep raises carrying the sync stderr."""
    mock_provider = MagicMock()
    mock_provider.get_default_parent_revision.return_value = "origin/master"
    mock_provider.checkout.return_value = (True, None)
    mock_provider.sync_workspace.return_value = (False, "sync error")

    with (
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean", return_value=(True, None)
        ),
        patch(
            "sase.axe.runner_workspace_prepare.get_vcs_provider",
            return_value=mock_provider,
        ),
        pytest.raises(WorkspacePreparationError) as exc_info,
    ):
        prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )

    assert "sync error" in exc_info.value.reason
    assert exc_info.value.step == "sync"
    mock_provider.checkout.assert_called_once_with("origin/master", "/workspace")
    mock_provider.sync_workspace.assert_called_once_with("/workspace")


def test_clear_stale_git_index_lock_removes_abandoned_lock(tmp_path: Path) -> None:
    lock = _make_index_lock(tmp_path, age_seconds=3600)

    assert clear_stale_git_index_lock(str(tmp_path)) is True
    assert not lock.exists()


def test_clear_stale_git_index_lock_keeps_fresh_lock(tmp_path: Path) -> None:
    lock = _make_index_lock(tmp_path, age_seconds=0)

    # A lock younger than the age threshold may belong to a live git process.
    assert clear_stale_git_index_lock(str(tmp_path)) is False
    assert lock.exists()


def test_clear_stale_git_index_lock_no_lock_is_noop(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    assert clear_stale_git_index_lock(str(tmp_path)) is False


def test_prepare_workspace_clears_stale_lock_before_clean(tmp_path: Path) -> None:
    """prepare_workspace self-heals an abandoned index.lock before cleaning."""
    lock = _make_index_lock(tmp_path, age_seconds=3600)
    mock_provider = MagicMock()
    mock_provider.get_default_parent_revision.return_value = "origin/master"
    mock_provider.checkout.return_value = (True, None)
    mock_provider.sync_workspace.return_value = (True, None)

    with (
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean", return_value=(True, None)
        ),
        patch(
            "sase.axe.runner_workspace_prepare.get_vcs_provider",
            return_value=mock_provider,
        ),
    ):
        prepare_workspace(
            str(tmp_path), "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )

    assert not lock.exists()


def test_prepare_workspace_default_parent_sync_not_implemented_passes() -> None:
    """Test default-parent workspace prep keeps checkout-only providers working."""
    mock_provider = MagicMock()
    mock_provider.get_default_parent_revision.return_value = "p4head"
    mock_provider.checkout.return_value = (True, None)
    mock_provider.sync_workspace.side_effect = NotImplementedError

    with (
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean", return_value=(True, None)
        ),
        patch(
            "sase.axe.runner_workspace_prepare.get_vcs_provider",
            return_value=mock_provider,
        ),
    ):
        prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )

    mock_provider.checkout.assert_called_once_with("p4head", "/workspace")
    mock_provider.sync_workspace.assert_called_once_with("/workspace")


def test_prepare_workspace_non_sentinel_passes_through() -> None:
    """Test prepare_workspace passes non-sentinel update_target directly."""
    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)

    with (
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean", return_value=(True, None)
        ),
        patch(
            "sase.axe.runner_workspace_prepare.get_vcs_provider",
            return_value=mock_provider,
        ),
    ):
        prepare_workspace("/workspace", "my_cl", "my_branch", backup_suffix="ace")
        # get_default_parent_revision should NOT be called
        mock_provider.get_default_parent_revision.assert_not_called()
        mock_provider.checkout.assert_called_once_with("my_branch", "/workspace")
        mock_provider.sync_workspace.assert_not_called()
