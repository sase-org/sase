"""Tests for run_agent_exec finalize attachment handling."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.attachments.markdown_pdf import MAX_MARKDOWN_PDF_ATTACHMENTS
from sase.attachments.markdown_pdf import MarkdownPdfProgressEvent
from sase.axe.run_agent_exec import AgentExecContext, LoopState, _finalize_loop
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.axe.run_agent_runner_finalize import send_completion_notification
from sase.core.agent_artifact_facade import list_agent_artifacts

from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._axe_run_agent_exec_helpers import run_command
from tests._axe_run_agent_exec_helpers import write_markdown_sources


def test_finalize_loop_records_markdown_pdfs_images_and_notification_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_command(workspace, "git", "init")
    run_command(workspace, "git", "config", "user.email", "test@example.com")
    run_command(workspace, "git", "config", "user.name", "Test User")
    (workspace / "base.txt").write_text("base\n")
    run_command(workspace, "git", "add", ".")
    run_command(workspace, "git", "commit", "-m", "base")

    research = workspace / "sdd" / "research" / "example.md"
    notes = workspace / "docs" / "notes.md"
    image = workspace / "assets" / "diagram.png"
    video = workspace / "assets" / "demo.mp4"
    image_source = str(image.resolve())
    video_source = str(video.resolve())
    research.parent.mkdir(parents=True)
    notes.parent.mkdir()
    image.parent.mkdir()
    research.write_text("# Research\n")
    notes.write_text("# Notes\n")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    video.write_bytes(b"mp4")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "workflow_state.json").write_text(
        json.dumps(
            {
                "steps": [
                    {"output": {"summary": "created markdown and image attachments"}}
                ]
            }
        )
    )
    chat = tmp_path / "chat.md"

    def fake_render_markdown_pdf(src: Path, dest: Path, **kwargs) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"%PDF {src.name}".encode())
        return dest

    ctx = AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(workspace),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260430120000",
        update_target="",
        project_name="test",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260430120000",
        vcs_tag=None,
        agent_name="agent",
        agent_model="model",
        agent_llm_provider="provider",
        agent_vcs_provider="git",
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )
    state = LoopState(
        current_prompt="create attachments",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create attachments",
    )

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
        patch(
            "sase.attachments.markdown_pdf.render_markdown_pdf",
            side_effect=fake_render_markdown_pdf,
        ),
    ):
        result = _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    pdf_dir = artifacts / "markdown_pdfs"
    expected_pdfs = [
        str(pdf_dir / "docs__notes.md.pdf"),
        str(pdf_dir / "sdd__research__example.md.pdf"),
    ]
    assert result.markdown_pdf_paths == expected_pdfs
    assert result.image_paths == [image_source]
    assert result.video_paths == [video_source]

    done = json.loads((artifacts / "done.json").read_text())
    assert done["markdown_pdf_paths"] == expected_pdfs
    assert done["image_paths"] == [image_source]
    assert done["video_paths"] == [video_source]
    assert sorted(path.name for path in pdf_dir.glob("*.pdf")) == [
        "docs__notes.md.pdf",
        "sdd__research__example.md.pdf",
    ]
    assert json.loads((pdf_dir / "index.json").read_text()) == [
        {"source_path": str(notes.resolve()), "pdf_path": expected_pdfs[0]},
        {"source_path": str(research.resolve()), "pdf_path": expected_pdfs[1]},
    ]

    artifact_rows = list_agent_artifacts(artifacts)
    rows_by_source = {
        artifact.source_path: artifact
        for artifact in artifact_rows
        if artifact.source_path
    }
    assert rows_by_source[image_source].kind == "image"
    video_artifact = rows_by_source[video_source]
    assert video_artifact.kind == "file"
    assert video_artifact.explicit is False
    persisted_video_path = Path(video_artifact.path)
    assert persisted_video_path.is_file()

    video.unlink()
    artifact_rows_after_cleanup = list_agent_artifacts(artifacts)
    rows_after_cleanup = {
        artifact.source_path: artifact
        for artifact in artifact_rows_after_cleanup
        if artifact.source_path
    }
    assert rows_after_cleanup[video_source].path == str(persisted_video_path)
    assert Path(rows_after_cleanup[video_source].path).is_file()

    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        send_completion_notification(
            cl_name=ctx.cl_name,
            artifacts_timestamp=ctx.artifacts_timestamp,
            workflow_name="ace-run",
            success=result.success,
            agent_hidden=ctx.agent_hidden,
            agent_name=ctx.agent_name,
            agent_model=ctx.agent_model,
            agent_llm_provider=ctx.agent_llm_provider,
            error_summary=None,
            error_report_path=None,
            saved_path=result.saved_path,
            diff_path=result.diff_path,
            markdown_pdf_paths=result.markdown_pdf_paths,
            image_paths=result.image_paths,
            video_paths=result.video_paths,
            output_path=ctx.output_path,
            step_output=result.step_output,
            prompt=state.original_prompt,
            outcome=result.outcome,
        )

    assert notify.call_args.kwargs["extra_files"] == [
        str(chat),
        *expected_pdfs,
        image_source,
        video_source,
    ]


def test_finalize_loop_renders_markdown_pdfs_at_attachment_limit(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="create markdown",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create markdown",
    )
    chat = tmp_path / "chat.md"
    sources = write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS)

    def fake_render_markdown_pdf(src: Path, dest: Path, **kwargs) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"%PDF {src.name}".encode())
        return dest

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=sources,
        ),
        patch(
            "sase.attachments.markdown_pdf.render_markdown_pdf",
            side_effect=fake_render_markdown_pdf,
        ) as render,
    ):
        result = _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert render.call_count == MAX_MARKDOWN_PDF_ATTACHMENTS
    assert len(result.markdown_pdf_paths) == MAX_MARKDOWN_PDF_ATTACHMENTS
    assert result.markdown_source_count == MAX_MARKDOWN_PDF_ATTACHMENTS


def test_finalize_loop_skips_markdown_pdfs_above_attachment_limit(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="create many markdown files",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create many markdown files",
    )
    chat = tmp_path / "chat.md"
    sources = write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS + 1)

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=sources,
        ),
        patch("sase.attachments.markdown_pdf.render_markdown_pdf") as render,
    ):
        result = _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    render.assert_not_called()
    assert result.markdown_pdf_paths == []
    assert result.markdown_source_count == MAX_MARKDOWN_PDF_ATTACHMENTS + 1

    done = json.loads((Path(ctx.artifacts_dir) / "done.json").read_text())
    assert done["markdown_pdf_paths"] == []


def test_finalize_loop_prints_and_persists_markdown_pdf_progress(
    tmp_path: Path,
    capsys,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": "running",
                "context": {"cl_name": "test-cl"},
                "steps": [],
            }
        )
    )
    source = tmp_path / "docs" / "note.md"
    source.parent.mkdir()
    source.write_text("# Note\n")
    state = LoopState(
        current_prompt="create markdown",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create markdown",
    )
    chat = tmp_path / "chat.md"

    def fake_render_markdown_pdf(
        src: Path,
        dest: Path,
        *,
        progress=None,
        **kwargs,
    ) -> Path:
        if progress is not None:
            progress(
                MarkdownPdfProgressEvent(
                    stage="source_started",
                    source_path=str(src),
                    pdf_path=str(dest),
                )
            )
            progress(
                MarkdownPdfProgressEvent(
                    stage="engine_started",
                    source_path=str(src),
                    pdf_path=str(dest),
                    engine="wkhtmltopdf",
                )
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF")
        if progress is not None:
            progress(
                MarkdownPdfProgressEvent(
                    stage="source_succeeded",
                    source_path=str(src),
                    pdf_path=str(dest),
                    engine="wkhtmltopdf",
                )
            )
        return dest

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[str(source)],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
        patch(
            "sase.attachments.markdown_pdf.render_markdown_pdf",
            side_effect=fake_render_markdown_pdf,
        ),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    output = capsys.readouterr().out
    assert "Preparing PDFs from Markdown... found 1, cap" in output
    assert "[PDF] 1/1 trying wkhtmltopdf: docs/note.md" in output
    workflow_state = json.loads((artifacts / "workflow_state.json").read_text())
    assert workflow_state["pdf_status"] == {
        "stage": "completed",
        "total": 1,
        "generated": 1,
        "skipped": 0,
        "cap": MAX_MARKDOWN_PDF_ATTACHMENTS,
        "active": False,
    }
    assert "activity" not in workflow_state


def test_finalize_loop_records_markdown_pdf_limit_reason(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "workflow_state.json").write_text(
        json.dumps({"workflow_name": "run", "status": "running", "steps": []})
    )
    state = LoopState(
        current_prompt="create many markdown files",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create many markdown files",
    )
    sources = write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS + 1)

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=sources,
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    workflow_state = json.loads((artifacts / "workflow_state.json").read_text())
    assert workflow_state["pdf_status"]["stage"] == "completed"
    assert workflow_state["pdf_status"]["skipped"] == MAX_MARKDOWN_PDF_ATTACHMENTS + 1
    assert workflow_state["pdf_status"]["reason"].startswith("over attachment limit")
