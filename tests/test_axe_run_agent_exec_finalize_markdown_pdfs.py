"""Tests for run_agent_exec finalize Markdown PDF attachments."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.attachments.markdown_pdf import MAX_MARKDOWN_PDF_ATTACHMENTS
from sase.attachments.markdown_pdf import MarkdownPdfProgressEvent
from sase.axe.run_agent_exec import LoopState, _finalize_loop
from sase.axe.run_agent_exec_retry import RetryTracker

from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._axe_run_agent_exec_helpers import write_markdown_sources


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
