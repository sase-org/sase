"""ACE PNG snapshots for the context-aware Copy as palette."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.modals.artifact_files_modal import ArtifactFileSelectionModal
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.core.artifact_file_types import ArtifactFile
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload
from sase.ace.tui.widgets.artifacts import CommitsPane
from tests.ace.tui._commits_pane_helpers import _DIFF, _result
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> commits_module.VcsLogResult:
    reference = datetime(2026, 7, 7, 12, tzinfo=UTC)
    result = _result(int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp()))
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: ("/tmp/sase.sase", 1, "sase"),
    )
    monkeypatch.setattr(
        "sase.ace.query.profile_reference_support.normalize_reference_time",
        lambda: reference,
    )
    monkeypatch.setattr("sase.vcs_log._render_util._now_epoch", reference.timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: _ArtifactsProjectChoices((), (), {}),
    )
    return result


async def _open_commits_palette(
    page: AcePage,
    result: commits_module.VcsLogResult,
) -> CommitsPane:
    await wait_for_startup(page)
    await page.expect_state("artifacts_subtab", "stitches")
    pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
    await page.wait_for(lambda _state: pane.result is result)
    await page.press("%")
    await page.expect_modal("CopyAsModal")
    await wait_for_svg_contains(page, "Copy as")
    await wait_for_visual_idle(page)
    return pane


async def test_copy_as_stitches_selected_dark_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    result = _patch_commits(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_commits_palette(page, result)

        ace_png_visual.assert_page_png(
            page,
            "copy_as_stitches_selected_dark_120x40",
            title="ACE Copy as palette — selected commit, dark theme",
        )


async def test_copy_as_stitches_marked_light_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    result = _patch_commits(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(80, 30),
        patches=patches(),
    ) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)

        await page.press("m", "j", "m")
        await page.wait_for(
            lambda _state: (
                len(page.app._artifacts_marked_targets.get("stitches", set())) == 2
            )
        )
        await page.press("%")
        await page.expect_modal("CopyAsModal")
        await wait_for_svg_contains(page, "2 marked stitches")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "copy_as_stitches_marked_light_80x30",
            title="ACE Copy as palette — marked stitches, light narrow layout",
        )


async def test_copy_as_over_preview_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    result = _patch_commits(monkeypatch)
    payload = PreviewPayload(
        kind_label="plan",
        icon="@",
        title="copy_as_palette.md",
        source_path="/workspace/plans/copy_as_palette.md",
        lexer="markdown",
        content=(
            "# Copy as palette\n\n"
            "The copy prefix opens a warm-only representation picker.\n\n"
            "- Direct accelerators remain available.\n"
            "- Snapshot capture happens after dismissal.\n"
        ),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        page.app.push_screen(PreviewPanelModal(payload))
        await page.expect_modal("PreviewPanelModal")
        await wait_for_svg_contains(page, "Snapshot capture")

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        await wait_for_svg_contains(page, "Copy as")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "copy_as_over_preview_panel_dark_120x40",
            title="ACE Copy as palette — stacked over preview panel",
        )


async def test_copy_as_over_artifact_files_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_commits(monkeypatch)
    artifact_files = [
        ArtifactFile(
            id="explicit:111111111111111111111111",
            label="Copy as palette design",
            kind="markdown",
            path="/home/visual/.sase/artifacts/copy_as_palette.md",
            source_path="docs/copy_as_palette.md",
            workspace_dir="/home/visual/workspace",
            project="sase",
            explicit=True,
            sha256="a" * 64,
            size_bytes=4096,
            mime_type="text/markdown",
        ),
        ArtifactFile(
            id="explicit:222222222222222222222222",
            label="Palette preview",
            kind="image",
            path="/home/visual/.sase/artifacts/copy_as_palette.png",
            project="sase",
            explicit=True,
            sha256="b" * 64,
            size_bytes=24_576,
            mime_type="image/png",
        ),
    ]

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(ArtifactFileSelectionModal(artifact_files))
        await page.expect_modal("ArtifactFileSelectionModal")
        await page.press("m", "m", "%")
        await page.expect_modal("CopyAsModal")
        await wait_for_svg_contains(page, "marked artifact files")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "copy_as_over_artifact_files_modal_dark_120x40",
            title="ACE Copy as palette — artifact file representations",
        )
