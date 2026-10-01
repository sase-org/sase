"""Pilot tests for the reading anchor: the top logical line survives width changes."""

from __future__ import annotations

import pytest

from sase.pager._layout import reading_anchor_at_row
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.resolve import LinkTarget, LinkTargetKind

from ._app_helpers import body_scroll, pager_view, target_document


def _wrapped_document(extra: str = "") -> PagerDocument:
    filler = "".join(f"{'x' * 60} {index:02d}\n" for index in range(40))
    section = PagerSection(
        identity="file:/tmp/wrapped.py",
        title="wrapped.py",
        kind="file",
        body=filler + extra,
    )
    return PagerDocument(
        sections=(section,), title="wrapped.py", origin=PagerOrigin.FILE
    )


def _top_line(app: SasePager) -> tuple[int, int]:
    view = pager_view(app)
    assert view._body is not None
    anchor = reading_anchor_at_row(view._body, int(body_scroll(app).scroll_y))
    return (anchor.section_index, anchor.line)


async def test_narrow_and_widen_keeps_the_top_logical_line() -> None:
    app = SasePager(_wrapped_document())
    async with app.run_test(size=(100, 16)) as pilot:
        scroll = body_scroll(app)
        for _ in range(10):
            await pilot.press("j")
        await pilot.pause()
        assert int(scroll.scroll_y) == 10
        assert _top_line(app) == (0, 11)

        await pilot.resize_terminal(50, 16)
        await pilot.pause()
        await pilot.pause()
        assert _top_line(app) == (0, 11)

        await pilot.resize_terminal(100, 16)
        await pilot.pause()
        await pilot.pause()
        assert _top_line(app) == (0, 11)


async def test_trail_back_lands_on_the_recorded_line_after_a_width_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref, **_kwargs: LinkTarget(
            kind=LinkTargetKind.DOCUMENT,
            document=target,
        ),
    )
    source = _wrapped_document(extra="see /tmp/reading-anchor-target.py end\n")
    app = SasePager(source)
    async with app.run_test(size=(100, 16)) as pilot:
        view = pager_view(app)
        for _ in range(10):
            await pilot.press("j")
        await pilot.pause()
        assert _top_line(app) == (0, 11)

        await pilot.press("0")
        await pilot.pause()
        await pilot.pause()
        assert view.document is target

        await pilot.resize_terminal(50, 16)
        await pilot.pause()
        await pilot.pause()

        await pilot.press("backspace")
        await pilot.pause()
        await pilot.pause()
        assert view.document is source
        assert _top_line(app) == (0, 11)
