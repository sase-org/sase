from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.attachments.markdown_pdf import (
    MarkdownPdfProgressEvent,
    render_markdown_pdf_attachments,
)


def test_render_markdown_pdf_attachments_writes_artifacts_and_index(tmp_path):
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    source = workspace / "docs" / "notes.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Notes\n")

    def fake_render(src, dest, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF")
        return dest

    with patch(
        "sase.attachments.markdown_pdf.render_markdown_pdf",
        side_effect=fake_render,
    ):
        result = render_markdown_pdf_attachments(
            [str(source)],
            workspace_dir=workspace,
            artifacts_dir=artifacts,
        )

    pdf = artifacts / "markdown_pdfs" / "docs__notes.md.pdf"
    assert result == [str(pdf)]
    assert pdf.read_bytes() == b"%PDF"
    assert json.loads((artifacts / "markdown_pdfs" / "index.json").read_text()) == [
        {"source_path": str(source), "pdf_path": str(pdf)}
    ]


def test_render_markdown_pdf_attachments_skips_failed_sources(tmp_path):
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    source = workspace / "notes.md"
    source.parent.mkdir()
    source.write_text("# Notes\n")

    with patch("sase.attachments.markdown_pdf.render_markdown_pdf", return_value=None):
        result = render_markdown_pdf_attachments(
            [str(source)],
            workspace_dir=workspace,
            artifacts_dir=artifacts,
        )

    assert result == []
    assert not (artifacts / "markdown_pdfs" / "index.json").exists()


def test_render_markdown_pdf_attachments_reports_progress_order(tmp_path):
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    source = workspace / "docs" / "notes.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Notes\n")
    events: list[MarkdownPdfProgressEvent] = []

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
        }.get(name)

    def fake_run(cmd, **kwargs):
        Path(cmd[3]).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
    ):
        result = render_markdown_pdf_attachments(
            [str(source)],
            workspace_dir=workspace,
            artifacts_dir=artifacts,
            progress=events.append,
        )

    assert result == [str(artifacts / "markdown_pdfs" / "docs__notes.md.pdf")]
    assert [event.stage for event in events] == [
        "started",
        "source_started",
        "engine_started",
        "source_succeeded",
        "completed",
    ]
    assert [(event.index, event.total) for event in events[1:4]] == [
        (1, 1),
        (1, 1),
        (1, 1),
    ]
    assert events[-1].generated == 1
    assert events[-1].skipped == 0
