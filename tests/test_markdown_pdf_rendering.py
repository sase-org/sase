from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.attachments import markdown_pdf
from sase.attachments.markdown_pdf import (
    MarkdownPdfProfile,
    render_markdown_pdf,
)


def _resource_path(*paths: Path) -> str:
    return os.pathsep.join(
        dict.fromkeys(str(path.expanduser().resolve(strict=False)) for path in paths)
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
    assert cmd[:3] == ["/usr/bin/pandoc", str(source.resolve()), "-o"]
    assert Path(cmd[3]).is_absolute()
    assert cmd[4:] == [
        "--pdf-engine=wkhtmltopdf",
        "--highlight-style=tango",
        f"--resource-path={_resource_path(source.parent, Path.cwd())}",
        f"--css={Path(markdown_pdf.__file__).with_name('markdown_pdf.css').resolve()}",
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
    assert (
        f"--css={Path(markdown_pdf.__file__).with_name('markdown_pdf.css').resolve()}"
        in cmd
    )


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
    assert f"--css={css.resolve()}" in cmd
    assert (
        f"--css={Path(markdown_pdf.__file__).with_name('markdown_pdf.css').resolve()}"
        not in cmd
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
    assert f"--syntax-definition={syntax.resolve()}" in cmd
    assert "--metadata" not in cmd
    assert "title=notes" not in cmd


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
    assert f"--css={css.resolve()}" in cmd
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
