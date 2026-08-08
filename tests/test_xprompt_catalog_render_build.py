from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.paths import get_sase_managed_tmpdir
from sase.xprompt.catalog import (
    NoXpromptsFound,
    PdfEngineUnavailable,
    _compute_stats,
    _render_html,
    build_xprompts_catalog,
)
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.tags import XPromptTag

from tests._xprompt_catalog_helpers import make_xprompt, seed_entries


def test_render_html_contains_sections() -> None:
    from sase.xprompt.catalog import _build_document

    entries = seed_entries()
    stats = _compute_stats(entries)
    document = _build_document(entries, stats)
    html = _render_html(document)

    assert "xprompts Catalog" in html
    assert "</span>a\n" in html
    assert "</span>b\n" in html
    assert "</span>c\n" in html
    assert "alpha" in html
    assert "Built-in xprompts" in html


def test_render_html_contains_input_descriptions() -> None:
    from sase.xprompt.catalog import _CatalogEntry, _build_document

    entries = [
        _CatalogEntry(
            make_xprompt(
                "review",
                source_path="config",
                inputs=[
                    InputArg(
                        name="diff",
                        type=InputType.PATH,
                        description="Diff file to inspect.",
                    )
                ],
            ),
            bucket="config",
            project=None,
        )
    ]
    stats = _compute_stats(entries)
    document = _build_document(entries, stats)
    html = _render_html(document)

    assert "Input details" in html
    assert "Diff file to inspect." in html


def test_render_html_contains_memory_badges() -> None:
    from sase.xprompt.catalog import _CatalogEntry, _build_document

    entries = [
        _CatalogEntry(
            make_xprompt(
                "memory/glossary",
                source_path="config",
                memory_type="long",
            ),
            bucket="config",
            project=None,
        )
    ]
    stats = _compute_stats(entries)
    document = _build_document(entries, stats)
    html = _render_html(document)

    assert "memory · long" in html
    assert "1 memory notes" in html


def test_build_raises_when_no_xprompts() -> None:
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        with pytest.raises(NoXpromptsFound):
            build_xprompts_catalog()


def test_build_raises_when_no_pdf_engine(tmp_path: Path) -> None:
    xp = make_xprompt(
        "hello",
        source_path="config",
        description="A test prompt",
    )
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"hello": xp}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch("sase.xprompt.catalog.shutil.which", return_value=None),
    ):
        with pytest.raises(PdfEngineUnavailable):
            build_xprompts_catalog(output_dir=tmp_path)


def test_build_default_output_uses_managed_sase_tmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xp = make_xprompt(
        "hello",
        source_path="config",
        description="A test prompt",
    )
    rendered_paths: list[Path] = []

    def fake_render_pdf(_html: str, pdf_path: Path) -> None:
        rendered_paths.append(pdf_path)
        pdf_path.write_bytes(b"%PDF fake")

    monkeypatch.delenv("SASE_TMPDIR", raising=False)
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"hello": xp}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch("sase.xprompt._catalog_render.render_pdf", side_effect=fake_render_pdf),
    ):
        artifact = build_xprompts_catalog()

    # The managed root itself is the pytest sandbox here, not ~/.sase/tmp; what
    # this asserts is that the catalog routes through the managed helper rather
    # than picking its own temp location.
    expected_parent = Path(get_sase_managed_tmpdir("xprompts_catalog"))
    assert artifact.pdf_path.parent == expected_parent
    assert artifact.pdf_path.read_bytes() == b"%PDF fake"
    assert rendered_paths
    assert rendered_paths[0].parent == expected_parent
    assert not rendered_paths[0].exists()


@pytest.mark.slow
@pytest.mark.skipif(
    shutil.which("wkhtmltopdf") is None and shutil.which("pandoc") is None,
    reason="No PDF engine available",
)
def test_build_integration_produces_pdf(tmp_path: Path) -> None:
    xps = {
        "hello": make_xprompt(
            "hello",
            source_path="config",
            tags=frozenset({XPromptTag.vcs}),
            description="A test",
            content="Hello from the test xprompt.",
        ),
        "goodbye": make_xprompt(
            "goodbye",
            source_path="config",
            content="bye",
        ),
    }

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value=xps),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        artifact = build_xprompts_catalog(output_dir=tmp_path)

    assert artifact.pdf_path.is_file()
    header = artifact.pdf_path.read_bytes()[:4]
    assert header == b"%PDF"
    assert artifact.stats.total == 2
