"""Regression checks for the strict handbook PDF export configuration."""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
PDF_CONFIG = ROOT / "mkdocs-pdf.yml"
JUSTFILE = ROOT / "Justfile"
POSTPROCESS = ROOT / "tools" / "postprocess_docs_pdf"
MAIN_TEMPLATE = ROOT / "docs" / "overrides" / "main.html"


class _MkDocsYamlLoader(yaml.SafeLoader):
    """Accept MkDocs ``!ENV`` tags so the PDF overlay can be loaded as data."""


def _construct_env(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


_MkDocsYamlLoader.add_constructor("!ENV", _construct_env)


def test_pdf_config_disables_remote_material_fonts() -> None:
    """Strict export 404s when Material fetches fonts.googleapis.com / fonts.gstatic.com."""

    data = yaml.load(PDF_CONFIG.read_text(encoding="utf-8"), Loader=_MkDocsYamlLoader)

    assert data["theme"]["font"] is False


def test_pdf_check_recipe_keeps_strict_mkdocs_export() -> None:
    recipe = JUSTFILE.read_text(encoding="utf-8")
    start = recipe.index("docs-pdf-check:")
    end = recipe.index("docs-deploy-artifact-check:", start)
    body = recipe[start:end]

    # Curated handbook design (pdf_scope = curate): the recipe builds a
    # generated config holding only handbook pages, strictly.
    assert "curate_docs_pdf_nav" in body
    assert "mkdocs build --strict" in body
    assert "pillow" in body


def _load_postprocess() -> ModuleType:
    loader = SourceFileLoader("postprocess_docs_pdf_tool", str(POSTPROCESS))
    spec = importlib.util.spec_from_file_location(
        "postprocess_docs_pdf_tool",
        POSTPROCESS,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _image(*, reference: int, image_format: str, mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        indirect_reference=SimpleNamespace(idnum=reference),
        image=SimpleNamespace(format=image_format, mode=mode),
        replace=Mock(),
    )


def test_pdf_image_optimization_reencodes_each_shared_rgb_png_once() -> None:
    pytest.importorskip("pypdf")
    tool = _load_postprocess()
    first = _image(reference=7, image_format="PNG", mode="RGB")
    duplicate = _image(reference=7, image_format="PNG", mode="RGB")
    jpeg = _image(reference=8, image_format="JPEG", mode="RGB")
    transparent = _image(reference=9, image_format="PNG", mode="RGBA")
    writer = SimpleNamespace(
        pages=[
            SimpleNamespace(images=[first, jpeg]),
            SimpleNamespace(images=[duplicate, transparent]),
        ]
    )

    assert tool._optimize_images(writer) == 1
    first.replace.assert_called_once_with(
        first.image,
        quality=tool.IMAGE_JPEG_QUALITY,
        optimize=True,
    )
    duplicate.replace.assert_not_called()
    jpeg.replace.assert_not_called()
    transparent.replace.assert_not_called()


def test_pdf_config_keeps_only_the_root_index_page() -> None:
    """A bare ``!index.md`` would pull every Reference hub into the strict build."""

    pathspec = pytest.importorskip("pathspec")
    data = yaml.load(PDF_CONFIG.read_text(encoding="utf-8"), Loader=_MkDocsYamlLoader)
    excluded = pathspec.GitIgnoreSpec.from_lines(data["exclude_docs"].splitlines())

    assert not excluded.match_file("index.md")
    assert not excluded.match_file("guides/index.md")
    assert excluded.match_file("reference/index.md")
    assert excluded.match_file("reference/tui/index.md")
    assert excluded.match_file("contribute/index.md")


def test_pdf_build_resolves_relative_video_posters() -> None:
    """mkdocs-exporter resolves src and href for print, but not <video poster>."""

    jinja2 = pytest.importorskip("jinja2")
    loader = jinja2.ChoiceLoader(
        [
            jinja2.DictLoader(
                {
                    "base.html": (
                        "{% block content %}"
                        '<video poster="images/still.png"></video>'
                        '<video poster="https://sase.sh/still.png"></video>'
                        "{% endblock %}"
                    )
                }
            ),
            jinja2.FileSystemLoader(str(MAIN_TEMPLATE.parent)),
        ]
    )
    template = jinja2.Environment(loader=loader).get_template(MAIN_TEMPLATE.name)
    page = SimpleNamespace(url="start/")

    pdf = template.render(
        config={"extra": {"pdf_handbook": {"build_date": ""}}, "site_dir": "/tmp/site"},
        page=page,
    )
    web = template.render(config={"extra": {}, "site_dir": "/tmp/site"}, page=page)

    assert 'poster="file:///tmp/site/start/images/still.png"' in pdf
    assert 'poster="https://sase.sh/still.png"' in pdf
    assert 'poster="images/still.png"' in web
