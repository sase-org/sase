"""Tests for the committed sase.sh social card and its renderer."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

from PIL import Image
import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "render_social_card"
CURATE_TOOL = ROOT / "tools" / "curate_docs_pdf_nav"
TEMPLATE_PATH = ROOT / "docs" / "overrides" / "main.html"
MKDOCS_PATH = ROOT / "mkdocs.yml"
MKDOCS_PDF_PATH = ROOT / "mkdocs-pdf.yml"
DEFAULT_IMAGE_RE = re.compile(r'\{\%\s*set\s+default_image\s*=\s*"([^"]+)"\s*\%\}')
RSS_IMAGE_RE = re.compile(r"image:\s*(https://sase\.sh/\S+)")
MAX_CARD_BYTES = 5 * 1024 * 1024
LINKEDIN_ASPECT = 1.91
ASPECT_TOLERANCE = 0.03


def _load_renderer(name: str = "render_social_card_test") -> ModuleType:
    loader = SourceFileLoader(name, str(TOOL_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _default_image_path() -> str:
    match = DEFAULT_IMAGE_RE.search(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert match is not None, "default_image is missing from main.html"
    return match.group(1)


def test_renderer_writes_card_and_preview(tmp_path: Path) -> None:
    renderer = _load_renderer()
    card = tmp_path / "card.png"
    preview = tmp_path / "preview.png"
    assert renderer.main([str(card), "--preview", str(preview)]) == 0

    with Image.open(card) as image:
        assert image.mode == "RGB"
        assert image.size == (1200, 627)
    assert card.stat().st_size < MAX_CARD_BYTES

    with Image.open(preview) as image:
        assert image.size == (474, 248)


def test_default_social_image_meets_linkedin_card_spec() -> None:
    relative = _default_image_path()
    path = ROOT / "docs" / relative
    assert path.is_file(), f"missing default social image: {path}"
    with Image.open(path) as image:
        width, height = image.size
    assert width >= 1200
    assert abs(width / height - LINKEDIN_ASPECT) <= ASPECT_TOLERANCE


def test_rss_plugin_images_use_the_default_social_image() -> None:
    relative = _default_image_path()
    urls = RSS_IMAGE_RE.findall(MKDOCS_PATH.read_text(encoding="utf-8"))
    assert urls, "rss image missing from mkdocs.yml"
    assert all(url.endswith(relative) for url in urls), urls


def test_pdf_rss_image_flows_through_the_curated_inherit_chain(
    tmp_path: Path,
) -> None:
    """The curated PDF build inherits its RSS image instead of repeating it.

    ``mkdocs-pdf.yml`` carries no RSS block by design (pdf_scope = curate):
    MkDocs config inheritance pulls the feed, including its image, from
    ``mkdocs.yml``. This guards the chain so the PDF feed keeps the default
    social image without pinning the old duplicated block.
    """
    pdf_text = MKDOCS_PDF_PATH.read_text(encoding="utf-8")
    assert re.search(r"^INHERIT:\s*mkdocs\.yml\s*$", pdf_text, re.MULTILINE), (
        "mkdocs-pdf.yml must inherit mkdocs.yml for the RSS image"
    )
    out = tmp_path / "mkdocs-pdf.curated.yml"
    proc = subprocess.run(
        [sys.executable, str(CURATE_TOOL), "--output", str(out)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    generated = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert generated.get("INHERIT") == "mkdocs-pdf.yml"
