"""PNG golden tests for the standalone `SasePager` reading surface.

Covers the two cases the `viewer` phase itself can produce: a document with
no scanned links yet (link scanning is the `labels` phase's job) and a
multi-section document scrolled so a transition rule sits mid-screen.
"""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.screen import PagerScreen
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_SIZES = [(120, 40), (60, 30)]


class _SvgExport:
    """Adapt a bare Textual ``App`` to the ``SvgExporter`` protocol."""

    def __init__(self, app: SasePager) -> None:
        self._app = app

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        return self._app.export_screenshot(title=title, simplify=simplify)


def _pager_screen(app: SasePager) -> PagerScreen:
    screen = app.screen
    assert isinstance(screen, PagerScreen)
    return screen


def _zero_link_document() -> PagerDocument:
    section = PagerSection(
        identity="bead:sase-uk.3",
        title="sase-uk.3: The reading surface",
        kind="bead",
        body=(
            "viewer: build the SasePager Textual app shell -- the sticky\n"
            "chrome band, section rules, scrolling, ctrl+n/ctrl+p\n"
            "scroll-to-header, the availability-driven footer legend, and\n"
            "the re-hosted VimSearchController -- wired to no caller yet.\n"
        ),
        subject_ref="bead:sase-uk.3",
    )
    return PagerDocument(
        sections=(section,),
        title="sase-uk.3 · The reading surface",
        origin=PagerOrigin.BEAD,
    )


def _three_section_document() -> PagerDocument:
    def section(name: str) -> PagerSection:
        body = "\n".join(f"{name} line {index}" for index in range(40)) + "\n"
        return PagerSection(
            identity=f"file:/tmp/{name}.py", title=f"{name}.py", kind="file", body=body
        )

    sections = (section("alpha"), section("beta"), section("gamma"))
    return PagerDocument(sections=sections, title="3 files", origin=PagerOrigin.FILE)


@pytest.mark.parametrize("size", _SIZES)
async def test_zero_link_document_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
    size: tuple[int, int],
) -> None:
    app = SasePager(_zero_link_document())
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        pager_png_visual.assert_page_png(
            _SvgExport(app),
            f"zero_link_document_{size[0]}x{size[1]}",
            title="SasePager: zero-link document",
        )


@pytest.mark.parametrize("size", _SIZES)
async def test_three_section_document_mid_rule_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
    size: tuple[int, int],
) -> None:
    app = SasePager(_three_section_document())
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        screen = _pager_screen(app)
        assert screen._body is not None
        scroll = screen.query_one("#pager-body-scroll", VerticalScroll)
        target_row = max(screen._body.section_offsets[1] - size[1] // 2, 0)
        scroll.scroll_to(y=target_row, animate=False, immediate=True)
        screen._update_subject()
        await pilot.pause()
        pager_png_visual.assert_page_png(
            _SvgExport(app),
            f"three_section_mid_rule_{size[0]}x{size[1]}",
            title="SasePager: three-section document mid-rule",
        )
