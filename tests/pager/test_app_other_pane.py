"""Headless Pilot other-pane-follow (``ctrl+w``) tests for ``SasePager``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Static

from sase.pager.app import SasePager
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.split import PagerSplitLayout

from ._app_helpers import (
    attached_target_document,
    link_document,
    pager_screen,
    pager_view,
    path_link_document,
    target_document,
)


def _footer_text(app: SasePager) -> str:
    footer = pager_screen(app).query_one("#pager-footer", Static)
    visual = getattr(footer, "visual", None)
    if visual is not None:
        return str(visual.plain)
    content = getattr(footer, "_content", "")
    return str(getattr(content, "plain", content))


def _document_resolver(target: Any) -> Any:
    def resolve(ref: str, **_kwargs: Any) -> LinkTarget:
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target)

    return resolve


async def test_ctrl_w_arms_other_pane_and_names_it_in_the_footer() -> None:
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen._pending_action == "other"
        assert "^W… other pane" in _footer_text(app)


async def test_single_ctrl_w_label_opens_stacked_split_with_focus_on_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    source_path = Path("/tmp/target.py")
    app = SasePager(path_link_document(source_path))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source = pager_view(app).document
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.3)
        await pilot.pause(0.3)
        await pilot.pause()
        assert len(screen.views) == 2
        assert screen._split_state.layout is PagerSplitLayout.BELOW
        assert screen._focused_index == 0
        assert screen.views[0].document is source
        assert screen.views[1].document is target
        assert screen._pending_action == "follow"


async def test_backspace_in_new_pane_returns_to_source_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source = pager_view(app).document
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.3)
        await pilot.pause(0.3)
        await pilot.pause()
        assert len(screen.views) == 2
        # The new pane pushed the source view onto its trail before
        # navigating, so walking back restores the source document.
        assert screen.views[1]._back_trail
        assert screen.views[1]._back_trail[-1].document is source
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert screen._focused_index == 1
        await pilot.press("backspace")
        await pilot.pause()
        await pilot.pause()
        assert screen.views[1].document is source


async def test_split_ctrl_w_label_navigates_other_pane_and_keeps_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source = pager_view(app).document
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert screen._focused_index == 0
        other = screen.views[1]
        other_document = other.document
        assert other_document is source
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.3)
        await pilot.pause(0.3)
        await pilot.pause()
        assert screen.views[0].document is source
        assert other.document is target
        assert other._back_trail
        assert other._back_trail[-1].document is source
        assert screen._focused_index == 0


async def test_doubled_ctrl_w_swaps_focus_in_a_split() -> None:
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert screen._focused_index == 1
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen._pending_action == "other"
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen._pending_action == "follow"
        assert screen._focused_index == 0
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen._focused_index == 1


async def test_doubled_ctrl_w_when_single_clears_the_arm() -> None:
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen._pending_action == "other"
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen._pending_action == "follow"
        assert len(screen.views) == 1
        assert app.is_running


async def test_ctrl_w_then_url_label_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    app = SasePager(link_document(2))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause(0.2)
        await pilot.pause(0.2)

    assert copied == ["https://example.test/1"]
    assert len(screen.views) == 1
    assert screen._pending_action == "follow"


async def test_attached_handler_receives_follow_for_other_pane_arm() -> None:
    calls: list[tuple[str, str]] = []
    app = SasePager(
        attached_target_document(),
        attached_handlers={
            "commit": lambda target, action: calls.append((str(target.target), action))
        },
    )
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause()

    assert calls == [("commit-object", "follow")]
    assert len(screen.views) == 1


async def test_unresolvable_target_notifies_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.pager.screen.resolve_ref", lambda ref, **_kwargs: None)
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(path_link_document(Path("/tmp/target.py")))
    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source = pager_view(app).document
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.3)
        await pilot.pause(0.3)
        assert notifications
        assert all(severity == "warning" for _, severity in notifications)
        assert len(screen.views) == 1
        assert pager_view(app).document is source
        assert screen._pending_action == "follow"


async def test_escape_cancels_the_arm_without_closing() -> None:
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen._pending_action == "other"
        await pilot.press("escape")
        await pilot.pause()
        assert screen._pending_action == "follow"
        assert app.is_running
        assert len(screen.views) == 1


async def test_no_room_fallback_follows_in_place_with_a_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(path_link_document(Path("/tmp/target.py")))
    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(40, 10)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.3)
        await pilot.pause(0.3)
        await pilot.pause()
        assert len(screen.views) == 1
        assert pager_view(app).document is target
        assert ("No room for a split — opened here.", "information") in notifications
