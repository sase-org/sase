"""Detail-panel, liveness, and bounded-preview coverage for Artifacts Files."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import files_pane
from sase.ace.tui.widgets.artifacts.files_detail import (
    build_file_detail,
    load_file_detail,
)
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests.ace.tui._artifacts_files_helpers import artifact_file, snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices


def _projects() -> ProjectRefDisplaySnapshot:
    return ProjectRefDisplaySnapshot(
        ProjectDisplaySnapshot({"alpha": "Alpha"}),
    )


def test_explicit_and_default_origins_are_plain_and_distinct(tmp_path: Path) -> None:
    stored = tmp_path / "artifact.md"
    stored.write_text("# Artifact\n", encoding="utf-8")
    explicit = artifact_file(
        "explicit",
        kind="markdown",
        path=str(stored),
        explicit=True,
        agent_artifacts_dir="/tmp/agents/alpha.1",
    )
    automatic = replace(explicit, id="default:automatic", explicit=False)
    detail = load_file_detail(explicit, view_mode="markdown")

    explicit_text = build_file_detail(
        explicit,
        detail,
        view_mode="markdown",
        projects=_projects(),
    ).plain
    automatic_text = build_file_detail(
        automatic,
        replace(detail, file_id=automatic.id),
        view_mode="markdown",
        projects=_projects(),
    ).plain

    assert "REFERENCE" in explicit_text
    assert f"file:{explicit.id}  →  {stored}" in explicit_text
    assert (
        "Registered explicitly by alpha.1--code during code in Alpha." in explicit_text
    )
    assert "Captured automatically from alpha.1--code's run." in automatic_text
    assert "Project: Alpha" in explicit_text
    assert "Artifacts dir: /tmp/agents/alpha.1" in explicit_text


def test_paths_keep_stored_and_missing_source_liveness_distinct(
    tmp_path: Path,
) -> None:
    stored = tmp_path / "stored.txt"
    stored.write_text("stored copy\n", encoding="utf-8")
    source = tmp_path / "deleted-source.txt"
    row = artifact_file(
        "paths",
        path=str(stored),
        source_path=str(source),
    )

    detail = load_file_detail(row, view_mode="text")
    rendered = build_file_detail(
        row,
        detail,
        view_mode="text",
        projects=_projects(),
    ).plain

    assert detail.stored_live is True
    assert detail.source_live is False
    assert f"Stored: {stored}  live" in rendered
    assert f"Source: {source}  missing" in rendered
    assert rendered.index("Stored:") < rendered.index("Source:")


def test_vcs_backed_detail_materializes_and_renders_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = tmp_path / "vcs-cache" / "report.md"
    cached.parent.mkdir()
    cached.write_text("# cached\n", encoding="utf-8")
    row = replace(
        artifact_file("vcs", kind="markdown"),
        path=None,
        vcs_repo="sase",
        vcs_sha="b" * 40,
        vcs_relpath="docs/report.md",
        sha256="a" * 64,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.files_detail._materialized_path",
        lambda _row: cached,
    )

    detail = load_file_detail(row, view_mode="markdown")
    rendered = build_file_detail(
        row,
        detail,
        view_mode="markdown",
        projects=_projects(),
    ).plain

    assert detail.resolved_stored_path == str(cached)
    assert detail.preview == "# cached"
    assert "PROVENANCE" in rendered
    assert "Repo: sase" in rendered
    assert f"Commit: {'b' * 40}" in rendered
    assert "Path: docs/report.md" in rendered
    assert "Cached: yes" in rendered
    assert "Stored:" not in rendered


def test_missing_enrichment_uses_dashes_and_names_doctor_fix() -> None:
    row = artifact_file(
        "unenriched",
        mime_type=None,
        size_bytes=None,
        sha256=None,
    )

    rendered = build_file_detail(
        row,
        None,
        view_mode="text",
        projects=_projects(),
    ).plain

    assert "MIME type: -" in rendered
    assert "Size: -" in rendered
    assert "SHA-256: -" in rendered
    assert "sase artifact doctor --fix" in rendered


def test_enriched_metadata_is_humanized_and_sha_is_shortened() -> None:
    row = artifact_file(
        "enriched",
        mime_type="text/plain",
        size_bytes=12_697,
        sha256="0123456789abcdef0123456789abcdef",
    )

    rendered = build_file_detail(
        row,
        None,
        view_mode="text",
        projects=_projects(),
    ).plain

    assert "Kind: file · text" in rendered
    assert "MIME type: text/plain" in rendered
    assert "Size: 12.4 KiB" in rendered
    assert "SHA-256: 0123456789ab…" in rendered
    assert "Created: 2026-07-24 14:32" in rendered
    assert "sase artifact doctor --fix" not in rendered


def test_text_preview_is_bounded_and_media_has_no_preview(tmp_path: Path) -> None:
    stored = tmp_path / "long.txt"
    stored.write_text(
        "".join(f"line {index}\n" for index in range(45)),
        encoding="utf-8",
    )
    text_row = artifact_file("long", path=str(stored))
    text_detail = load_file_detail(text_row, view_mode="text")

    rendered = build_file_detail(
        text_row,
        text_detail,
        view_mode="text",
        projects=_projects(),
    ).plain
    assert text_detail.preview_truncated is True
    assert len(text_detail.preview.splitlines()) == 40
    assert "line 39" in rendered
    assert "line 40" not in rendered
    assert "press enter for the full reader" in rendered

    image_row = replace(text_row, kind="image", path=str(tmp_path / "image.png"))
    image_detail = load_file_detail(image_row, view_mode="image")
    media_rendered = build_file_detail(
        image_row,
        image_detail,
        view_mode="image",
        projects=_projects(),
    ).plain
    assert image_detail.preview == ""
    assert "PREVIEW" not in media_rendered


def test_cache_key_tracks_stored_file_mtime_and_size(tmp_path: Path) -> None:
    stored = tmp_path / "changing.txt"
    stored.write_text("first\n", encoding="utf-8")
    row = artifact_file("changing", path=str(stored))
    first = load_file_detail(row, view_mode="text")

    stored.write_text("a meaningfully longer second value\n", encoding="utf-8")
    second = load_file_detail(row, view_mode="text")

    assert first.cache_key[0] == row.id
    assert first.cache_key != second.cache_key


async def test_rapid_navigation_loads_only_the_final_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = tuple(tmp_path / f"row-{index}.txt" for index in range(3))
    for index, path in enumerate(paths):
        path.write_text(f"row {index}\n", encoding="utf-8")
    rows = tuple(
        artifact_file(f"row-{index}", path=str(path))
        for index, path in enumerate(paths)
    )
    calls: list[str] = []
    real_loader = load_file_detail

    def load_detail(row, *, view_mode):
        calls.append(row.id)
        return real_loader(row, view_mode=view_mode)

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: snapshot(rows, project=project),
    )
    monkeypatch.setattr(files_pane, "load_file_detail", load_detail)

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("5", "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: calls == [rows[0].id])
        calls.clear()

        await page.press("j", "j")
        await page.wait_for(lambda _state: bool(calls))

        assert pane.selected_entry is rows[2]
        assert calls == [rows[2].id]
