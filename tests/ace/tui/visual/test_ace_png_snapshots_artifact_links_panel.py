"""ACE TUI PNG snapshots for the artifact links inspector panel."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.artifact_links_panel_modal import ArtifactLinksPanelModal
from sase.ace.tui.relations.link_index import LinkChip
from sase.core.artifact_entry_target import ArtifactEntryTarget
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


_DEFAULT_TARGET = ArtifactEntryTarget(
    "beads",
    ("demo", "task", "sase-ug.9"),
)
_ACCENTS = ("#00D7AF", "#D7AF5F", "#87AFD7", "#D75F87")
_ICONS = ("✎", "◈", "⬡", "◆")


def _chip(
    index: int,
    *,
    relation: str = "implements",
    label: str = "implemented-by",
    directed: bool = True,
    this_is_source: bool = True,
    neighbor_ref: str | None = None,
    neighbor_target: ArtifactEntryTarget | None = _DEFAULT_TARGET,
    why: str | None = None,
    origin: str = "manual",
    created_by: str = "visual.panel",
    created_at: str = "2026-08-26T16:40:00Z",
    writable: bool = True,
) -> LinkChip:
    """Return a deterministic link chip for panel rendering snapshots."""

    return LinkChip(
        relation=relation,
        label=label,
        directed=directed,
        this_is_source=this_is_source,
        neighbor_ref=neighbor_ref or f"bead:sase-ug.{index}",
        neighbor_target=neighbor_target,
        accent=_ACCENTS[index % len(_ACCENTS)],
        icon=_ICONS[index % len(_ICONS)],
        why=why
        or (
            "The panel keeps the full link rationale visible instead of "
            "truncating it into the compact rail."
        ),
        origin=origin,
        uses=index + 1,
        created_by=created_by,
        created_at=created_at,
        writable=writable,
    )


def _three_link_chips() -> tuple[LinkChip, ...]:
    return (
        _chip(
            0,
            relation="implements",
            label="implemented-by",
            neighbor_ref="bead:sase-ug.4",
            why="Builds the app-owned rail that exposes artifact links everywhere.",
        ),
        _chip(
            1,
            relation="cites",
            label="cites",
            directed=True,
            neighbor_ref="file:plans/202608/link_rail_every_tab.md",
            why="Grounds the UI behavior in the approved design file.",
        ),
        _chip(
            2,
            relation="related",
            label="related",
            directed=False,
            neighbor_ref="stitch:sase@8f5b1d2e0",
            why="Keeps the implementation tied to the stitch that introduced it.",
        ),
    )


def _twenty_six_link_chips() -> tuple[LinkChip, ...]:
    return tuple(
        _chip(
            index,
            neighbor_ref=f"file:docs/linked-artifact-{index:02}.md",
            why=f"Overflow row {index:02} remains addressable by the a-z panel keys.",
        )
        for index in range(26)
    )


def _dangling_chips() -> tuple[LinkChip, ...]:
    return (
        _chip(0),
        _chip(
            1,
            neighbor_ref="bead:sase-missing.7",
            neighbor_target=None,
            origin="projected",
            created_by="projection:stitch-bead",
            writable=False,
            why="The target no longer resolves but the link still explains why it exists.",
        ),
        _chip(2, relation="launched", label="launched"),
    )


async def _assert_panel_snapshot(
    *,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    snapshot_name: str,
    title: str,
    chips: Sequence[LinkChip],
    wait_text: str,
    scoped_label: str | None = None,
    staleness_notice: str = "",
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=size) as page:
        await wait_for_startup(page)
        page.app.push_screen(
            ArtifactLinksPanelModal(
                subject_ref="file:origin.txt",
                chips=chips,
                scoped_label=scoped_label,
                add_enabled=True,
                staleness_notice=staleness_notice,
            )
        )
        await page.expect_modal("ArtifactLinksPanelModal")
        await wait_for_svg_contains(page, wait_text)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "artifact_links_panel_3_links_120x40"),
        ((60, 30), "artifact_links_panel_3_links_60x30"),
    ],
)
async def test_artifact_links_panel_three_links_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    snapshot_name: str,
) -> None:
    await _assert_panel_snapshot(
        ace_png_visual=ace_png_visual,
        monkeypatch=monkeypatch,
        size=size,
        snapshot_name=snapshot_name,
        title="ACE artifact links panel three links",
        chips=_three_link_chips(),
        scoped_label="3 stitches",
        wait_text="3 links",
    )


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "artifact_links_panel_26_links_120x40"),
        ((60, 30), "artifact_links_panel_26_links_60x30"),
    ],
)
async def test_artifact_links_panel_twenty_six_links_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    snapshot_name: str,
) -> None:
    await _assert_panel_snapshot(
        ace_png_visual=ace_png_visual,
        monkeypatch=monkeypatch,
        size=size,
        snapshot_name=snapshot_name,
        title="ACE artifact links panel twenty six links",
        chips=_twenty_six_link_chips(),
        wait_text="26 links",
    )


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "artifact_links_panel_dangling_row_120x40"),
        ((60, 30), "artifact_links_panel_dangling_row_60x30"),
    ],
)
async def test_artifact_links_panel_dangling_row_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    snapshot_name: str,
) -> None:
    await _assert_panel_snapshot(
        ace_png_visual=ace_png_visual,
        monkeypatch=monkeypatch,
        size=size,
        snapshot_name=snapshot_name,
        title="ACE artifact links panel dangling row",
        chips=_dangling_chips(),
        wait_text="missing",
    )


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "artifact_links_panel_staleness_notice_120x40"),
        ((60, 30), "artifact_links_panel_staleness_notice_60x30"),
    ],
)
async def test_artifact_links_panel_staleness_notice_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    snapshot_name: str,
) -> None:
    await _assert_panel_snapshot(
        ace_png_visual=ace_png_visual,
        monkeypatch=monkeypatch,
        size=size,
        snapshot_name=snapshot_name,
        title="ACE artifact links panel staleness notice",
        chips=_three_link_chips(),
        staleness_notice="Index stale: aggregate has 3 stale rows and 1 missing target.",
        wait_text="Index stale",
    )
