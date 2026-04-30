"""Tests for run_agent_runner's completion-notification helper.

Specifically guards that hidden agents (lumberjack chops, %hidden,
SASE_AGENT_AUTO_DISMISS) forward ``silent=True`` to
``notify_workflow_complete`` so they don't ping Telegram / bell / unread
count for runs the user never asked to see.
"""

from unittest.mock import patch

import pytest

from sase.axe.image_attachments import collect_agent_image_paths
from sase.axe.run_agent_runner_finalize import (
    classify_exec_success,
    send_completion_notification,
)


@pytest.fixture
def base_kwargs(tmp_path):
    """Minimal valid args; tests override only the bits they care about."""
    return {
        "cl_name": "test-cl",
        "artifacts_timestamp": "20260425232621",
        "workflow_name": "pylimit_split",
        "success": True,
        "agent_hidden": False,
        "agent_name": None,
        "agent_model": "opus",
        "agent_llm_provider": "claude",
        "error_summary": None,
        "error_report_path": None,
        "saved_path": None,
        "diff_path": None,
        "image_paths": [],
        "output_path": str(tmp_path / "output.log"),
        "step_output": None,
        "prompt": "#gh:sase #!sase/pylimit_split %approve",
    }


def test_hidden_agent_forwards_silent_true(base_kwargs):
    base_kwargs["agent_hidden"] = True
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_count == 1
    assert mock_notify.call_args.kwargs["silent"] is True


def test_visible_agent_forwards_silent_false(base_kwargs):
    base_kwargs["agent_hidden"] = False
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_count == 1
    assert mock_notify.call_args.kwargs["silent"] is False


def test_hidden_agent_failure_still_silent(base_kwargs):
    """Hidden runs are silent for failures too — matches sibling runners."""
    base_kwargs["agent_hidden"] = True
    base_kwargs["success"] = False
    base_kwargs["error_summary"] = "boom"
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["silent"] is True
    assert mock_notify.call_args.kwargs["success"] is False


def test_plan_rejected_suppresses_completion_notification(base_kwargs):
    base_kwargs["success"] = True
    base_kwargs["outcome"] = "plan_rejected"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    mock_notify.assert_not_called()


def test_plan_rejected_classifies_as_runner_success():
    assert classify_exec_success(success=False, outcome="plan_rejected") is True


def test_real_failure_stays_runner_failure():
    assert classify_exec_success(success=False, outcome="killed") is False


def test_completion_notification_appends_image_paths_after_standard_files(
    base_kwargs, tmp_path
):
    chat = tmp_path / "chat.md"
    diff = tmp_path / "diff.diff"
    image = tmp_path / "screen.png"
    base_kwargs["saved_path"] = str(chat)
    base_kwargs["diff_path"] = str(diff)
    base_kwargs["image_paths"] = [str(image)]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [
        str(chat),
        str(diff),
        str(image),
    ]


def test_completion_notification_dedupes_image_paths(base_kwargs, tmp_path):
    image = tmp_path / "screen.png"
    base_kwargs["diff_path"] = str(image)
    base_kwargs["image_paths"] = [str(image)]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [str(image)]


def test_collect_agent_image_paths_from_working_tree(tmp_path):
    _run(tmp_path, "git", "init")
    _run(tmp_path, "git", "config", "user.email", "test@example.com")
    _run(tmp_path, "git", "config", "user.name", "Test User")
    (tmp_path / "existing.txt").write_text("base\n")
    (tmp_path / "changed.png").write_bytes(b"old")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "changed.png").write_bytes(b"new")
    (tmp_path / "new.webp").write_bytes(b"webp")
    (tmp_path / "notes.txt").write_text("ignore\n")

    assert collect_agent_image_paths(str(tmp_path)) == [
        str((tmp_path / "changed.png").resolve()),
        str((tmp_path / "new.webp").resolve()),
    ]


def test_collect_agent_image_paths_ignores_deleted_missing_and_non_images(tmp_path):
    _run(tmp_path, "git", "init")
    _run(tmp_path, "git", "config", "user.email", "test@example.com")
    _run(tmp_path, "git", "config", "user.name", "Test User")
    (tmp_path / "deleted.gif").write_bytes(b"gif")
    (tmp_path / "notes.txt").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "deleted.gif").unlink()
    (tmp_path / "notes.txt").write_text("changed\n")
    (tmp_path / "missing.jpg").write_bytes(b"jpg")
    diff_path = tmp_path / "proposal.diff"
    diff_path.write_text(
        "diff --git a/missing.jpg b/missing.jpg\n"
        "new file mode 100644\n"
        "+++ b/missing.jpg\n"
    )
    (tmp_path / "missing.jpg").unlink()

    assert collect_agent_image_paths(str(tmp_path), diff_path=str(diff_path)) == []


def test_collect_agent_image_paths_from_diff_file_when_tree_clean(tmp_path):
    image = tmp_path / "result.jpeg"
    image.write_bytes(b"jpeg")
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        "diff --git a/result.jpeg b/result.jpeg\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/result.jpeg\n"
    )

    assert collect_agent_image_paths(str(tmp_path), diff_path=str(diff_path)) == [
        str(image.resolve())
    ]


def test_collect_agent_image_paths_from_head_commit(tmp_path):
    _run(tmp_path, "git", "init")
    _run(tmp_path, "git", "config", "user.email", "test@example.com")
    _run(tmp_path, "git", "config", "user.name", "Test User")
    (tmp_path / "base.txt").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    image = tmp_path / "committed.jpg"
    image.write_bytes(b"jpg")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "add image")

    assert collect_agent_image_paths(str(tmp_path), include_head_commit=True) == [
        str(image.resolve())
    ]


def _run(cwd, *args):
    import subprocess

    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
