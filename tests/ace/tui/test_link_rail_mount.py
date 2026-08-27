"""The mounted LinkRail must actually get rows to paint in (bead:sase-ug).

``test_link_rail`` covers ``_render_link_rail`` in isolation, which is blind
to the widget's box: the rail once carried a ``border-top`` inside a fixed
one-row, border-box budget, so it composed a perfect line of chips into zero
content rows and only its own rule reached the screen. These tests assert the
mounted geometry the pure-render tests cannot see.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.relations.link_index import LinkChip
from sase.ace.tui.widgets import LinkRail
from sase.core.artifact_entry_target import ArtifactEntryTarget

_TARGET = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug"))


def _chip() -> LinkChip:
    return LinkChip(
        relation="implements",
        label="implemented-by",
        directed=True,
        this_is_source=False,
        neighbor_ref="plan:202608/link_rail_every_tab.md",
        neighbor_target=_TARGET,
        accent="#00D7AF",
        icon="✎",
        why="lands the approved design for the rail on every tab",
        origin="manual",
        uses=1,
        created_by="tester",
        created_at="2026-08-27T04:00:00Z",
        writable=True,
    )


def _freeze_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real link index off this machine's own aggregate."""

    def _no_refresh(*_args: object) -> None:
        return None

    monkeypatch.setattr(AceApp, "refresh_link_rail", _no_refresh, raising=False)


async def test_mounted_rail_paints_its_chips_into_a_real_content_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_rail(monkeypatch)

    async with AcePage(initial_tab="artifacts") as page:
        rail = page.app.query_one("#link-rail", LinkRail)
        rail.update_links((_chip(),), subject_accent="#00D7AF")
        await page.pause()

        assert rail.display is True
        assert rail.size.height >= 1, (
            "the rail composed chips into a zero-row box; "
            f"outer={rail.outer_size} content={rail.content_size}"
        )
        assert "LINKS" in page.export_svg()


async def test_cleared_rail_leaves_no_trace_in_the_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_rail(monkeypatch)

    async with AcePage(initial_tab="artifacts") as page:
        rail = page.app.query_one("#link-rail", LinkRail)
        rail.update_links((_chip(),), subject_accent="#00D7AF")
        await page.pause()
        rail.clear()
        await page.pause()

        assert rail.display is False
        assert "LINKS" not in page.export_svg()
