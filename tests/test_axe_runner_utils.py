"""Tests for axe_runner_utils module."""

import json
import os
import signal
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from sase.ace.agent_tags import REVIEW_AGENT_TAG
from sase.axe.runner_artifacts import (
    all_steps_hidden,
    clear_agent_meta_tag,
    detect_write_and_persist_review_agent_meta,
    write_done_marker,
)
from sase.axe.runner_reporting import finalize_axe_runner
from sase.axe.runner_signals import (
    _killed_state,
    install_sigterm_handler,
    killed_at,
    reset_killed,
    was_killed,
)
from sase.axe.runner_workspace import (
    clear_stale_git_index_lock,
    prepare_workspace,
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


def test_all_steps_hidden_skipped_steps_ignored() -> None:
    """Test returns True when non-hidden steps were all skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "steps": [
                {"name": "a", "hidden": True, "status": "completed"},
                {"name": "b", "hidden": False, "status": "skipped"},
            ]
        }
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is True


def test_all_steps_hidden_visible_completed_step() -> None:
    """Test returns False when a non-hidden step actually ran."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "steps": [
                {"name": "a", "hidden": True, "status": "completed"},
                {"name": "b", "hidden": False, "status": "completed"},
            ]
        }
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is False


def test_write_done_marker_can_write_visible_review_agent() -> None:
    """Review agents should complete without forcing hidden rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        calls: list[str] = []
        with patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ):
            write_done_marker(
                tmpdir,
                cl_name="my_cl",
                project_file="/tmp/project.sase",
                timestamp="260506_120000",
                exit_code=0,
                hidden=False,
            )

        with open(os.path.join(tmpdir, "done.json"), encoding="utf-8") as f:
            data = json.load(f)

        assert data["outcome"] == "completed"
        assert data["artifacts_timestamp"] == "20260506120000"
        assert "hidden" not in data
        assert calls == [tmpdir]


def test_detect_write_and_persist_review_agent_meta(tmp_path: Path) -> None:
    """Specialized review runners persist the same tag as %tribe:review."""
    artifacts_dir = tmp_path / "crs" / "20260506120000"
    artifacts_dir.mkdir(parents=True)
    tag_file = tmp_path / "agent_tags.json"

    mock_provider = MagicMock()
    mock_provider.resolve_model_name.return_value = "test-model"
    calls: list[str] = []

    with (
        patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test-provider",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=mock_provider),
        patch(
            "sase.workspace_provider.detect_workflow_type",
            return_value="git",
        ),
        patch("sase.workspace_provider.get_display_name", return_value="Git"),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
    ):
        detect_write_and_persist_review_agent_meta(
            str(artifacts_dir),
            "/tmp/project.sase",
            "my_cl",
        )

    with open(artifacts_dir / "agent_meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    with open(tag_file, encoding="utf-8") as f:
        tags = json.load(f)

    assert meta["tag"] == REVIEW_AGENT_TAG
    assert tags == [
        {
            "id": ["run", "my_cl", "20260506120000"],
            "tag": REVIEW_AGENT_TAG,
        }
    ]
    assert calls == [str(artifacts_dir)]


def test_clear_agent_meta_tag_removes_only_tag(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "agent" / "20260623120000"
    artifacts_dir.mkdir(parents=True)
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(
        json.dumps({"name": "foo.bar", "tag": "foo", "model": "test-model"}),
        encoding="utf-8",
    )
    calls: list[str] = []

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        assert clear_agent_meta_tag(str(artifacts_dir)) is True

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    assert meta == {"name": "foo.bar", "model": "test-model"}
    assert calls == [str(artifacts_dir)]


def test_clear_agent_meta_tag_safe_noops(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing"
    assert clear_agent_meta_tag(str(missing_dir)) is False

    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "foo.bar"}), encoding="utf-8")
    assert clear_agent_meta_tag(str(artifacts_dir)) is False
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {"name": "foo.bar"}

    meta_path.write_text("{not-json", encoding="utf-8")
    assert clear_agent_meta_tag(str(artifacts_dir)) is False


# Tests for finalize_axe_runner


def test_finalize_axe_runner_success() -> None:
    """Test finalize_axe_runner calls all required functions."""
    mock_cs = MagicMock()
    mock_cs.name = "test_cl"

    update_suffix_calls: list[tuple[object, str, str | None, int]] = []

    def mock_update_suffix(cs: object, pf: str, pid: str | None, ec: int) -> None:
        update_suffix_calls.append((cs, pf, pid, ec))

    with patch(
        "sase.axe.runner_reporting.parse_project_file",
        return_value=[mock_cs],
    ):
        finalize_axe_runner(
            project_file="/path/project.sase",
            changespec_name="test_cl",
            proposal_id="abc123",
            exit_code=0,
            update_suffix_fn=mock_update_suffix,
        )

        # Check update_suffix was called
        assert len(update_suffix_calls) == 1
        assert update_suffix_calls[0] == (mock_cs, "/path/project.sase", "abc123", 0)


def test_finalize_axe_runner_no_matching_changespec() -> None:
    """Test finalize_axe_runner skips suffix update when changespec not found."""
    mock_cs = MagicMock()
    mock_cs.name = "other_cl"

    update_suffix_calls: list[tuple[object, str, str | None, int]] = []

    def mock_update_suffix(cs: object, pf: str, pid: str | None, ec: int) -> None:
        update_suffix_calls.append((cs, pf, pid, ec))

    with patch(
        "sase.axe.runner_reporting.parse_project_file",
        return_value=[mock_cs],
    ):
        finalize_axe_runner(
            project_file="/path/project.sase",
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
        "sase.axe.runner_reporting.parse_project_file",
        side_effect=Exception("Parse error"),
    ):
        # Should not raise - errors are caught and printed
        finalize_axe_runner(
            project_file="/path/project.sase",
            changespec_name="test_cl",
            proposal_id=None,
            exit_code=1,
            update_suffix_fn=lambda *args: None,
        )


# Tests for was_killed / install_sigterm_handler
def test_sigterm_handler_sets_killed() -> None:
    """Test that invoking the captured handler sets was_killed to True."""
    reset_killed()
    captured_handler = None

    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test")
        captured_handler = mock_signal.call_args[0][1]

    # Invoke the handler - it calls sys.exit, so we catch SystemExit
    with (
        patch("sase.axe.runner_signals.sys.exit"),
        patch("sase.axe.runner_signals.time.time", return_value=123.456),
    ):
        captured_handler(signal.SIGTERM, None)

    assert was_killed() is True
    assert killed_at() == 123.456
    # Reset state
    reset_killed()


def test_sigterm_handler_runs_cleanup_callback() -> None:
    """SIGTERM handlers can run best-effort cleanup before exiting."""
    reset_killed()
    cleanup = MagicMock()

    with patch("sase.axe.runner_signals.signal.signal") as mock_signal:
        install_sigterm_handler("test", on_signal=cleanup)
        captured_handler = mock_signal.call_args[0][1]

    with (
        patch("sase.axe.runner_signals.sys.exit"),
        patch("sase.axe.runner_signals.time.time", return_value=123.456),
    ):
        captured_handler(signal.SIGTERM, None)

    cleanup.assert_called_once_with()
    assert was_killed() is True
    reset_killed()


def test_reset_killed_clears_timestamp() -> None:
    """reset_killed clears both the boolean kill flag and timestamp."""
    _killed_state["killed"] = True
    _killed_state["killed_at"] = 42.0

    reset_killed()

    assert was_killed() is False
    assert killed_at() is None


# Tests for prepare_workspace
def test_prepare_workspace_clean_fails() -> None:
    """Test prepare_workspace returns False when clean fails."""
    with patch(
        "sase.workflows.commit_utils.run_sase_hg_clean",
        return_value=(False, "clean error"),
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
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean", return_value=(True, None)
        ),
        patch("sase.axe.runner_workspace.get_vcs_provider", return_value=mock_provider),
    ):
        result = prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )
        assert result is False
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
        patch("sase.axe.runner_workspace.get_vcs_provider", return_value=mock_provider),
    ):
        result = prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )

    assert result is True
    mock_provider.get_default_parent_revision.assert_called_once_with("/workspace")
    mock_provider.checkout.assert_called_once_with("origin/master", "/workspace")
    mock_provider.sync_workspace.assert_called_once_with("/workspace")
    assert mock_provider.method_calls == [
        call.get_default_parent_revision("/workspace"),
        call.checkout("origin/master", "/workspace"),
        call.sync_workspace("/workspace"),
    ]


def test_prepare_workspace_default_parent_sync_failure_fails() -> None:
    """Test default-parent workspace prep fails when sync fails."""
    mock_provider = MagicMock()
    mock_provider.get_default_parent_revision.return_value = "origin/master"
    mock_provider.checkout.return_value = (True, None)
    mock_provider.sync_workspace.return_value = (False, "sync error")

    with (
        patch(
            "sase.workflows.commit_utils.run_sase_hg_clean", return_value=(True, None)
        ),
        patch("sase.axe.runner_workspace.get_vcs_provider", return_value=mock_provider),
    ):
        result = prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )

    assert result is False
    mock_provider.checkout.assert_called_once_with("origin/master", "/workspace")
    mock_provider.sync_workspace.assert_called_once_with("/workspace")


# Tests for clear_stale_git_index_lock


def _make_index_lock(workspace: Path, *, age_seconds: float) -> Path:
    """Create a ``.git/index.lock`` aged *age_seconds* into the past."""
    git_dir = workspace / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    lock = git_dir / "index.lock"
    lock.write_bytes(b"")
    old = time.time() - age_seconds
    os.utime(lock, (old, old))
    return lock


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
        patch("sase.axe.runner_workspace.get_vcs_provider", return_value=mock_provider),
    ):
        result = prepare_workspace(
            str(tmp_path), "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )

    assert result is True
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
        patch("sase.axe.runner_workspace.get_vcs_provider", return_value=mock_provider),
    ):
        result = prepare_workspace(
            "/workspace", "my_cl", VCS_DEFAULT_REVISION, backup_suffix="ace"
        )

    assert result is True
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
        patch("sase.axe.runner_workspace.get_vcs_provider", return_value=mock_provider),
    ):
        result = prepare_workspace(
            "/workspace", "my_cl", "my_branch", backup_suffix="ace"
        )
        assert result is True
        # get_default_parent_revision should NOT be called
        mock_provider.get_default_parent_revision.assert_not_called()
        mock_provider.checkout.assert_called_once_with("my_branch", "/workspace")
        mock_provider.sync_workspace.assert_not_called()
