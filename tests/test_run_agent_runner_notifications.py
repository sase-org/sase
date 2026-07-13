"""Tests for run_agent_runner's completion-notification helper.

Specifically guards that hidden agents (lumberjack chops, %hidden,
SASE_AGENT_AUTO_DISMISS) forward ``silent=True`` to
``notify_workflow_complete`` so they don't ping Telegram / bell / unread
count for runs the user never asked to see.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.attachments.markdown_pdf import MAX_MARKDOWN_PDF_ATTACHMENTS
from sase.axe.image_attachments import (
    MAX_COMPLETION_IMAGE_ATTACHMENTS,
    collect_agent_image_paths,
)
from sase.axe.run_agent_phases import build_done_marker
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
        "workflow_name": "toobig_split",
        "success": True,
        "agent_hidden": False,
        "agent_name": None,
        "agent_model": "opus",
        "agent_llm_provider": "claude",
        "error_summary": None,
        "error_report_path": None,
        "saved_path": None,
        "diff_path": None,
        "current_artifacts_dir": str(tmp_path / "agent_artifacts"),
        "markdown_pdf_paths": [],
        "markdown_source_count": None,
        "image_paths": [],
        "video_paths": [],
        "output_path": str(tmp_path / "output.log"),
        "step_output": None,
        "prompt": "#gh:sase #!sase/toobig_split %auto",
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


def test_failed_notification_includes_held_workspace_recovery(base_kwargs):
    base_kwargs.update(
        success=False,
        held_workspace_num=17,
        held_workspace_dir="/tmp/workspace-17",
    )
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    notes = mock_notify.call_args.kwargs["notes"]
    assert any("Workspace #17 is held at /tmp/workspace-17" in note for note in notes)
    assert any("dismiss this agent to release it" in note for note in notes)


def test_success_completion_notification_includes_runtime(base_kwargs):
    base_kwargs["runtime"] = "4m32s"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["runtime"] == "4m32s"


def test_success_completion_notification_includes_output_variables(base_kwargs):
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "output_variables": {
                    "status": "ok",
                    "STOP": "1",
                    "report_path": "dist/report.md",
                }
            }
        )
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["output_variables"] == (
        '{"report_path": "dist/report.md", "status": "ok"}'
    )
    assert json.loads(action_data["output_variables"]) == {
        "report_path": "dist/report.md",
        "status": "ok",
    }


def test_completion_notification_omits_empty_output_variables(base_kwargs):
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"output_variables": {"STOP": "1"}})
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert "output_variables" not in action_data


def test_success_completion_notification_tags_done(base_kwargs):
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "JumpToAgent"
    assert mock_notify.call_args.kwargs["tags"] == ["done"]


def test_failure_completion_notification_is_not_tagged_done(base_kwargs, tmp_path):
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    base_kwargs["success"] = False
    base_kwargs["error_report_path"] = str(error_report)

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    assert mock_notify.call_args.kwargs["tags"] is None


def test_completion_notification_uses_full_commit_result_message(base_kwargs):
    full_message = "feat: add report\n\nInclude full commit body."
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "commit_result.json").write_text(
        json.dumps({"message": full_message, "result": "abc123"})
    )
    base_kwargs["step_output"] = {"meta_commit_message": "feat: add report"}

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["commit_message"] == full_message


def test_completion_notification_reads_commit_result_without_step_output(base_kwargs):
    full_message = "fix: recover after failure\n\nCommit happened before failure."
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "commit_result.json").write_text(
        json.dumps({"message": full_message, "result": "abc123"})
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["commit_message"] == full_message


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


def test_completion_notification_adds_bead_display_for_bead_agent(
    base_kwargs, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "sase.agent.bead_display._lookup_bead_issue", lambda _, **__: None
    )
    base_kwargs["agent_name"] = "sase-x.3"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["bead_display"] == "sase-x.3"


def test_completion_notification_omits_bead_display_for_ordinary_agent(base_kwargs):
    base_kwargs["agent_name"] = "reviewer"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert "bead_display" not in action_data


def test_failure_error_report_notification_adds_bead_display(
    base_kwargs, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "sase.agent.bead_display._lookup_bead_issue", lambda _, **__: None
    )
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    chat = tmp_path / "chat.md"
    diff = tmp_path / "diff.diff"
    base_kwargs["success"] = False
    base_kwargs["agent_name"] = "sase-x.3"
    base_kwargs["error_report_path"] = str(error_report)
    base_kwargs["saved_path"] = str(chat)
    base_kwargs["diff_path"] = str(diff)

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    assert mock_notify.call_args.kwargs["extra_files"][:3] == [
        str(error_report),
        str(chat),
        str(diff),
    ]
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["bead_display"] == "sase-x.3"


def test_failure_error_report_notification_includes_runtime(base_kwargs, tmp_path):
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    base_kwargs["success"] = False
    base_kwargs["error_report_path"] = str(error_report)
    base_kwargs["runtime"] = "1m05s"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["runtime"] == "1m05s"


def test_failure_error_report_notification_includes_output_variables(
    base_kwargs, tmp_path
):
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"output_variables": {"summary_path": "reports/error.md"}})
    )
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    base_kwargs["success"] = False
    base_kwargs["error_report_path"] = str(error_report)

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert json.loads(action_data["output_variables"]) == {
        "summary_path": "reports/error.md"
    }


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


def test_completion_notification_appends_markdown_pdfs_before_images(
    base_kwargs, tmp_path
):
    chat = tmp_path / "chat.md"
    diff = tmp_path / "diff.diff"
    pdf = tmp_path / "markdown_pdfs" / "docs__notes.md.pdf"
    image = tmp_path / "screen.png"
    base_kwargs["saved_path"] = str(chat)
    base_kwargs["diff_path"] = str(diff)
    base_kwargs["markdown_pdf_paths"] = [str(pdf)]
    base_kwargs["image_paths"] = [str(image)]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [
        str(chat),
        str(diff),
        str(pdf),
        str(image),
    ]


def test_completion_notification_appends_videos_after_images(base_kwargs, tmp_path):
    chat = tmp_path / "chat.md"
    diff = tmp_path / "diff.diff"
    pdf = tmp_path / "markdown_pdfs" / "docs__notes.md.pdf"
    image = tmp_path / "screen.png"
    video = tmp_path / "demo.mp4"
    base_kwargs["saved_path"] = str(chat)
    base_kwargs["diff_path"] = str(diff)
    base_kwargs["markdown_pdf_paths"] = [str(pdf)]
    base_kwargs["image_paths"] = [str(image)]
    base_kwargs["video_paths"] = [str(video)]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [
        str(chat),
        str(diff),
        str(pdf),
        str(image),
        str(video),
    ]


def test_completion_notification_dedupes_markdown_pdfs(base_kwargs, tmp_path):
    pdf = tmp_path / "notes.pdf"
    base_kwargs["diff_path"] = str(pdf)
    base_kwargs["markdown_pdf_paths"] = [str(pdf)]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [str(pdf)]


def test_completion_notification_notes_markdown_pdf_limit_exceeded(base_kwargs):
    base_kwargs["markdown_source_count"] = MAX_MARKDOWN_PDF_ATTACHMENTS + 1

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["notes"][-1] == (
        f"Edited {MAX_MARKDOWN_PDF_ATTACHMENTS + 1} Markdown files; skipped PDF "
        f"attachments because the limit is {MAX_MARKDOWN_PDF_ATTACHMENTS}."
    )


def test_completion_notification_has_no_markdown_limit_note_at_threshold(base_kwargs):
    base_kwargs["markdown_source_count"] = MAX_MARKDOWN_PDF_ATTACHMENTS

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    notes = mock_notify.call_args.kwargs["notes"]
    assert len(notes) == 1
    assert "skipped PDF attachments" not in notes[0]


def test_completion_notification_dedupes_image_paths(base_kwargs, tmp_path):
    image = tmp_path / "screen.png"
    base_kwargs["diff_path"] = str(image)
    base_kwargs["image_paths"] = [str(image)]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [str(image)]


def test_completion_notification_attaches_images_at_limit(base_kwargs, tmp_path):
    images = [
        str(tmp_path / f"screen_{index:02d}.png")
        for index in range(MAX_COMPLETION_IMAGE_ATTACHMENTS)
    ]
    base_kwargs["image_paths"] = images

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == images
    assert len(mock_notify.call_args.kwargs["notes"]) == 1


def test_completion_notification_skips_images_above_limit(base_kwargs, tmp_path):
    chat = tmp_path / "chat.md"
    video = tmp_path / "demo.mp4"
    image_count = MAX_COMPLETION_IMAGE_ATTACHMENTS + 1
    base_kwargs["saved_path"] = str(chat)
    base_kwargs["image_paths"] = [
        str(tmp_path / f"screen_{index:02d}.png") for index in range(image_count)
    ]
    base_kwargs["video_paths"] = [str(video)]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [str(chat), str(video)]
    assert mock_notify.call_args.kwargs["notes"][-1] == (
        f"Discovered {image_count} images; skipped image attachments because the "
        f"limit is {MAX_COMPLETION_IMAGE_ATTACHMENTS}."
    )


def test_completion_notification_counts_deduped_image_candidates(base_kwargs, tmp_path):
    already_attached = str(tmp_path / "screen_00.png")
    image_candidates = [
        str(tmp_path / f"screen_{index:02d}.png")
        for index in range(1, MAX_COMPLETION_IMAGE_ATTACHMENTS + 1)
    ]
    base_kwargs["diff_path"] = already_attached
    base_kwargs["image_paths"] = [
        already_attached,
        *image_candidates,
        image_candidates[0],
    ]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [
        already_attached,
        *image_candidates,
    ]
    assert len(mock_notify.call_args.kwargs["notes"]) == 1


def test_completion_notification_dedupes_video_paths(base_kwargs, tmp_path):
    video = tmp_path / "demo.mp4"
    base_kwargs["diff_path"] = str(video)
    base_kwargs["video_paths"] = [str(video)]

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [str(video)]


def test_completion_notification_appends_explicit_artifact_paths(base_kwargs, tmp_path):
    chat = tmp_path / "chat.md"
    explicit = tmp_path / "result.png"
    base_kwargs["saved_path"] = str(chat)
    explicit.write_bytes(b"png")

    with (
        patch(
            "sase.core.agent_artifact_facade.list_explicit_agent_artifacts",
            return_value=[SimpleNamespace(path=str(explicit))],
        ) as list_artifacts,
        patch("sase.notifications.senders.notify_workflow_complete") as mock_notify,
    ):
        send_completion_notification(**base_kwargs)

    list_artifacts.assert_called_once_with(base_kwargs["current_artifacts_dir"])
    assert mock_notify.call_args.kwargs["extra_files"] == [
        str(chat),
        str(explicit),
    ]


def test_completion_notification_dedupes_explicit_artifact_paths(base_kwargs, tmp_path):
    chat = tmp_path / "chat.md"
    diff = tmp_path / "diff.diff"
    pdf = tmp_path / "notes.pdf"
    image = tmp_path / "screen.png"
    video = tmp_path / "demo.mp4"
    explicit = tmp_path / "explicit.txt"
    for path in (chat, diff, pdf, image, video, explicit):
        path.write_text("content\n")
    base_kwargs["saved_path"] = str(chat)
    base_kwargs["diff_path"] = str(diff)
    base_kwargs["markdown_pdf_paths"] = [str(pdf)]
    base_kwargs["image_paths"] = [str(image)]
    base_kwargs["video_paths"] = [str(video)]

    with (
        patch(
            "sase.core.agent_artifact_facade.list_explicit_agent_artifacts",
            return_value=[
                SimpleNamespace(path=str(chat)),
                SimpleNamespace(path=str(pdf)),
                SimpleNamespace(path=str(image)),
                SimpleNamespace(path=str(video)),
                SimpleNamespace(path=str(explicit)),
            ],
        ),
        patch("sase.notifications.senders.notify_workflow_complete") as mock_notify,
    ):
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [
        str(chat),
        str(diff),
        str(pdf),
        str(image),
        str(video),
        str(explicit),
    ]


def test_completion_notification_skips_missing_explicit_artifacts(
    base_kwargs, tmp_path
):
    explicit = tmp_path / "result.png"
    explicit.write_bytes(b"png")

    with (
        patch(
            "sase.core.agent_artifact_facade.list_explicit_agent_artifacts",
            return_value=[
                SimpleNamespace(path=""),
                SimpleNamespace(path=str(tmp_path / "missing.png")),
                SimpleNamespace(path=str(explicit)),
            ],
        ),
        patch("sase.notifications.senders.notify_workflow_complete") as mock_notify,
    ):
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == [str(explicit)]


def test_completion_notification_ignores_explicit_artifact_index_errors(base_kwargs):
    with (
        patch(
            "sase.core.agent_artifact_facade.list_explicit_agent_artifacts",
            side_effect=OSError("index unavailable"),
        ),
        patch("sase.notifications.senders.notify_workflow_complete") as mock_notify,
    ):
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == []


def test_completed_done_marker_includes_markdown_pdf_paths(tmp_path):
    marker = build_done_marker(
        "test-cl",
        "/tmp/project.sase",
        "20260430120000",
        "20260430120000",
        1,
        "/tmp/workspace",
        "/tmp/output.log",
        "completed",
        markdown_pdf_paths=[str(tmp_path / "notes.pdf")],
        video_paths=[str(tmp_path / "demo.mp4")],
    )

    assert marker["markdown_pdf_paths"] == [str(tmp_path / "notes.pdf")]
    assert marker["video_paths"] == [str(tmp_path / "demo.mp4")]
    assert marker["workspace_dir"] == "/tmp/workspace"


def test_completed_done_marker_defaults_empty_markdown_pdf_paths():
    marker = build_done_marker(
        "test-cl",
        "/tmp/project.sase",
        "20260430120000",
        "20260430120000",
        1,
        "/tmp/workspace",
        "/tmp/output.log",
        "completed",
    )

    assert marker["markdown_pdf_paths"] == []
    assert marker["video_paths"] == []


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
