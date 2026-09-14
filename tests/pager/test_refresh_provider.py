"""Tests for the live document-refresh provider threaded through `r`."""

from __future__ import annotations

from textual.widgets import Static

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection

from ._app_helpers import pager_screen


def _document(body: str, *, identity: str = "sec") -> PagerDocument:
    section = PagerSection(identity=identity, title="one", kind="file", body=body)
    return PagerDocument(sections=(section,), title="doc", origin=PagerOrigin.FILE)


async def test_r_without_a_provider_keeps_the_legacy_recompose_behavior() -> None:
    app = SasePager(_document("first\n"))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        original_document = screen.document

        await pilot.press("r")
        await pilot.pause()

        assert screen.document is original_document


async def test_r_swaps_in_the_refreshed_document() -> None:
    calls: list[int] = []

    def refresh() -> PagerDocument:
        calls.append(1)
        return _document("second\n", identity="sec")

    app = SasePager(_document("first\n", identity="sec"), refresh_document_fn=refresh)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause(0.2)
        await pilot.pause(0.2)

        assert calls == [1]
        assert screen.document.sections[0].plain_text == "second\n"


async def test_r_keeps_the_current_document_when_the_provider_returns_none() -> None:
    def refresh() -> PagerDocument | None:
        return None

    original = _document("first\n")
    app = SasePager(original, refresh_document_fn=refresh)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause(0.2)
        await pilot.pause(0.2)

        assert screen.document is original
        footer = screen.query_one("#pager-footer", Static)
        assert "keeping current document" in footer.visual.plain  # type: ignore[attr-defined]


async def test_r_keeps_the_current_document_when_the_provider_raises() -> None:
    def refresh() -> PagerDocument:
        raise RuntimeError("boom")

    original = _document("first\n")
    app = SasePager(original, refresh_document_fn=refresh)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause(0.2)
        await pilot.pause(0.2)

        assert screen.document is original


async def test_r_coalesces_overlapping_refresh_requests() -> None:
    calls: list[int] = []

    def refresh() -> PagerDocument:
        calls.append(1)
        return _document(f"snapshot {len(calls)}\n", identity="sec")

    app = SasePager(_document("first\n", identity="sec"), refresh_document_fn=refresh)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()

        await pilot.press("r")
        await pilot.press("r")
        await pilot.pause(0.2)
        await pilot.pause(0.2)

        # The second press lands while the first refresh is still in flight
        # and is dropped by the coalescing guard rather than queued.
        assert calls == [1]
        assert screen.document.sections[0].plain_text == "snapshot 1\n"
