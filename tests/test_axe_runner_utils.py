"""Tests for axe_runner_utils module."""

import json
import os
import signal
import tempfile
from unittest.mock import MagicMock, patch

from sase.axe.runner_utils import (
    _killed_state,
    all_steps_hidden,
    finalize_axe_runner,
    install_sigterm_handler,
    prepare_workspace,
    was_killed,
)
from sase.vcs_provider import VCS_DEFAULT_REVISION


# Tests for all_steps_hidden


def test_all_steps_hidden_all_hidden() -> None:
    """Test returns True when every step has hidden: true."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "steps": [
                {"name": "a", "hidden": True},
                {"name": "b", "hidden": True},
            ]
        }
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is True


def test_all_steps_hidden_mixed() -> None:
    """Test returns False when at least one step is visible."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "steps": [
                {"name": "a", "hidden": True},
                {"name": "b", "hidden": False},
            ]
        }
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is False


def test_all_steps_hidden_no_hidden_key() -> None:
    """Test returns False when steps lack hidden key (defaults to visible)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {"steps": [{"name": "a"}]}
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is False


def test_all_steps_hidden_empty_steps() -> None:
    """Test returns False when steps list is empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state: dict[str, list[object]] = {"steps": []}
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is False


def test_all_steps_hidden_missing_file() -> None:
    """Test returns False when workflow_state.json doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert all_steps_hidden(tmpdir) is False


# Tests for finalize_axe_runner


def test_finalize_axe_runner_success() -> None:
    """Test finalize_axe_runner calls all required functions."""
    mock_cs = MagicMock()
    mock_cs.name = "test_cl"

    update_suffix_calls: list[tuple[object, str, str | None, int]] = []

    def mock_update_suffix(cs: object, pf: str, pid: str | None, ec: int) -> None:
        update_suffix_calls.append((cs, pf, pid, ec))

    with patch(
        "sase.axe.runner_utils.parse_project_file",
        return_value=[mock_cs],
    ):
        finalize_axe_runner(
            project_file="/path/project.gp",
            changespec_name="test_cl",
            proposal_id="abc123",
            exit_code=0,
            update_suffix_fn=mock_update_suffix,
        )

        # Check update_suffix was called
        assert len(update_suffix_calls) == 1
        assert update_suffix_calls[0] == (mock_cs, "/path/project.gp", "abc123", 0)


def test_finalize_axe_runner_no_matching_changespec() -> None:
    """Test finalize_axe_runner skips suffix update when changespec not found."""
    mock_cs = MagicMock()
    mock_cs.name = "other_cl"

    update_suffix_calls: list[tuple[object, str, str | None, int]] = []

    def mock_update_suffix(cs: object, pf: str, pid: str | None, ec: int) -> None:
        update_suffix_calls.append((cs, pf, pid, ec))

    with patch(
        "sase.axe.runner_utils.parse_project_file",
        return_value=[mock_cs],
    ):
        finalize_axe_runner(
            project_file="/path/project.gp",
            changespec_name="test_cl",
            proposal_id="abc123",
            exit_code=0,
            update_suffix_fn=mock_update_suffix,
        )

        # update_suffix should not be called - no matching changespec
        assert len(update_suffix_calls) == 0


def test_finalize_axe_runner_handles_errors() -> None:
    """Test finalize_axe_runner handles errors gracefully."""
    with patch(
        "sase.axe.runner_utils.parse_project_file",
        side_effect=Exception("Parse error"),
    ):
        # Should not raise - errors are caught and printed
        finalize_axe_runner(
            project_file="/path/project.gp",
            changespec_name="test_cl",
            proposal_id=None,
            exit_code=1,
            update_suffix_fn=lambda *args: None,
        )


# Tests for was_killed / install_sigterm_handler
def test_sigterm_handler_sets_killed() -> None:
    """Test that invoking the captured handler sets was_killed to True."""
    _killed_state["killed"] = False
    captured_handler = None

    with patch("sase.axe.runner_utils.signal.signal") as mock_signal:
        install_sigterm_handler("test")
        captured_handler = mock_signal.call_args[0][1]

    # Invoke the handler - it calls sys.exit, so we catch SystemExit
    with patch("sase.axe.runner_utils.sys.exit"):
        captured_handler(signal.SIGTERM, None)

    assert was_killed() is True
    # Reset state
    _killed_state["killed"] = False


# Tests for prepare_workspace
def test_prepare_workspace_clean_fails() -> None:
    """Test prepare_workspace returns False when clean fails."""
    with patch(
        "sase.commit_utils.run_sase_hg_clean", return_value=(False, "clean error")
    ):
        result = prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )
        assert result is False


def test_prepare_workspace_update_fails() -> None:
    """Test prepare_workspace returns False when sase_hg_update returns non-zero."""
    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (False, "sase_hg_update failed: update error")
    mock_provider.get_default_parent_revision.return_value = "p4head"

    with (
        patch("sase.commit_utils.run_sase_hg_clean", return_value=(True, None)),
        patch("sase.axe.runner_utils.get_vcs_provider", return_value=mock_provider),
    ):
        result = prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )
        assert result is False


def test_prepare_workspace_non_sentinel_passes_through() -> None:
    """Test prepare_workspace passes non-sentinel update_target directly."""
    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)

    with (
        patch("sase.commit_utils.run_sase_hg_clean", return_value=(True, None)),
        patch("sase.axe.runner_utils.get_vcs_provider", return_value=mock_provider),
    ):
        result = prepare_workspace(
            "/workspace", "my_cl", "my_branch", backup_suffix="ace"
        )
        assert result is True
        # get_default_parent_revision should NOT be called
        mock_provider.get_default_parent_revision.assert_not_called()
        mock_provider.checkout.assert_called_once_with("my_branch", "/workspace")
