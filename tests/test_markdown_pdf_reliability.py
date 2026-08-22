from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.attachments import markdown_pdf
from sase.attachments.markdown_pdf import (
    MarkdownPdfProgressEvent,
    render_markdown_pdf,
)


def _resource_path(*paths: Path) -> str:
    return os.pathsep.join(
        dict.fromkeys(str(path.expanduser().resolve(strict=False)) for path in paths)
    )


def _write_pandoc_scratch(cwd: Path) -> None:
    (cwd / "toPdfViaTempFile3479326-0.html").write_text(
        "<html><head><title>launch_preview</title></head></html>\n",
        encoding="utf-8",
    )
    (cwd / "toPdfViaTempFile3479326-1.pdf").write_bytes(b"")


def test_render_markdown_pdf_reports_engine_fallback_progress(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"
    events: list[MarkdownPdfProgressEvent] = []

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
            "xelatex": "/usr/bin/xelatex",
        }.get(name)

    def fake_run(cmd, **kwargs):
        engine = next(arg for arg in cmd if arg.startswith("--pdf-engine="))
        if engine == "--pdf-engine=wkhtmltopdf":
            raise subprocess.CalledProcessError(1, cmd)
        Path(cmd[3]).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
    ):
        assert render_markdown_pdf(source, dest, progress=events.append) == dest

    assert [(event.stage, event.engine) for event in events] == [
        ("source_started", None),
        ("engine_started", "wkhtmltopdf"),
        ("engine_started", "xelatex"),
        ("source_succeeded", "xelatex"),
    ]


def test_render_markdown_pdf_returns_none_when_pandoc_missing(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", return_value=None),
        patch("sase.attachments.markdown_pdf.subprocess.run") as run,
    ):
        events: list[MarkdownPdfProgressEvent] = []
        result = render_markdown_pdf(source, dest, progress=events.append)

    assert result is None
    assert not dest.exists()
    run.assert_not_called()
    assert [event.stage for event in events] == ["source_started", "skipped"]
    assert events[-1].reason == "pandoc not found"


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


def test_render_markdown_pdf_reports_unsupported_source_progress(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("# Notes\n")
    events: list[MarkdownPdfProgressEvent] = []

    assert (
        render_markdown_pdf(source, tmp_path / "notes.pdf", progress=events.append)
        is None
    )

    assert [event.stage for event in events] == ["source_started", "skipped"]
    assert events[-1].reason == "unsupported source"


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
        events: list[MarkdownPdfProgressEvent] = []
        result = render_markdown_pdf(source, dest, timeout=1, progress=events.append)

    assert result is None
    assert not dest.exists()
    assert list(tmp_path.glob("*.pdf")) == []
    assert [event.stage for event in events] == [
        "source_started",
        "engine_started",
        "source_failed",
    ]
    assert events[-1].reason == "all PDF engines failed"


def test_render_markdown_pdf_isolates_pandoc_scratch_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = Path("docs")
    docs.mkdir()
    source = docs / "notes.md"
    source.write_text("# Notes\n![diagram](images/diagram.png)\n")
    dest = Path("out") / "notes.pdf"
    captured_cwd: Path | None = None
    captured_cmd: list[str] = []

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
        }.get(name)

    def fake_run(cmd, **kwargs):
        nonlocal captured_cwd, captured_cmd
        captured_cmd = cmd
        cwd = Path(kwargs["cwd"])
        captured_cwd = cwd
        _write_pandoc_scratch(cwd)
        Path(cmd[3]).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
    ):
        result = render_markdown_pdf(source, dest)

    assert result == dest
    assert not result.is_absolute()
    assert dest.read_bytes() == b"%PDF"
    assert captured_cwd is not None
    workdir = captured_cwd.resolve()
    repo = tmp_path.resolve()
    assert workdir.is_absolute()
    assert workdir != repo
    assert not workdir.is_relative_to(repo)
    assert workdir.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert not workdir.exists()
    assert list(tmp_path.rglob("toPdfViaTempFile*")) == []
    assert Path(captured_cmd[1]) == source.resolve()
    assert Path(captured_cmd[3]).is_absolute()
    assert not Path(captured_cmd[3]).is_relative_to(workdir)
    css = Path(markdown_pdf.__file__).with_name("markdown_pdf.css").resolve()
    assert f"--css={css}" in captured_cmd
    assert (
        f"--resource-path={_resource_path(source.parent, Path.cwd())}" in captured_cmd
    )


def test_render_markdown_pdf_isolates_pandoc_scratch_on_timeout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = Path("notes.md")
    source.write_text("# Notes\n")
    dest = Path("notes.pdf")
    captured_cwd: Path | None = None

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "pdflatex": "/usr/bin/pdflatex",
        }.get(name)

    def fake_run(cmd, **kwargs):
        nonlocal captured_cwd
        cwd = Path(kwargs["cwd"])
        captured_cwd = cwd
        _write_pandoc_scratch(cwd)
        Path(cmd[3]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(cmd, timeout=kwargs["timeout"])

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
    ):
        result = render_markdown_pdf(source, dest, timeout=1)

    assert result is None
    assert not dest.exists()
    assert captured_cwd is not None
    workdir = captured_cwd.resolve()
    repo = tmp_path.resolve()
    assert workdir != repo
    assert not workdir.is_relative_to(repo)
    assert not workdir.exists()
    assert list(tmp_path.rglob("toPdfViaTempFile*")) == []
    assert list(tmp_path.glob("*.pdf")) == []
