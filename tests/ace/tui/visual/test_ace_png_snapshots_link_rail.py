"""ACE TUI PNG snapshots for the app-level link rail (``bead:sase-ug.6``).

The rail is yielded once at the ``AppLayoutMixin.compose`` seam between the
main container and the footer, so the point of these goldens is that it lands
in *the same place* on all three top-level tabs. Chips are injected straight
into the widget -- the same shape the ``$0`` panel goldens use -- so the frame
never depends on this machine's real artifact-link aggregate.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.relations.link_index import LinkChip
from sase.ace.tui.widgets import LinkRail
from sase.core.artifact_entry_target import ArtifactEntryTarget
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    axe_collected_data,
    patches,
    patch_startup_loaders,
    visual_agents,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture, render_svg_to_png

pytestmark = pytest.mark.visual

_SUBJECT_ACCENT = "#00D7AF"
_BEAD_TARGET = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug"))
_PLAN_TARGET = ArtifactEntryTarget("plans", ("202608/link_rail_every_tab.md",))
_ACCENTS = ("#00D7AF", "#D7AF5F", "#87AFD7", "#D75F87")
_ICONS = ("✎", "◈", "⬡", "◆")


def _chip(
    index: int,
    *,
    relation: str = "implements",
    label: str = "implements",
    directed: bool = True,
    this_is_source: bool = True,
    neighbor_ref: str | None = None,
    neighbor_target: ArtifactEntryTarget | None = _BEAD_TARGET,
    why: str = "",
    origin: str = "manual",
    created_by: str = "visual.rail",
) -> LinkChip:
    """Return a deterministic rail chip; only display fields vary."""

    return LinkChip(
        relation=relation,
        label=label,
        directed=directed,
        this_is_source=this_is_source,
        neighbor_ref=neighbor_ref or f"bead:sase-ug.{index}",
        neighbor_target=neighbor_target,
        accent=_ACCENTS[index % len(_ACCENTS)],
        icon=_ICONS[index % len(_ICONS)],
        why=why,
        origin=origin,
        uses=1,
        created_by=created_by,
        created_at="2026-08-27T04:00:00Z",
        writable=origin != "projected",
    )


def _single_inverse_chip() -> tuple[LinkChip, ...]:
    """One inbound link: the rail must key it ``$$`` and glyph it ``←``."""

    return (
        _chip(
            0,
            relation="implements",
            label="implemented-by",
            this_is_source=False,
            neighbor_ref="plan:202608/link_rail_every_tab.md",
            neighbor_target=_PLAN_TARGET,
            why="lands the approved design for the rail on every tab",
        ),
    )


def _three_chips() -> tuple[LinkChip, ...]:
    return (
        _chip(
            0,
            relation="implements",
            label="implemented-by",
            this_is_source=False,
            neighbor_ref="plan:202608/link_rail_every_tab.md",
            neighbor_target=_PLAN_TARGET,
            why="lands the approved design for the rail on every tab",
        ),
        _chip(
            1,
            relation="related",
            label="related",
            directed=False,
            neighbor_ref="bead:sase-u3",
        ),
        _chip(
            2,
            relation="cites",
            label="cites",
            neighbor_ref="research:202608/artifact_link_derivation.md",
            neighbor_target=_PLAN_TARGET,
        ),
    )


def _twelve_chips() -> tuple[LinkChip, ...]:
    """Twelve links: three overflow past the nine direct keys into ``$0``."""

    return _three_chips() + tuple(
        _chip(index, neighbor_ref=f"bead:sase-u{index:x}") for index in range(3, 12)
    )


def _dangling_chips() -> tuple[LinkChip, ...]:
    """A dangling row still counts as a link: dim, ``⊘``, ``(missing)``."""

    return (
        _chip(
            0,
            relation="implements",
            label="implemented-by",
            this_is_source=False,
            neighbor_ref="plan:202608/link_rail_every_tab.md",
            neighbor_target=_PLAN_TARGET,
            why="lands the approved design for the rail on every tab",
        ),
        _chip(
            1,
            relation="derives-from",
            label="derives-from",
            neighbor_ref="bead:sase-deleted.7",
            neighbor_target=None,
            origin="projected",
            created_by="projection:stitch-bead",
        ),
    )


def _freeze_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the app from repainting the rail from the real link index.

    ``refresh_link_rail`` would otherwise clear the injected chips and kick
    off a background build against this machine's own aggregate, which is
    exactly the non-determinism a golden cannot tolerate.
    """

    def _no_refresh(*_args: object) -> None:
        return None

    monkeypatch.setattr(AceApp, "refresh_link_rail", _no_refresh, raising=False)


async def _paint_rail(page: AcePage, chips: Sequence[LinkChip]) -> LinkRail:
    rail = page.app.query_one("#link-rail", LinkRail)
    rail.update_links(chips, subject_accent=_SUBJECT_ACCENT)
    await wait_for_svg_contains(page, "LINKS")
    await wait_for_visual_idle(page)
    return rail


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "link_rail_agents_single_link_120x40"),
        ((60, 30), "link_rail_agents_single_link_60x30"),
    ],
)
async def test_link_rail_agents_single_link_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    snapshot_name: str,
) -> None:
    """n=1 teaches ``$$`` rather than ``$1``, with an inverse-direction label."""

    _freeze_rail(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=visual_agents())

    async with AcePage(
        query='"visual"', patches=patches(), size=size, initial_tab="agents"
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await _paint_rail(page, _single_inverse_chip())

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title="ACE link rail agents single link",
        )


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "link_rail_artifacts_three_links_120x40"),
        ((60, 30), "link_rail_artifacts_three_links_60x30"),
    ],
)
async def test_link_rail_artifacts_three_links_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    snapshot_name: str,
) -> None:
    """Three links exercise the mixed direction glyphs and the sigil tail."""

    _freeze_rail(monkeypatch)
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"', patches=patches(), size=size, initial_tab="artifacts"
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "artifacts")
        await _paint_rail(page, _three_chips())

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title="ACE link rail artifacts three links",
        )


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "link_rail_axe_twelve_links_120x40"),
        ((60, 30), "link_rail_axe_twelve_links_60x30"),
    ],
)
async def test_link_rail_axe_twelve_links_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    snapshot_name: str,
) -> None:
    """Past nine direct keys the tail is absorbed into ``$0 +k more``."""

    _freeze_rail(monkeypatch)
    patch_startup_loaders(monkeypatch, axe_data=axe_collected_data())

    async with AcePage(
        query='"visual"', patches=patches(), size=size, initial_tab="axe"
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "axe")
        await _paint_rail(page, _twelve_chips())

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title="ACE link rail axe twelve links",
        )


async def test_link_rail_dangling_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hiding a dangling link would under-report the graph, so it renders."""

    _freeze_rail(monkeypatch)
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"', patches=patches(), initial_tab="artifacts"
    ) as page:
        await wait_for_startup(page)
        await _paint_rail(page, _dangling_chips())
        await wait_for_svg_contains(page, "(missing)")

        ace_png_visual.assert_page_png(
            page,
            "link_rail_dangling_row_120x40",
            title="ACE link rail dangling row",
        )


async def test_zero_link_selection_is_pixel_identical_to_no_rail_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The invisibility contract, asserted the strongest way available.

    A cleared rail must not merely *look* empty: it must occupy no rows, so
    the frame has to rasterize identically to one where the widget was never
    mounted. This needs no golden -- it compares two captures of the same
    running app against each other.
    """

    _freeze_rail(monkeypatch)
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"', patches=patches(), initial_tab="artifacts"
    ) as page:
        await wait_for_startup(page)
        rail = page.app.query_one("#link-rail", LinkRail)
        rail.clear()
        await wait_for_visual_idle(page)
        cleared_png = render_svg_to_png(page.export_svg(title="cleared"))

        await rail.remove()
        await wait_for_visual_idle(page)
        unmounted_png = render_svg_to_png(page.export_svg(title="cleared"))

    assert cleared_png == unmounted_png
