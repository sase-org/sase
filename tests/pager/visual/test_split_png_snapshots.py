"""PNG golden tests for the pager split-pane views.

Covers the stacked and side-by-side arrangements with focused-pane label
badges, a narrow stacked layout exercising border-title truncation, and the
``ctrl+w`` armed footer state.
"""

from __future__ import annotations

from typing import Any

import pytest

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.screen import PagerScreen
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


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


def _source_document() -> PagerDocument:
    body_lines = ["see /tmp/target.py for the other pane"]
    body_lines.extend(f"source line {index}" for index in range(30))
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body="\n".join(body_lines) + "\n",
        subject_ref="file:/tmp/source.py",
    )
    return PagerDocument(
        sections=(section,), title="source.py", origin=PagerOrigin.FILE
    )


def _bead_target_document() -> PagerDocument:
    body_lines = ["see /tmp/notes.py for related reading"]
    body_lines.extend(f"target bead body line {index}" for index in range(30))
    section = PagerSection(
        identity="bead:sase-1eg",
        title="sase-1eg: Pager split panes (`\\` below, `|` beside)",
        kind="bead",
        body="\n".join(body_lines) + "\n",
        subject_ref="bead:sase-1eg",
    )
    return PagerDocument(
        sections=(section,),
        title="sase-1eg · Pager split panes (`\\` below, `|` beside)",
        origin=PagerOrigin.BEAD,
    )


def _document_resolver(target: Any) -> Any:
    def resolve(ref: str, **_kwargs: Any) -> LinkTarget:
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target)

    return resolve


def _patch_resolver(monkeypatch: pytest.MonkeyPatch, target: PagerDocument) -> None:
    """Point link resolution at *target* before the pager app starts."""
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))


async def _follow_into_other_pane(pilot: Any) -> None:
    """Drive ``ctrl+w`` + label so the other pane shows the patched document."""
    await pilot.press("ctrl+w")
    await pilot.pause()
    await pilot.press("0")
    await pilot.pause(0.3)
    await pilot.pause(0.3)
    await pilot.pause()


async def test_stacked_split_bottom_focused_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_resolver(monkeypatch, _bead_target_document())
    app = SasePager(_source_document())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _follow_into_other_pane(pilot)
        screen = _pager_screen(app)
        assert len(screen.views) == 2
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.pause()
        assert screen._focused_index == 1
        assert screen.views[0]._visible_label_count() == 0
        assert screen.focused_view._visible_label_count() > 0
        pager_png_visual.assert_page_png(
            _SvgExport(app),
            "split_stacked_bottom_focused_120x40",
            title="SasePager: stacked split, bottom pane focused",
        )


async def test_beside_split_left_focused_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
) -> None:
    app = SasePager(_source_document())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        screen = _pager_screen(app)
        assert len(screen.views) == 2
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.pause()
        assert screen._focused_index == 0
        assert screen.views[1]._visible_label_count() == 0
        assert screen.focused_view._visible_label_count() > 0
        pager_png_visual.assert_page_png(
            _SvgExport(app),
            "split_beside_left_focused_120x40",
            title="SasePager: side-by-side split, left pane focused",
        )


async def test_stacked_split_narrow_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_resolver(monkeypatch, _bead_target_document())
    app = SasePager(_source_document())
    async with app.run_test(size=(60, 30)) as pilot:
        await pilot.pause()
        await _follow_into_other_pane(pilot)
        screen = _pager_screen(app)
        assert len(screen.views) == 2
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.pause()
        assert screen._focused_index == 1
        assert screen.views[0]._visible_label_count() == 0
        assert screen.focused_view._visible_label_count() > 0
        pager_png_visual.assert_page_png(
            _SvgExport(app),
            "split_stacked_bottom_focused_60x30",
            title="SasePager: stacked split at 60x30, bottom pane focused",
        )


async def test_other_pane_armed_footer_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
) -> None:
    app = SasePager(_source_document())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert _pager_screen(app)._pending_action == "other"
        pager_png_visual.assert_page_png(
            _SvgExport(app),
            "split_other_pane_armed_120x40",
            title="SasePager: ctrl+w armed footer",
        )
