"""ACE PNG visual snapshot coverage for Artifacts -> Files."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.ace.tui.widgets.artifacts import files_pane
from sase.ace.tui.widgets.artifacts.files_detail import FileDetailData
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.files_rendering import (
    FILE_VIEW_MODE_COLORS,
    FILE_VIEW_MODE_GLYPHS,
)
from sase.core.artifact_file_types import ArtifactFile
from tests.ace.tui._artifacts_files_helpers import artifact_file, snapshot
from tests.ace.tui._artifacts_plans_helpers import _all_choices
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


_VISUAL_FILES_ROOT = "/visual/artifacts"
_MISSING_SOURCE = "/visual/recycled/sase_7/docs/release_notes.md"


def _fixture_rows() -> tuple[ArtifactFile, ...]:
    """Cover every view-mode glyph, an explicit row, and an unenriched row."""

    return (
        artifact_file(
            "release-notes",
            artifact_id="explicit:1a2b3c4d5e6f708192a3b4c5",
            kind="file",
            path=f"{_VISUAL_FILES_ROOT}/release_notes.md",
            source_path=_MISSING_SOURCE,
            created_at="2026-07-24T16:05:00-04:00",
            project="alpha",
            agent_name="alpha.1--code",
            workflow="code",
            explicit=True,
            size_bytes=8_412,
            mime_type="text/markdown",
            sha256="9f2c1d7ab34e55608172c9de4f0a1b2c3d4e5f60718293a4b5c6d7e8f9001122",
        ),
        artifact_file(
            "architecture",
            artifact_id="default:2b3c4d5e6f708192a3b4c5d6",
            kind="image",
            path=f"{_VISUAL_FILES_ROOT}/architecture.png",
            created_at="2026-07-24T15:40:00-04:00",
            project="alpha",
            agent_name="alpha.2--research",
            workflow="research",
            size_bytes=214_902,
            mime_type="image/png",
            sha256="1c2d3e4f5a6b7c8d9e0f112233445566778899aabbccddeeff0011223344556",
        ),
        artifact_file(
            "walkthrough",
            artifact_id="default:3c4d5e6f708192a3b4c5d6e7",
            kind="file",
            path=f"{_VISUAL_FILES_ROOT}/walkthrough.mp4",
            created_at="2026-07-24T14:20:00-04:00",
            project="beta",
            agent_name="beta.1--demo",
            workflow="demo",
            size_bytes=18_874_368,
            mime_type="video/mp4",
            sha256="2d3e4f5a6b7c8d9e0f112233445566778899aabbccddeeff00112233445566aa",
        ),
        artifact_file(
            "design-review",
            artifact_id="default:4d5e6f708192a3b4c5d6e7f8",
            kind="pdf",
            path=f"{_VISUAL_FILES_ROOT}/design_review.pdf",
            created_at="2026-07-24T13:05:00-04:00",
            project="beta",
            agent_name="beta.2--review",
            workflow="review",
            size_bytes=1_204_224,
            mime_type="application/pdf",
            sha256="3e4f5a6b7c8d9e0f112233445566778899aabbccddeeff00112233445566aabb",
        ),
        artifact_file(
            "build-log",
            artifact_id="default:5e6f708192a3b4c5d6e7f809",
            kind="file",
            path=f"{_VISUAL_FILES_ROOT}/build.log",
            created_at="2026-07-23T18:30:00-04:00",
            project="alpha",
            agent_name="alpha.3--lint",
            workflow="lint",
            size_bytes=None,
            mime_type=None,
            sha256=None,
        ),
    )


def _fixture_detail(
    entry: ArtifactFile,
    *,
    view_mode: ArtifactViewMode,
) -> FileDetailData:
    """Return deterministic liveness and preview data without touching disk."""

    preview = (
        f"# {entry.label}\n\nBounded preview body for {entry.label}."
        if view_mode in {"markdown", "text"}
        else ""
    )
    return FileDetailData(
        file_id=entry.id,
        resolved_stored_path=entry.path,
        stored_live=True,
        stored_mtime_ns=1_753_387_500_000_000_000,
        stored_size=entry.size_bytes,
        resolved_source_path=entry.source_path,
        source_live=None if entry.source_path is None else False,
        preview=preview,
        preview_truncated=False,
    )


async def test_artifacts_files_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    rows = _fixture_rows()
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _all_choices,
    )
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: snapshot(rows, project=project),
    )
    monkeypatch.setattr(files_pane, "load_file_detail", _fixture_detail)
    monkeypatch.setattr(
        files_pane,
        "local_now",
        lambda: datetime.fromisoformat("2026-07-24T20:00:00-04:00"),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("5", "(")
        await page.expect_state("artifacts_subtab", "files")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(
            lambda _state: pane.snapshot is not None and pane.snapshot.rows == rows
        )
        await wait_for_svg_contains(page, "release-notes artifact")
        await wait_for_svg_contains(page, "missing")
        await wait_for_visual_idle(page)

        for glyph in (*set(FILE_VIEW_MODE_GLYPHS.values()), "◆"):
            assert_page_svg_contains(page, glyph)
        for chip in ("1 images", "2 documents", "1 videos", "1 files"):
            assert_page_svg_contains(page, chip)
        for token in ("Today", "Yesterday", "[Alpha]", "[Beta]", "live", "missing"):
            assert_page_svg_contains(page, token)
        for token in ("file · markdown", "8.2 KiB", "build-log", "walkthrough"):
            assert_page_svg_contains(page, token)
        svg = page.export_svg(title="ACE Artifacts Files populated assertion")
        for color in FILE_VIEW_MODE_COLORS.values():
            assert color.casefold() in svg.casefold()

        ace_png_visual.assert_page_png(
            page,
            "artifacts_files_populated_120x40",
            title="ACE Artifacts - Files populated",
        )
