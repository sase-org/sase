"""Tests for xprompt.catalog — stats, classification, and rendering."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.xprompt.catalog import (
    MAX_MOBILE_CONTENT_PREVIEW_CHARS,
    NoXpromptsFound,
    PdfEngineUnavailable,
    _classify,
    _compute_stats,
    _format_inputs,
    _render_html,
    _truncate_content,
    build_structured_xprompts_catalog,
    build_xprompts_catalog,
)
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.tags import XPromptTag


def _make_xprompt(
    name: str,
    *,
    source_path: str | None = None,
    tags: frozenset = frozenset(),
    description: str | None = None,
    inputs: list[InputArg] | None = None,
    skill: bool | None = None,
    content: str = "body",
    snippet: bool | None = None,
    keywords: list[str] | None = None,
) -> XPrompt:
    return XPrompt(
        name=name,
        content=content,
        inputs=inputs or [],
        source_path=source_path,
        tags=tags,
        description=description,
        skill=skill,
        snippet=snippet,
        keywords=keywords or [],
    )


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


def test_classify_builtin(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    source = pkg_dir / "foo.md"
    source.write_text("x")

    xp = _make_xprompt("foo", source_path=str(source))

    with (
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir", return_value=pkg_dir
        ),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = _classify(xp, project=None)

    assert entry.bucket == "built-in"
    assert entry.project is None


def test_classify_default_xprompts_builtin(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    default_dir = tmp_path / "default_xprompts"
    default_dir.mkdir()
    source = default_dir / "research_swarm.md"
    source.write_text("x")

    xp = _make_xprompt("research_swarm", source_path=str(source))

    with (
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=pkg_dir,
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_default_xprompts_dir",
            return_value=default_dir,
        ),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = _classify(xp, project=None)

    assert entry.bucket == "built-in"
    assert entry.project is None


def test_classify_plugin_source() -> None:
    xp = _make_xprompt("foo", source_path="plugin:some_module/foo.md")
    with (
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project=None)
    assert entry.bucket == "plugin"


def test_classify_config_label() -> None:
    xp = _make_xprompt("foo", source_path="config")
    with (
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project=None)
    assert entry.bucket == "config"


def test_classify_memory(tmp_path: Path) -> None:
    mem_file = tmp_path / "memory" / "long" / "x.md"
    mem_file.parent.mkdir(parents=True)
    mem_file.write_text("hi")

    xp = _make_xprompt("memory/long/x", source_path=str(mem_file))
    with (
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project=None)
    assert entry.bucket == "memory"


def test_classify_project_explicit(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    xp = _make_xprompt("foo", source_path=str(ws / "sase.yml"))
    with (
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"myproj": ws},
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project="myproj")
    assert entry.bucket == "project"
    assert entry.project == "myproj"


def test_classify_project_inferred_from_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "proj-ws"
    ws.mkdir()
    source = ws / ".xprompts" / "bar.md"
    source.parent.mkdir(parents=True)
    source.write_text("x")
    xp = _make_xprompt("bar", source_path=str(source))
    with (
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"inferred": ws},
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project=None)
    assert entry.bucket == "project"
    assert entry.project == "inferred"


# ---------------------------------------------------------------------------
# _compute_stats
# ---------------------------------------------------------------------------


def _seed_entries() -> list:
    from sase.xprompt.catalog import _CatalogEntry

    return [
        _CatalogEntry(
            _make_xprompt(
                "a",
                tags=frozenset({XPromptTag.vcs}),
                description="A",
                inputs=[InputArg(name="x", type=InputType.LINE)],
                skill=True,
            ),
            bucket="built-in",
            project=None,
        ),
        _CatalogEntry(
            _make_xprompt("b", tags=frozenset({XPromptTag.vcs, XPromptTag.commit})),
            bucket="project",
            project="alpha",
        ),
        _CatalogEntry(
            _make_xprompt("c"),
            bucket="config",
            project=None,
        ),
    ]


def test_compute_stats_basic() -> None:
    entries = _seed_entries()
    stats = _compute_stats(entries)

    assert stats.total == 3
    assert stats.by_source["built-in"] == 1
    assert stats.by_source["project"] == 1
    assert stats.by_source["config"] == 1
    assert stats.by_project == {"alpha": 1}
    assert stats.by_tag == {"vcs": 2, "commit": 1}
    assert stats.with_description == 1
    assert stats.with_inputs == 1
    assert stats.skills == 1


# ---------------------------------------------------------------------------
# Helper filters
# ---------------------------------------------------------------------------


def test_truncate_content_short() -> None:
    result = _truncate_content("a\nb\nc")
    assert result["text"] == "a\nb\nc"
    assert result["elided"] is None


def test_truncate_content_long() -> None:
    body = "\n".join(f"line{i}" for i in range(100))
    result = _truncate_content(body, source_path="/foo.md")
    assert result["text"].count("\n") == 39
    assert "more lines" in result["elided"]
    assert "/foo.md" in result["elided"]


def test_format_inputs_required_optional() -> None:
    from sase.xprompt.models import UNSET

    inputs = [
        InputArg(name="p", type=InputType.PATH, default=UNSET),
        InputArg(name="n", type=InputType.LINE, default="hi"),
    ]
    assert _format_inputs(inputs) == "(p: path, n?: line)"


def test_format_inputs_empty() -> None:
    assert _format_inputs([]) == ""


# ---------------------------------------------------------------------------
# build_structured_xprompts_catalog
# ---------------------------------------------------------------------------


def test_structured_catalog_projects_filters_and_caps_preview(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "sase"
    ws.mkdir()
    local_source = ws / ".sase" / "xprompts" / "local.md"
    local_source.parent.mkdir(parents=True)
    local_source.write_text("local")
    long_body = "a" * (MAX_MOBILE_CONTENT_PREVIEW_CHARS + 25)
    global_xp = _make_xprompt(
        "review",
        source_path="config",
        tags=frozenset({XPromptTag.mentor}),
        description="Review code",
    )
    local_xp = _make_xprompt(
        "local_fix",
        source_path=str(local_source),
        tags=frozenset({XPromptTag.fix_hook}),
        inputs=[InputArg(name="path", type=InputType.PATH)],
        skill=True,
        content=long_body,
    )
    other_xp = _make_xprompt("other", source_path=str(tmp_path / "other.md"))

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts", return_value={"review": global_xp}
        ),
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"sase": ws, "other": tmp_path / "other"},
        ),
        patch(
            "sase.xprompt.catalog.load_project_local_xprompts",
            side_effect=[
                {"local_fix": local_xp},
                {"other": other_xp},
            ],
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_default_xprompts_dir",
            return_value=tmp_path / "default",
        ),
    ):
        projection = build_structured_xprompts_catalog(
            project="sase",
            tag="fix_hook",
            query="local",
        )

    assert [entry.name for entry in projection.entries] == ["local_fix"]
    entry = projection.entries[0]
    assert entry.project == "sase"
    assert entry.input_signature == "(path: path)"
    assert entry.is_skill is True
    assert entry.source_path_display == ".sase/xprompts/local.md"
    assert entry.content_preview is not None
    assert len(entry.content_preview) <= MAX_MOBILE_CONTENT_PREVIEW_CHARS + 3
    assert projection.stats.total_count == 1
    assert projection.stats.project_count == 1
    assert projection.stats.skill_count == 1


def test_structured_catalog_source_filter_keeps_global_entries(
    tmp_path: Path,
) -> None:
    config_xp = _make_xprompt("global", source_path="config")
    project_xp = _make_xprompt("project", source_path=str(tmp_path / "p.md"))

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts", return_value={"global": config_xp}
        ),
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"sase": tmp_path},
        ),
        patch(
            "sase.xprompt.catalog.load_project_local_xprompts",
            return_value={"project": project_xp},
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
    ):
        projection = build_structured_xprompts_catalog(project="sase", source="config")

    assert [entry.name for entry in projection.entries] == ["global"]
    assert projection.entries[0].source_bucket == "config"


def test_structured_catalog_pdf_engine_warning_does_not_block_records(
    tmp_path: Path,
) -> None:
    xp = _make_xprompt("hello", source_path="config")
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"hello": xp}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch("sase.xprompt.catalog.shutil.which", return_value=None),
    ):
        projection = build_structured_xprompts_catalog(include_pdf=True)

    assert [entry.name for entry in projection.entries] == ["hello"]
    assert projection.stats.pdf_requested is True
    assert projection.catalog_attachment is None
    assert projection.warnings == ["PDF catalog was not generated"]
    assert projection.skipped[0].target == "xprompt-catalog.pdf"


# ---------------------------------------------------------------------------
# _render_html (end-to-end on fake data, no PDF)
# ---------------------------------------------------------------------------


def test_render_html_contains_sections() -> None:
    from sase.xprompt.catalog import _build_document

    entries = _seed_entries()
    stats = _compute_stats(entries)
    document = _build_document(entries, stats)
    html = _render_html(document)

    assert "xprompts Catalog" in html
    assert "</span>a\n" in html
    assert "</span>b\n" in html
    assert "</span>c\n" in html
    assert "alpha" in html
    assert "Built-in xprompts" in html


# ---------------------------------------------------------------------------
# build_xprompts_catalog — error paths + integration
# ---------------------------------------------------------------------------


def test_build_raises_when_no_xprompts() -> None:
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        with pytest.raises(NoXpromptsFound):
            build_xprompts_catalog()


def test_build_raises_when_no_pdf_engine(tmp_path: Path) -> None:
    xp = _make_xprompt(
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


@pytest.mark.slow
@pytest.mark.skipif(
    shutil.which("wkhtmltopdf") is None and shutil.which("pandoc") is None,
    reason="No PDF engine available",
)
def test_build_integration_produces_pdf(tmp_path: Path) -> None:
    xps = {
        "hello": _make_xprompt(
            "hello",
            source_path="config",
            tags=frozenset({XPromptTag.vcs}),
            description="A test",
            content="Hello from the test xprompt.",
        ),
        "goodbye": _make_xprompt(
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
