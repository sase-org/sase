"""Tests for direct restore and pin shortcuts in the stashed-prompts modal."""

from rich.text import Text

from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
)
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import (
    ModalHost,
    make_entry,
)


async def test_enter_with_no_toggle_restores_highlighted() -> None:
    app = ModalHost([make_entry("a"), make_entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("enter")  # confirm highlighted (first row)
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["a"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_enter_with_no_toggle_keeps_pinned_highlighted_bundle() -> None:
    app = ModalHost([make_entry("bundle", "one\n---\ntwo", pinned=True)])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == ["bundle"]
    assert app.result.delete_ids == []


async def test_enter_with_no_toggle_keeps_pinned_highlighted_row() -> None:
    app = ModalHost([make_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("space")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == ["a"]
    assert app.result.delete_ids == []


async def test_digit_restores_unpinned_row_to_pop() -> None:
    app = ModalHost(
        [
            make_entry("first", created_at="2026-06-16T12:00:00"),
            make_entry("target", created_at="2026-06-16T11:00:00"),
            make_entry("third", created_at="2026-06-16T10:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["target"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_digit_restores_pinned_row_to_keep() -> None:
    app = ModalHost(
        [
            make_entry("first", created_at="2026-06-16T12:00:00"),
            make_entry("target", created_at="2026-06-16T11:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("space")
        await pilot.press("2")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == ["target"]
    assert app.result.delete_ids == []


async def test_zero_restores_tenth_row() -> None:
    entries = [
        make_entry(
            f"row-{idx + 1}",
            created_at=f"2026-06-16T{23 - idx:02d}:00:00",
        )
        for idx in range(10)
    ]
    app = ModalHost(entries)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["row-10"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_out_of_range_digit_is_noop() -> None:
    app = ModalHost([make_entry("a"), make_entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("5")
        await pilot.pause()
        assert isinstance(app.screen, StashedPromptsModal)
    assert app.result == "UNSET"


async def test_digit_restores_bundle_row_to_pop() -> None:
    app = ModalHost([make_entry("bundle", "one\n---\ntwo")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["bundle"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_digit_restores_pinned_bundle_row_to_keep() -> None:
    app = ModalHost([make_entry("bundle", "one\n---\ntwo", pinned=True)])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == ["bundle"]
    assert app.result.delete_ids == []


async def test_space_toggles_pin_and_posts_events() -> None:
    app = ModalHost([make_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)

        await pilot.press("space")
        await pilot.pause()
        assert modal._pinned == {"a"}
        assert modal._entries[0].pinned is True
        assert [(event.entry.id, event.pinned) for event in app.pin_events] == [
            ("a", True)
        ]

        await pilot.press("space")
        await pilot.pause()
        assert modal._pinned == set()
        assert modal._entries[0].pinned is False
        assert [(event.entry.id, event.pinned) for event in app.pin_events] == [
            ("a", True),
            ("a", False),
        ]


async def test_space_toggles_bundle_pin_and_posts_events() -> None:
    app = ModalHost([make_entry("bundle", "one\n---\ntwo")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)

        await pilot.press("space")
        await pilot.pause()
        assert modal._pinned == {"bundle"}
        assert modal._entries[0].pinned is True
        option = modal._build_options()[0]
        assert isinstance(option.prompt, Text)
        assert "📌" in option.prompt.plain

        await pilot.press("space")
        await pilot.pause()
        assert modal._pinned == set()
        assert modal._entries[0].pinned is False
        assert [(event.entry.id, event.pinned) for event in app.pin_events] == [
            ("bundle", True),
            ("bundle", False),
        ]
