"""Grouped rows and kind rendering for Artifacts Files."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.artifacts.files_list import build_file_options
from sase.ace.tui.widgets.artifacts.files_rendering import (
    FILE_VIEW_MODE_COLORS,
    FILE_VIEW_MODE_GLYPHS,
    build_files_info,
)
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests.ace.tui._artifacts_files_helpers import artifact_file, snapshot


def _projects() -> ProjectRefDisplaySnapshot:
    return ProjectRefDisplaySnapshot(
        ProjectDisplaySnapshot({"alpha": "Alpha"}),
    )


def test_rows_stay_newest_first_with_date_headers_and_display_names() -> None:
    rows = (
        artifact_file("today-new", created_at="2026-07-24T14:32:00-04:00"),
        artifact_file("today-old", created_at="2026-07-24T09:15:00-04:00"),
        artifact_file("yesterday", created_at="2026-07-23T19:00:00-04:00"),
        artifact_file("historic", created_at="2026-07-20T08:00:00-04:00"),
    )
    options, option_rows = build_file_options(
        model := snapshot(rows),
        project_scope="alpha",
        project_ref_display=_projects(),
        loading=False,
        now=datetime.fromisoformat("2026-07-24T20:00:00-04:00"),
    )

    assert [option.prompt.plain for option in options if option.disabled] == [
        "── Today ────────────────────",
        "── Yesterday ────────────────────",
        "── 2026-07-20 ────────────────────",
    ]
    assert [row.entry for row in option_rows.values()] == list(model.rows)
    assert "14:32" in options[1].prompt.plain
    assert "09:15" in options[2].prompt.plain
    assert "[Alpha]" in options[1].prompt.plain


def test_viewer_classifier_drives_icons_colors_origin_and_size() -> None:
    rows = (
        artifact_file("image", kind="image", path="/tmp/image.png"),
        artifact_file("video", kind="file", path="/tmp/capture.mp4"),
        artifact_file("pdf", kind="pdf", path="/tmp/design.pdf", explicit=True),
        artifact_file(
            "markdown",
            kind="markdown",
            path="/tmp/notes.md",
            size_bytes=None,
        ),
        artifact_file("text", kind="file", path="/tmp/output.log"),
    )
    model = snapshot(rows)
    options, _option_rows = build_file_options(
        model,
        project_scope="alpha",
        project_ref_display=_projects(),
        loading=False,
        now=datetime.fromisoformat("2026-07-24T20:00:00-04:00"),
    )
    prompts = [option.prompt for option in options if not option.disabled]

    expected_modes = ("image", "video", "pdf", "markdown", "text")
    for prompt, mode in zip(prompts, expected_modes, strict=True):
        assert prompt.plain.startswith(FILE_VIEW_MODE_GLYPHS[mode])
        assert any(
            str(span.style) == f"bold {FILE_VIEW_MODE_COLORS[mode]}"
            for span in prompt.spans
        )
        assert prompt.no_wrap is True
        assert len(prompt.wrap(Console(width=80), 80)) == 1

    assert "C" in prompts[2].plain
    assert prompts[3].plain.endswith("-")
    assert model.view_mode_for(model.rows[1].latest) == "video"


def test_info_uses_precomputed_kind_and_explicit_counts() -> None:
    rows = (
        artifact_file("image", kind="image", path="/tmp/image.png"),
        artifact_file("video", kind="file", path="/tmp/capture.mp4"),
        artifact_file("pdf", kind="pdf", path="/tmp/design.pdf", explicit=True),
        artifact_file("markdown", kind="markdown", path="/tmp/notes.md"),
        artifact_file("text", kind="file", path="/tmp/output.log"),
    )
    info = build_files_info(
        load_keymap_registry({}),
        snapshot(rows),
        project_scope="alpha",
        project_display_name="Alpha",
    )

    assert "▨ 1 images" in info.plain
    assert "▤ 2 documents" in info.plain
    assert "▶ 1 videos" in info.plain
    assert "• 1 files" in info.plain
    assert "C 1" in info.plain
    assert "A 4" in info.plain
