"""Tests for sase.ace.tui.actions.sync._sync_task."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.actions.sync import _sync_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow_result(status: str = "success", message: str = "ok") -> MagicMock:
    """Create a mock WorkflowResult with JSON output."""
    import json

    result = MagicMock()
    result.output = json.dumps({"status": status, "message": message})
    return result


# Patch targets
# Module-level imports in sync.py → patch at the sync module
_PATCH_CLEAN = "sase.ace.tui.actions.sync.run_sase_hg_clean"
_PATCH_VCS = "sase.ace.tui.actions.sync.get_vcs_provider"
# Local imports inside _sync_task → patch at the source module
_PATCH_GET_FIRST = "sase.running_field.get_first_available_axe_workspace"
_PATCH_GET_DIR = "sase.running_field.get_workspace_directory_for_num"
_PATCH_CLAIM = "sase.running_field.claim_workspace"
_PATCH_RELEASE = "sase.running_field.release_workspace"
_PATCH_WORKFLOW = "sase.xprompt.execute_workflow"


@pytest.fixture
def _patch_running_field():
    """Patch workspace management functions with sensible defaults."""
    with (
        patch(_PATCH_GET_FIRST, return_value=100) as m_first,
        patch(_PATCH_GET_DIR, return_value=("/ws/100", None)) as m_dir,
        patch(_PATCH_CLAIM, return_value=True) as m_claim,
        patch(_PATCH_RELEASE) as m_release,
    ):
        yield {
            "get_first": m_first,
            "get_dir": m_dir,
            "claim": m_claim,
            "release": m_release,
        }


@pytest.fixture
def _patch_vcs():
    """Patch VCS provider with successful checkout."""
    provider = MagicMock()
    provider.resolve_revision.return_value = "rev123"
    provider.checkout.return_value = (True, None)
    with patch(_PATCH_VCS, return_value=provider) as m_vcs:
        yield {"vcs": m_vcs, "provider": provider}


@pytest.fixture
def _patch_clean():
    """Patch run_sase_hg_clean to succeed."""
    with patch(_PATCH_CLEAN, return_value=(True, None)) as m_clean:
        yield m_clean


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


class TestSyncTaskSuccess:
    def test_returns_success_on_sync_success(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        result = _make_workflow_result("success", "all good")
        with patch(_PATCH_WORKFLOW, return_value=result):
            success, message = _sync_task("CL-1", "/proj.gp", "proj")

        assert success is True
        assert "Synced CL-1" in message
        assert "all good" in message

    def test_returns_success_on_resolved_status(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        result = _make_workflow_result("resolved", "conflicts resolved")
        with (
            patch(_PATCH_WORKFLOW, return_value=result),
            patch("sase.notifications.senders.notify_sync_result") as m_notify,
        ):
            success, message = _sync_task("CL-1", "/proj.gp", "proj")

        assert success is True
        assert "Synced CL-1" in message
        m_notify.assert_called_once_with("resolved", "CL-1", "/ws/100", "/proj.gp")


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


class TestSyncTaskFailure:
    def test_returns_failure_on_workspace_dir_error(self, _patch_running_field) -> None:
        _patch_running_field["get_dir"].side_effect = RuntimeError("no dir")
        success, message = _sync_task("CL-1", "/proj.gp", "proj")

        assert success is False
        assert "Failed to get workspace directory" in message

    def test_returns_failure_on_claim_failure(self, _patch_running_field) -> None:
        _patch_running_field["claim"].return_value = False
        success, message = _sync_task("CL-1", "/proj.gp", "proj")

        assert success is False
        assert "Failed to claim workspace" in message

    def test_returns_failure_on_checkout_failure(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        _patch_vcs["provider"].checkout.return_value = (False, "bad branch")
        success, message = _sync_task("CL-1", "/proj.gp", "proj")

        assert success is False
        assert "checkout failed" in message

    def test_returns_failure_on_workflow_error_status(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        result = _make_workflow_result("error", "merge conflict")
        with (
            patch(_PATCH_WORKFLOW, return_value=result),
            patch("sase.notifications.senders.notify_sync_result"),
        ):
            success, message = _sync_task("CL-1", "/proj.gp", "proj")

        assert success is False
        assert "sync failed" in message

    def test_returns_failure_on_workflow_execution_error(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        from sase.xprompt.workflow_models import WorkflowExecutionError

        with patch(
            _PATCH_WORKFLOW, side_effect=WorkflowExecutionError("workflow broke")
        ):
            success, message = _sync_task("CL-1", "/proj.gp", "proj")

        assert success is False
        assert "sync workflow failed" in message

    def test_returns_failure_on_unparseable_output(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        result = MagicMock()
        result.output = "not json"
        with (
            patch(_PATCH_WORKFLOW, return_value=result),
            patch("sase.notifications.senders.notify_sync_result"),
        ):
            success, message = _sync_task("CL-1", "/proj.gp", "proj")

        assert success is False
        assert "Failed to parse workflow output" in message


# ---------------------------------------------------------------------------
# Workspace lifecycle
# ---------------------------------------------------------------------------


class TestSyncTaskWorkspaceLifecycle:
    def test_workspace_released_on_success(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        result = _make_workflow_result("success", "ok")
        with patch(_PATCH_WORKFLOW, return_value=result):
            _sync_task("CL-1", "/proj.gp", "proj")

        _patch_running_field["release"].assert_called_once_with(
            "/proj.gp", 100, "sync-CL-1", "CL-1"
        )

    def test_workspace_released_on_checkout_failure(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        _patch_vcs["provider"].checkout.return_value = (False, "bad")
        _sync_task("CL-1", "/proj.gp", "proj")

        _patch_running_field["release"].assert_called_once()

    def test_workspace_released_on_workflow_exception(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        with patch(_PATCH_WORKFLOW, side_effect=Exception("boom")):
            _sync_task("CL-1", "/proj.gp", "proj")

        _patch_running_field["release"].assert_called_once()

    def test_workspace_not_released_on_dir_error(self, _patch_running_field) -> None:
        """Workspace is not claimed if get_workspace_directory_for_num fails,
        so release should not be called."""
        _patch_running_field["get_dir"].side_effect = RuntimeError("no dir")
        _sync_task("CL-1", "/proj.gp", "proj")

        _patch_running_field["release"].assert_not_called()

    def test_workspace_not_released_on_claim_failure(
        self, _patch_running_field
    ) -> None:
        _patch_running_field["claim"].return_value = False
        _sync_task("CL-1", "/proj.gp", "proj")

        _patch_running_field["release"].assert_not_called()


# ---------------------------------------------------------------------------
# SASE_SYNC_CWD env var
# ---------------------------------------------------------------------------


class TestSyncTaskEnvVar:
    def test_env_var_restored_after_success(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        os.environ.pop("SASE_SYNC_CWD", None)
        result = _make_workflow_result("success", "ok")
        with patch(_PATCH_WORKFLOW, return_value=result):
            _sync_task("CL-1", "/proj.gp", "proj")

        assert "SASE_SYNC_CWD" not in os.environ

    def test_env_var_restored_after_failure(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        os.environ.pop("SASE_SYNC_CWD", None)
        with patch(_PATCH_WORKFLOW, side_effect=Exception("boom")):
            _sync_task("CL-1", "/proj.gp", "proj")

        assert "SASE_SYNC_CWD" not in os.environ

    def test_env_var_preserves_previous_value(
        self, _patch_running_field, _patch_vcs, _patch_clean
    ) -> None:
        os.environ["SASE_SYNC_CWD"] = "/original"
        result = _make_workflow_result("success", "ok")
        try:
            with patch(_PATCH_WORKFLOW, return_value=result):
                _sync_task("CL-1", "/proj.gp", "proj")
            assert os.environ["SASE_SYNC_CWD"] == "/original"
        finally:
            os.environ.pop("SASE_SYNC_CWD", None)
