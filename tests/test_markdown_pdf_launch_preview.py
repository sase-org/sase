from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.attachments import markdown_pdf
from sase.attachments.markdown_pdf import render_launch_preview_pdf


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
    assert (
        f"--css={Path(markdown_pdf.__file__).with_name('launch_preview.css').resolve()}"
        in cmd
    )
    assert (
        f"--syntax-definition="
        f"{Path(markdown_pdf.__file__).with_name('sase.xml').resolve()}"
    ) in cmd
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
