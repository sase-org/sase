from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.attachments import markdown_pdf
from sase.attachments.markdown_pdf import (
    MarkdownPdfProgressEvent,
    MarkdownPdfProfile,
    render_launch_preview_pdf,
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
        f"--css={Path(markdown_pdf.__file__).with_name('markdown_pdf.css')}",
        "--pdf-engine-opt=--page-width",
        "--pdf-engine-opt=4.25in",
        "--pdf-engine-opt=--page-height",
        "--pdf-engine-opt=7in",
        "--pdf-engine-opt=--margin-top",
        "--pdf-engine-opt=0.22in",
        "--pdf-engine-opt=--margin-right",
        "--pdf-engine-opt=0.22in",
        "--pdf-engine-opt=--margin-bottom",
        "--pdf-engine-opt=0.22in",
        "--pdf-engine-opt=--margin-left",
        "--pdf-engine-opt=0.22in",
        "--metadata",
        "title=notes",
    ]


def test_render_markdown_pdf_uses_default_css_when_unspecified(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"

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
    cmd = run.call_args.args[0]
    assert f"--css={Path(markdown_pdf.__file__).with_name('markdown_pdf.css')}" in cmd


def test_render_markdown_pdf_explicit_css_overrides_default(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"
    css = tmp_path / "custom.css"
    css.write_text("body { color: black; }\n")

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
        result = render_markdown_pdf(source, dest, css_path=css)

    assert result == dest
    cmd = run.call_args.args[0]
    assert f"--css={css}" in cmd
    assert (
        f"--css={Path(markdown_pdf.__file__).with_name('markdown_pdf.css')}" not in cmd
    )


def test_render_markdown_pdf_accepts_syntax_definitions_and_no_auto_title(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("```demo\nhello\n```\n", encoding="utf-8")
    dest = tmp_path / "notes.pdf"
    syntax = tmp_path / "demo.xml"
    syntax.write_text("<language/>\n", encoding="utf-8")

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
        result = render_markdown_pdf(
            source,
            dest,
            syntax_definitions=[syntax],
            include_auto_title=False,
        )

    assert result == dest
    cmd = run.call_args.args[0]
    assert f"--syntax-definition={syntax}" in cmd
    assert "--metadata" not in cmd
    assert "title=notes" not in cmd


def test_render_launch_preview_pdf_uses_dedicated_assets(tmp_path):
    source = tmp_path / "launch_preview.md"
    source.write_text("# Launch Preview\n\n```sase\n#plan\n```\n", encoding="utf-8")
    dest = tmp_path / "launch_preview.pdf"

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
        result = render_launch_preview_pdf(source, dest)

    assert result == dest
    cmd = run.call_args.args[0]
    assert f"--css={Path(markdown_pdf.__file__).with_name('launch_preview.css')}" in cmd
    assert (
        f"--syntax-definition={Path(markdown_pdf.__file__).with_name('sase.xml')}"
        in cmd
    )
    assert "--metadata" not in cmd


def test_render_launch_preview_pdf_falls_back_to_generic_renderer(tmp_path):
    source = tmp_path / "launch_preview.md"
    source.write_text("# Launch Preview\n", encoding="utf-8")
    dest = tmp_path / "launch_preview.pdf"

    def fake_render(src, pdf, **kwargs):
        if kwargs.get("syntax_definitions"):
            return None
        Path(pdf).write_bytes(b"%PDF")
        return Path(pdf)

    with patch(
        "sase.attachments.markdown_pdf.render_markdown_pdf",
        side_effect=fake_render,
    ) as render:
        assert render_launch_preview_pdf(source, dest) == dest

    first = render.call_args_list[0]
    second = render.call_args_list[1]
    assert first.args == (source, dest)
    assert first.kwargs["css_path"] == Path(markdown_pdf.__file__).with_name(
        "launch_preview.css"
    )
    assert first.kwargs["syntax_definitions"] == [
        Path(markdown_pdf.__file__).with_name("sase.xml")
    ]
    assert first.kwargs["include_auto_title"] is False
    assert first.kwargs["include_properties"] is False
    assert second.args == (source, dest)
    assert "css_path" not in second.kwargs
    assert "syntax_definitions" not in second.kwargs
    assert second.kwargs["include_properties"] is False


def test_render_markdown_pdf_custom_profile_updates_wkhtmltopdf_and_css(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"
    profile = MarkdownPdfProfile(
        page_width="8.50in",
        page_height="4.25in",
        margin="0.18in",
        css_font_size="18px",
        latex_font_size="13pt",
        line_stretch="1.4",
    )
    seen_css: list[str] = []
    seen_css_paths: list[Path] = []

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
        }.get(name)

    def fake_run(cmd, **kwargs):
        css_arg = next(arg for arg in cmd if arg.startswith("--css="))
        css_path = Path(css_arg.removeprefix("--css="))
        seen_css_paths.append(css_path)
        seen_css.append(css_path.read_text(encoding="utf-8"))
        Path(cmd[3]).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch(
            "sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run
        ) as run,
    ):
        result = render_markdown_pdf(source, dest, profile=profile)

    assert result == dest
    cmd = run.call_args.args[0]
    assert "--pdf-engine-opt=8.50in" in cmd
    assert "--pdf-engine-opt=4.25in" in cmd
    assert "--pdf-engine-opt=0.18in" in cmd
    assert len(seen_css) == 1
    assert "size: 8.50in 4.25in;" in seen_css[0]
    assert "margin: 0.18in;" in seen_css[0]
    assert seen_css[0].count("font-size: 18px;") >= 2
    assert "line-height: 1.4;" in seen_css[0]
    assert not seen_css_paths[0].exists()


def test_render_markdown_pdf_explicit_css_overrides_profile_css(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"
    css = tmp_path / "custom.css"
    css.write_text("body { color: black; }\n")
    profile = MarkdownPdfProfile(
        page_width="8.50in",
        page_height="4.25in",
        margin="0.18in",
        css_font_size="18px",
        latex_font_size="13pt",
    )

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
        result = render_markdown_pdf(source, dest, css_path=css, profile=profile)

    assert result == dest
    cmd = run.call_args.args[0]
    assert f"--css={css}" in cmd
    assert "--pdf-engine-opt=8.50in" in cmd
    assert not list(tmp_path.glob(".markdown-pdf-profile.*.css"))


def test_render_markdown_pdf_falls_back_to_latex_engine(tmp_path):
    source = tmp_path / "notes.markdown"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"
    seen_engines: list[str] = []
    seen_cmds: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
            "xelatex": "/usr/bin/xelatex",
        }.get(name)

    def fake_run(cmd, **kwargs):
        seen_cmds.append(cmd)
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
    latex_cmd = seen_cmds[-1]
    assert "-V" in latex_cmd
    assert "geometry:paperwidth=4.25in,paperheight=7in,margin=0.22in" in latex_cmd
    assert "fontsize=12pt" in latex_cmd
    assert "linestretch=1.32" in latex_cmd


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


def test_render_markdown_pdf_custom_profile_updates_latex_variables(tmp_path):
    source = tmp_path / "notes.markdown"
    source.write_text("# Notes\n")
    dest = tmp_path / "notes.pdf"
    profile = MarkdownPdfProfile(
        page_width="8.50in",
        page_height="4.25in",
        margin="0.18in",
        css_font_size="18px",
        latex_font_size="13pt",
        line_stretch="1.4",
    )

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "xelatex": "/usr/bin/xelatex",
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
        result = render_markdown_pdf(source, dest, profile=profile)

    assert result == dest
    cmd = run.call_args.args[0]
    assert "geometry:paperwidth=8.50in,paperheight=4.25in,margin=0.18in" in cmd
    assert "fontsize=13pt" in cmd
    assert "linestretch=1.4" in cmd


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


def test_render_launch_preview_pdf_smoke_when_tools_available(tmp_path):
    if not shutil.which("pandoc") or not any(
        shutil.which(engine) for engine in markdown_pdf.PDF_ENGINES
    ):
        pytest.skip("pandoc and a PDF engine are required")

    source = tmp_path / "launch_preview.md"
    source.write_text(
        "\n".join(
            [
                "# Launch Preview",
                "",
                "**2 agents** · source `agent_skill` · all-or-nothing",
                "",
                "## Agent 1 of 2 · demo",
                "",
                "```sase",
                "%i:demo",
                "#plan",
                "`actstat --repo sase`",
                "---",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    dest = tmp_path / "launch_preview.pdf"

    rendered = render_launch_preview_pdf(source, dest)

    assert rendered == dest
    assert dest.stat().st_size > 0
