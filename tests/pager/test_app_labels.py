"""Headless Pilot label tests for the standalone ``SasePager`` app."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.resolve import LinkTarget, LinkTargetKind

from ._app_helpers import (
    link_document,
    pager_screen,
    path_link_document,
    target_document,
)


async def test_painted_link_key_records_the_selected_label() -> None:
    app = SasePager(link_document(2))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    assert screen._last_activated_label is not None
    assert screen._last_activated_label.hint == "1"
    assert screen._last_activated_label.target.text == "https://example.test/1"


async def test_uppercase_painted_link_key_uses_event_character() -> None:
    app = SasePager(link_document(30))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()

    assert screen._last_activated_label is not None
    assert screen._last_activated_label.hint == "A"


async def test_pending_prefix_is_shown_in_the_footer_and_invalid_clears_it() -> None:
    app = SasePager(link_document(53))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("Z")
        await pilot.pause()

        footer = screen.query_one("#pager-footer", Static)
        assert "Z… link" in footer.visual.plain  # type: ignore[attr-defined]
        assert screen._label_pending_prefix == "Z"

        await pilot.press("x")
        await pilot.pause()

        footer = screen.query_one("#pager-footer", Static)
        assert "Z… link" not in footer.visual.plain  # type: ignore[attr-defined]
        assert screen._label_pending_prefix == ""


async def test_footer_offers_copy_and_edit_once_links_are_painted() -> None:
    app = SasePager(link_document(2))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = pager_screen(app).query_one("#pager-footer", Static)
        assert "y copy" in footer.visual.plain  # type: ignore[attr-defined]
        assert "E edit" in footer.visual.plain  # type: ignore[attr-defined]


async def test_pressing_a_label_follows_it_into_a_new_document(
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
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert screen.document is target


async def test_pressing_a_label_passes_merged_context_to_resolver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    section_anchor = tmp_path / "section"
    document_anchor = tmp_path / "document"
    section_anchor.mkdir()
    document_anchor.mkdir()
    target = target_document()
    calls: list[tuple[str, LinkResolutionContext | None]] = []

    def fake_resolve(
        ref: str,
        *,
        context: LinkResolutionContext | None = None,
    ) -> LinkTarget:
        calls.append((ref, context))
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target)

    monkeypatch.setattr("sase.pager.screen.resolve_ref", fake_resolve)
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body="see src/target.py\n",
        link_anchors=(LinkAnchor(section_anchor),),
    )
    document = PagerDocument(
        sections=(section,),
        title="source.py",
        origin=PagerOrigin.FILE,
        link_context=LinkResolutionContext(
            anchors=(LinkAnchor(document_anchor),),
        ),
    )
    app = SasePager(document)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert calls[0][0] == "src/target.py"
    assert calls[0][1] is not None
    assert calls[0][1].base_dirs == (section_anchor, document_anchor)
