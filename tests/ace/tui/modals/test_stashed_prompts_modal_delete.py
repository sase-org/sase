"""Tests for partial-delete-keep-open behavior in the stashed-prompts modal."""

from textual.widgets import Label

from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
)
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import (
    ModalHost,
    make_entry,
)


async def test_partial_delete_then_restore_remaining() -> None:
    app = ModalHost(
        [
            make_entry("a", created_at="2026-06-16T12:00:00"),
            make_entry("b", created_at="2026-06-16T11:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        await pilot.press("d")  # delete mark on "a"
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == "UNSET"
        assert [e.id for e in modal._entries] == ["b"]
        await pilot.press("enter")  # no marks: restore highlighted "b"
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["b"]
    assert app.result.delete_ids == []


async def test_multiple_delete_marks_keep_order_and_surviving_highlight() -> None:
    app = ModalHost(
        [
            make_entry("a", created_at="2026-06-16T12:00:00"),
            make_entry("b", created_at="2026-06-16T11:00:00"),
            make_entry("c", created_at="2026-06-16T10:00:00"),
            make_entry("d", created_at="2026-06-16T09:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        await pilot.press("d")  # mark "a"
        await pilot.press("j")
        await pilot.press("j")  # highlight "c"
        await pilot.press("d")  # mark "c"
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == "UNSET"
        assert app.screen is modal
        assert len(app.delete_events) == 1
        assert app.delete_events[0].entry_ids == ["a", "c"]
        assert [e.id for e in modal._entries] == ["b", "d"]
        assert modal._deleted == set()
        assert (
            str(modal.query_one("#stashed-prompts-title", Label).content)
            == "Stashed prompts (2)"
        )
        highlighted = modal._highlighted_entry()
        assert highlighted is not None
        assert highlighted.id in {"b", "d"}


async def test_delete_all_then_unmark_one_keeps_single_row() -> None:
    app = ModalHost(
        [
            make_entry("a", created_at="2026-06-16T12:00:00"),
            make_entry("b", created_at="2026-06-16T11:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        await pilot.press("D")  # mark both
        await pilot.press("d")  # unmark highlighted "a"
        await pilot.pause()
        assert modal._deleted == {"b"}
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == "UNSET"
        assert len(app.delete_events) == 1
        assert app.delete_events[0].entry_ids == ["b"]
        assert [e.id for e in modal._entries] == ["a"]
        assert (
            str(modal.query_one("#stashed-prompts-title", Label).content)
            == "Stashed prompts (1)"
        )


async def test_pins_survive_partial_delete() -> None:
    app = ModalHost(
        [
            make_entry("p", pinned=True, created_at="2026-06-16T12:00:00"),
            make_entry("u", created_at="2026-06-16T11:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        await pilot.press("j")  # highlight "u"
        await pilot.press("d")
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == "UNSET"
        assert [e.id for e in modal._entries] == ["p"]
        assert modal._pinned == {"p"}
        await pilot.press("enter")  # restore pinned survivor
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.keep_ids == ["p"]
    assert app.result.pop_ids == []
    assert app.result.delete_ids == []


async def test_mixed_restore_and_delete_still_dismisses() -> None:
    app = ModalHost(
        [
            make_entry("a", created_at="2026-06-16T12:00:00"),
            make_entry("b", created_at="2026-06-16T11:00:00"),
            make_entry("c", created_at="2026-06-16T10:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("tab")  # restore "a"
        await pilot.press("j")  # highlight "b"
        await pilot.press("d")  # delete "b"
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["a"]
    assert app.result.delete_ids == ["b"]
    assert app.delete_events == []
