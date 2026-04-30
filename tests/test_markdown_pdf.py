from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.attachments.markdown_pdf import (
    render_markdown_pdf,
    render_markdown_pdf_attachments,
)


def test_render_markdown_pdf_uses_first_available_engine(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "out" / "notes.pdf"

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
        patch(
            "sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run
        ) as run,
    ):
        result = render_markdown_pdf(source, dest)

    assert result == dest
    assert dest.read_bytes() == b"%PDF"
    cmd = run.call_args.args[0]
    assert cmd[:3] == ["/usr/bin/pandoc", str(source), "-o"]
    assert cmd[4:] == [
        "--pdf-engine=wkhtmltopdf",
        "--highlight-style=tango",
        "--metadata",
        "title=notes",
    ]


def test_render_markdown_pdf_falls_back_to_latex_engine(tmp_path):
    source = tmp_path / "notes.markdown"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"
    seen_engines: list[str] = []

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
            "xelatex": "/usr/bin/xelatex",
        }.get(name)

    def fake_run(cmd, **kwargs):
        engine = next(arg for arg in cmd if arg.startswith("--pdf-engine="))
        seen_engines.append(engine)
        if engine == "--pdf-engine=wkhtmltopdf":
            Path(cmd[3]).write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, cmd, stderr=b"failed")
        Path(cmd[3]).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
    ):
        result = render_markdown_pdf(source, dest)

    assert result == dest
    assert dest.read_bytes() == b"%PDF"
    assert seen_engines == ["--pdf-engine=wkhtmltopdf", "--pdf-engine=xelatex"]


def test_render_markdown_pdf_returns_none_when_pandoc_missing(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", return_value=None),
        patch("sase.attachments.markdown_pdf.subprocess.run") as run,
    ):
        result = render_markdown_pdf(source, dest)

    assert result is None
    assert not dest.exists()
    run.assert_not_called()


def test_render_markdown_pdf_returns_none_when_no_engine_available(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"

    def fake_which(name: str) -> str | None:
        return "/usr/bin/pandoc" if name == "pandoc" else None

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run") as run,
    ):
        result = render_markdown_pdf(source, dest)

    assert result is None
    assert not dest.exists()
    run.assert_not_called()


def test_render_markdown_pdf_rejects_non_markdown_and_non_pdf_dest(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("# Notes\n")

    assert render_markdown_pdf(source, tmp_path / "notes.pdf") is None
    assert render_markdown_pdf(tmp_path / "missing.md", tmp_path / "notes.pdf") is None
    assert (
        render_markdown_pdf(source.with_suffix(".md"), tmp_path / "notes.txt") is None
    )


def test_render_markdown_pdf_removes_failed_partial_output(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "pdflatex": "/usr/bin/pdflatex",
        }.get(name)

    def fake_run(cmd, **kwargs):
        Path(cmd[3]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(cmd, timeout=kwargs["timeout"])

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
    ):
        result = render_markdown_pdf(source, dest, timeout=1)

    assert result is None
    assert not dest.exists()
    assert list(tmp_path.glob("*.pdf")) == []


def test_render_markdown_pdf_attachments_writes_artifacts_and_index(tmp_path):
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    source = workspace / "docs" / "notes.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Notes\n")

    def fake_render(src, dest):
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
