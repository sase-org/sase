"""Tests for attachments on run-agent-runner completion notifications."""

from types import SimpleNamespace
from unittest.mock import patch

from sase.attachments.markdown_pdf import MAX_MARKDOWN_PDF_ATTACHMENTS
from sase.axe.image_attachments import MAX_COMPLETION_IMAGE_ATTACHMENTS
from sase.axe.run_agent_runner_finalize import send_completion_notification

pytest_plugins = ("tests._run_agent_runner_notification_fixtures",)


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
            "sase.core.artifact_file_facade.list_explicit_artifact_files",
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
            "sase.core.artifact_file_facade.list_explicit_artifact_files",
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
            "sase.core.artifact_file_facade.list_explicit_artifact_files",
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
            "sase.core.artifact_file_facade.list_explicit_artifact_files",
            side_effect=OSError("index unavailable"),
        ),
        patch("sase.notifications.senders.notify_workflow_complete") as mock_notify,
    ):
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["extra_files"] == []
