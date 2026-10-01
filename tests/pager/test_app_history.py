"""Headless Pilot history tests for the standalone ``SasePager`` app."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace.testing.wait import wait_for
from sase.pager._help import PagerHelpScreen
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import committed_pin_for_ordinal
from sase.pager.history.provider import (
    clear_history_provider_factories,
    register_history_provider_factory,
)
from sase.pager.trail import PAGER_TRAIL_LIMIT
from sase.pager.app import SasePager
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.screen import PagerScreen

from ._app_helpers import (
    body_scroll,
    long_link_source_document,
    pager_screen,
    searchable_link_source_document,
    target_document,
)


async def test_follow_back_and_forward_restore_the_view(
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
    source = long_link_source_document(Path("/tmp/target.py"))
    app = SasePager(source)
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        scroll = body_scroll(app)
        trail = screen.query_one("#pager-trail", Static)
        footer = screen.query_one("#pager-footer", Static)
        scroll.focus()
        scroll.scroll_to(y=12, animate=False, immediate=True)
        screen._update_subject()
        await pilot.pause()

        assert "hidden" in trail.classes

        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

        assert screen.document is target
        assert screen._back_trail
        assert "hidden" not in trail.classes
        assert "⌫/^O back" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("backspace")
        await pilot.pause()

        assert screen.document is source
        assert int(scroll.scroll_y) == 12
        assert not screen._back_trail
        assert screen._forward_trail
        assert "hidden" not in trail.classes
        assert "TRAIL 1/2" in trail.visual.plain  # type: ignore[attr-defined]
        assert "^I forward" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("tab")
        await pilot.pause()

        assert screen.document is target
        assert screen._back_trail
        assert not screen._forward_trail


async def test_history_band_orders_forward_entries_and_clears_branch() -> None:
    documents = {name: target_document(name) for name in ("A", "B", "C", "D", "E")}
    app = SasePager(documents["A"])
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()

        for name in ("B", "C", "D"):
            screen._apply_resolution(
                name,
                LinkTarget(kind=LinkTargetKind.DOCUMENT, document=documents[name]),
                intent="follow",
            )
            await pilot.pause()

        assert [entry.short_label for entry in screen._trail_snapshot().entries] == [
            "target.py",
            "target.py",
            "target.py",
            "target.py",
        ]
        assert screen._trail_snapshot().position == 4

        await pilot.press("backspace")
        await pilot.press("backspace")
        await pilot.press("backspace")
        await pilot.pause()

        snapshot = screen._trail_snapshot()
        assert screen.document is documents["A"]
        assert snapshot.position == 1
        assert snapshot.forward_count == 3
        assert "hidden" not in screen.query_one("#pager-trail", Static).classes

        await pilot.press("tab")
        await pilot.pause()
        assert screen.document is documents["B"]
        assert screen._trail_snapshot().position == 2

        await pilot.press("tab")
        await pilot.pause()
        assert screen.document is documents["C"]
        assert screen._trail_snapshot().position == 3

        screen._apply_resolution(
            "E",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=documents["E"]),
            intent="follow",
        )
        await pilot.pause()

        assert screen.document is documents["E"]
        assert screen._trail_snapshot().forward_count == 0


async def test_ctrl_i_remains_a_forward_history_alias() -> None:
    source = target_document("source")
    target = target_document("target")
    app = SasePager(source)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        screen._apply_resolution(
            "target",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target),
            intent="follow",
        )
        await pilot.pause()
        await pilot.press("backspace")
        await pilot.pause()

        assert screen.document is source
        assert screen._forward_trail

        await pilot.press("ctrl+i")
        await pilot.pause()

        assert screen.document is target
        assert not screen._forward_trail


def test_trail_forward_binding_keeps_tab_alias_with_ctrl_i_display() -> None:
    binding = next(b for b in PagerScreen.BINDINGS if b.action == "trail_forward")

    assert binding.key == "tab,ctrl+i"
    assert binding.key_display == "<ctrl+i>"


async def test_tab_without_forward_history_keeps_pager_open_and_focused() -> None:
    source = target_document("source")
    app = SasePager(source)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        scroll = body_scroll(app)
        scroll.focus()
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        assert app.screen is screen
        assert screen.document is source
        assert not screen._back_trail
        assert not screen._forward_trail
        assert app.focused is scroll


async def test_bounded_trail_numbering_is_retained_history_only() -> None:
    app = SasePager(target_document("root"))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()

        for index in range(PAGER_TRAIL_LIMIT + 5):
            document = target_document(f"doc-{index}")
            screen._apply_resolution(
                str(index),
                LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document),
                intent="follow",
            )
        await pilot.pause()

        snapshot = screen._trail_snapshot()
        assert snapshot.total == PAGER_TRAIL_LIMIT + 1
        assert snapshot.position == PAGER_TRAIL_LIMIT + 1
        assert snapshot.entries[0].document_title == "doc-4"


async def test_backspace_with_forward_history_still_exits_when_back_empty() -> None:
    source = target_document("source")
    target = target_document("target")
    app = SasePager(source)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        screen._apply_resolution(
            "target",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target),
            intent="follow",
        )
        await pilot.pause()
        await pilot.press("backspace")
        await pilot.pause()

        assert screen._forward_trail
        assert not screen._back_trail

        await pilot.press("backspace")
        await pilot.pause()

    assert app.return_value is not None
    assert app.return_value.trail_exhausted is True


async def test_back_restores_committed_search_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    source = searchable_link_source_document(Path("/tmp/target.py"))
    app = SasePager(source)
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        scroll = body_scroll(app)
        await pilot.press("slash")
        for character in "needle":
            await pilot.press(character)
        await pilot.press("enter")
        await pilot.pause()

        assert screen._search.mode == "committed"
        assert screen._search.last_search == ("needle", "forward")
        source_scroll_y = int(scroll.scroll_y)
        assert source_scroll_y > 0

        screen._apply_resolution(
            "/tmp/target.py",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target),
            intent="follow",
        )
        await pilot.pause()

        assert screen.document is target
        assert screen._search.mode == "off"

        await pilot.press("ctrl+o")
        await pilot.pause()

        command = screen.query_one("#pager-search-command", Static)
        assert screen.document is source
        assert int(scroll.scroll_y) == source_scroll_y
        assert screen._search.mode == "committed"
        assert screen._search.last_search == ("needle", "forward")
        assert "hidden" not in command.classes


async def test_question_mark_help_preserves_committed_search_state() -> None:
    app = SasePager(searchable_link_source_document(Path("/tmp/target.py")))
    async with app.run_test(size=(80, 12)) as pilot:
        screen = pager_screen(app)
        await pilot.press("slash")
        for character in "needle":
            await pilot.press(character)
        await pilot.press("enter")
        await pilot.pause()

        assert screen._search.mode == "committed"

        await pilot.press("question_mark")
        await pilot.pause()

        assert isinstance(app.screen, PagerHelpScreen)
        assert screen._search.mode == "committed"

        await pilot.press("question_mark")
        await pilot.pause()

        assert app.screen is screen
        assert screen._search.mode == "committed"


async def test_tab_does_not_advance_while_search_is_typing() -> None:
    source = searchable_link_source_document(Path("/tmp/target.py"))
    target = target_document()
    app = SasePager(source)
    async with app.run_test(size=(80, 12)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        screen._apply_resolution(
            "/tmp/target.py",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target),
            intent="follow",
        )
        await pilot.pause()
        await pilot.press("backspace")
        await pilot.pause()
        await pilot.press("slash")
        for character in "nee":
            await pilot.press(character)
        await pilot.pause()

        assert screen.document is source
        assert screen._search.mode == "typing"
        assert screen._search.query == "nee"

        await pilot.press("tab")
        await pilot.pause()

        assert screen.document is source
        assert screen._forward_trail
        assert screen._search.mode == "typing"
        assert screen._search.query == "nee"
        assert "hidden" not in screen.query_one("#pager-search-command", Static).classes


async def test_tab_does_not_advance_while_goto_prompt_is_open() -> None:
    source = long_link_source_document(Path("/tmp/target.py"))
    target = target_document()
    app = SasePager(source)
    async with app.run_test(size=(80, 12)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        screen._apply_resolution(
            "/tmp/target.py",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target),
            intent="follow",
        )
        await pilot.pause()
        await pilot.press("backspace")
        await pilot.pause()
        await pilot.press("colon")
        await pilot.press("1")
        await pilot.pause()

        assert screen.document is source
        assert screen._goto_active is True
        assert screen._goto_digits == "1"

        await pilot.press("tab")
        await pilot.pause()

        assert screen.document is source
        assert screen._forward_trail
        assert screen._goto_active is True
        assert screen._goto_digits == "1"
        assert "hidden" not in screen.query_one("#pager-goto-command", Static).classes


async def test_tab_does_not_advance_under_help_modal() -> None:
    source = target_document("source")
    target = target_document("target")
    app = SasePager(source)
    async with app.run_test(size=(80, 12)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        screen._apply_resolution(
            "target",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target),
            intent="follow",
        )
        await pilot.pause()
        await pilot.press("backspace")
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()

        assert isinstance(app.screen, PagerHelpScreen)
        assert screen.document is source

        await pilot.press("tab")
        await pilot.pause()

        assert isinstance(app.screen, PagerHelpScreen)
        assert screen.document is source
        assert screen._forward_trail

        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()

        assert app.screen is screen
        assert screen.document is target


class _VersionStepFakeProvider:
    """Deterministic two-version provider for version-step regression tests."""

    provider_key = "version-step-fake"
    IDENTITY = "probe:/tmp/version-step.md"

    def recognizes(self, section: PagerSection) -> bool:
        return section.identity == self.IDENTITY

    def load_timeline(self, section: PagerSection) -> dict[str, object]:
        return {
            "versions": [
                {"ordinal": 1, "commit": "a" * 40, "hidden": False},
                {"ordinal": 2, "commit": "b" * 40, "hidden": False},
            ]
        }

    def load_version(self, section: PagerSection, ordinal: int) -> PagerSection | None:
        if ordinal == 0:
            return replace(section, body="live body\nsecond line\n", version_pin=None)
        pin = committed_pin_for_ordinal(
            section.subject_ref or section.identity,
            ordinal,
            commit=("ab"[ordinal - 1]) * 40,
            blob_oid=str(ordinal) * 40,
        )
        return replace(
            section,
            body=f"version {ordinal} body\nsecond line\n",
            version_pin=pin,  # type: ignore[arg-type]
        )

    def compare_versions(
        self, section: PagerSection, base_ordinal: int, target_ordinal: int
    ) -> dict[str, object] | None:
        return {"line_marks": [1], "word_ops": [], "removal_anchors": []}

    def resolve_historical_link(
        self, section: PagerSection, ref: str
    ) -> PagerSection | None:
        return None

    def refresh(self, section: PagerSection) -> PagerSection | None:
        return replace(section, version_pin=None)


def _version_step_document() -> PagerDocument:
    section = PagerSection(
        identity=_VersionStepFakeProvider.IDENTITY,
        title="version-step.md",
        kind="file",
        body="live body\nsecond line\n",
        subject_ref=_VersionStepFakeProvider.IDENTITY,
    )
    return PagerDocument(
        sections=(section,), title="version-step.md", origin=PagerOrigin.FILE
    )


def _current_ordinal(screen: PagerScreen, identity: str) -> int | None:
    state = screen._history_states.get(identity)
    if state is None or state.current_pin is None:
        return None
    return state.current_pin.ordinal


async def test_paren_keys_step_between_now_and_newest_committed() -> None:
    """``(`` publishes the newest committed body; ``)`` restores now.

    Regression test: the history mixin used to address worker-to-UI
    callbacks through a ``call_from_thread`` helper that ``PagerScreen``
    does not provide, so no version step could ever publish, and the
    anchor-restore call passed its arguments in the wrong order.
    """
    clear_history_provider_factories()
    register_history_provider_factory(_VersionStepFakeProvider)
    try:
        identity = _VersionStepFakeProvider.IDENTITY
        app = SasePager(_version_step_document())
        async with app.run_test(size=(80, 24)) as pilot:
            screen = pager_screen(app)
            await wait_for(pilot, lambda: identity in screen._history_states)
            assert _current_ordinal(screen, identity) == 0

            await pilot.press("(")
            await wait_for(pilot, lambda: _current_ordinal(screen, identity) == 2)
            assert "version 2 body" in screen.document.sections[0].plain_text

            await pilot.press(")")
            await wait_for(pilot, lambda: _current_ordinal(screen, identity) == 0)
            assert "live body" in screen.document.sections[0].plain_text
    finally:
        clear_history_provider_factories()
