from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.attachments import markdown_pdf
from sase.attachments.markdown_pdf import render_markdown_pdf


def test_properties_card_markup_is_ordered_styled_and_html_safe():
    markup = markdown_pdf._properties_card_markup(
        {
            "zeta": "<unsafe & *literal*>",
            "phases": [{"id": "build", "depends_on": []}],
            "title": "A > B",
        }
    )

    assert 'class="sase-properties"' in markup
    assert 'style="background:#f6f8fa;' in markup
    assert markup.index(">Title</th>") < markup.index(">Phases</th>")
    assert markup.index(">Phases</th>") < markup.index(">Zeta</th>")
    assert "A &gt; B" in markup
    assert "&lt;unsafe &amp; *literal*&gt;" in markup
    html_card = markup.split("```{=html}\n", 1)[1].split("\n```", 1)[0]
    assert "<unsafe" not in html_card
    assert "•" in markup
    assert "  id: build" in markup
    assert 'style="display:none;"' in markup


def test_markdown_fallback_escapes_property_text():
    escaped = markdown_pdf._escape_markdown_text(
        "<script>*literal* [link](target) & value"
    )

    assert escaped == (r"\<script\>\*literal\* \[link\]\(target\) \& value")


@pytest.mark.parametrize(
    "content",
    [
        "# No frontmatter\n",
        "---\n---\n# Empty frontmatter\n",
        "---\ntitle: [unterminated\n---\n# Malformed frontmatter\n",
    ],
)
def test_preprocess_markdown_source_is_noop_without_usable_frontmatter(
    tmp_path: Path,
    content: str,
):
    source = tmp_path / "plan.md"
    source.write_text(content, encoding="utf-8")

    render_source, title, temporary = markdown_pdf._preprocess_markdown_source(
        source,
        tmp_path,
        include_properties=True,
    )

    assert render_source == source
    assert title == "plan"
    assert temporary is None


def test_preprocess_markdown_source_replaces_frontmatter_and_uses_real_title(
    tmp_path: Path,
):
    source = tmp_path / "plan.md"
    source.write_text(
        "---\ntitle: Real Plan Title\ntier: tale\ngoal: Ship it\n---\n# Body\n",
        encoding="utf-8",
    )

    render_source, title, temporary = markdown_pdf._preprocess_markdown_source(
        source,
        tmp_path,
        include_properties=True,
    )

    try:
        assert temporary == render_source
        assert temporary is not None
        assert title == "Real Plan Title"
        rendered_content = render_source.read_text(encoding="utf-8")
        assert rendered_content.startswith("```{=html}\n")
        assert ">Real Plan Title</div>" in rendered_content
        assert rendered_content.endswith("# Body\n")
        assert "\ntitle: Real Plan Title\n" not in rendered_content
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def test_render_markdown_pdf_uses_preprocessed_source_and_cleans_it_up(
    tmp_path: Path,
):
    source = tmp_path / "plan.md"
    source.write_text(
        "---\ntitle: Real Plan Title\ntier: tale\n---\n# Body\n",
        encoding="utf-8",
    )
    dest = tmp_path / "plan.pdf"
    captured_source: Path | None = None
    captured_content = ""
    captured_cmd: list[str] = []

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
        }.get(name)

    def fake_run(cmd, **kwargs):
        nonlocal captured_source, captured_content, captured_cmd
        captured_cmd = cmd
        captured_source = Path(cmd[1])
        captured_content = captured_source.read_text(encoding="utf-8")
        Path(cmd[3]).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
    ):
        assert render_markdown_pdf(source, dest) == dest

    assert captured_source is not None
    assert captured_source != source
    assert not captured_source.exists()
    assert captured_content.startswith("```{=html}\n")
    assert captured_content.endswith("# Body\n")
    assert ["--metadata", "title=Real Plan Title"] == captured_cmd[-2:]


def test_render_markdown_pdf_falls_back_to_original_after_preprocessing_error(
    tmp_path: Path,
):
    source = tmp_path / "plan.md"
    original = "---\ntitle: Real Plan Title\n---\n# Body\n"
    source.write_text(original, encoding="utf-8")
    dest = tmp_path / "plan.pdf"
    captured_source: Path | None = None
    captured_content = ""

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
        }.get(name)

    def fake_run(cmd, **kwargs):
        nonlocal captured_source, captured_content
        captured_source = Path(cmd[1])
        captured_content = captured_source.read_text(encoding="utf-8")
        Path(cmd[3]).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
        patch(
            "sase.attachments.markdown_pdf._properties_card_markup",
            side_effect=RuntimeError("boom"),
        ),
    ):
        assert render_markdown_pdf(source, dest) == dest

    assert captured_source == source
    assert captured_content == original


def test_render_markdown_pdf_can_disable_properties(tmp_path: Path):
    source = tmp_path / "prompt.md"
    original = "---\ntitle: Prompt Metadata\n---\n# Prompt body\n"
    source.write_text(original, encoding="utf-8")
    dest = tmp_path / "prompt.pdf"
    captured_source: Path | None = None

    def fake_which(name: str) -> str | None:
        return {
            "pandoc": "/usr/bin/pandoc",
            "wkhtmltopdf": "/usr/bin/wkhtmltopdf",
        }.get(name)

    def fake_run(cmd, **kwargs):
        nonlocal captured_source
        captured_source = Path(cmd[1])
        Path(cmd[3]).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sase.attachments.markdown_pdf.shutil.which", side_effect=fake_which),
        patch("sase.attachments.markdown_pdf.subprocess.run", side_effect=fake_run),
    ):
        assert render_markdown_pdf(source, dest, include_properties=False) == dest

    assert captured_source == source
    assert source.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "frontmatter",
    [
        "title: Tale PDF\ntier: tale\ngoal: Verify the card",
        (
            "title: Epic PDF\n"
            "tier: epic\n"
            "goal: Verify nested phases\n"
            "phases:\n"
            "  - id: research\n"
            "    depends_on: []\n"
            "    description: |\n"
            "      <unsafe & *literal*> remains text.\n"
            "  - id: build\n"
            "    depends_on: [research]"
        ),
    ],
)
def test_render_markdown_pdf_properties_smoke_when_tools_available(
    tmp_path: Path,
    frontmatter: str,
):
    if not shutil.which("pandoc") or not any(
        shutil.which(engine) for engine in markdown_pdf.PDF_ENGINES
    ):
        pytest.skip("pandoc and a PDF engine are required")

    source = tmp_path / "plan.md"
    source.write_text(
        f"---\n{frontmatter}\n---\n# Plan body\n",
        encoding="utf-8",
    )
    dest = tmp_path / "plan.pdf"

    assert render_markdown_pdf(source, dest) == dest
    assert dest.stat().st_size > 0
    if pdftotext := shutil.which("pdftotext"):
        extracted = subprocess.run(
            [pdftotext, str(dest), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert "Properties" in extracted
        assert "</div>" not in extracted
        assert "&lt;" not in extracted
