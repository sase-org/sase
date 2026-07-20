"""Tests for multi-row selection and deletion in the stashed-prompts modal."""

from rich.text import Text

from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
)
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import (
    ModalHost,
    make_entry,
)


async def test_tab_toggles_then_enter_restores_pop_set() -> None:
    app = ModalHost(
        [
            make_entry("a", created_at="2026-06-16T12:00:00"),
            make_entry("b", created_at="2026-06-16T11:00:00"),
            make_entry("c", created_at="2026-06-16T10:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("tab")  # pop "a"
        await pilot.press("j")
        await pilot.press("j")
        await pilot.press("tab")  # pop "c"
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert set(app.result.pop_ids) == {"a", "c"}
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_marked_pinned_row_confirms_to_keep() -> None:
    app = ModalHost([make_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        await pilot.press("space")
        await pilot.press("tab")
        await pilot.pause()
        assert modal._pinned == {"a"}
        assert modal._pop == {"a"}
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == ["a"]
    assert app.result.delete_ids == []


async def test_toggle_all_then_enter_restores_everything() -> None:
    app = ModalHost([make_entry("a"), make_entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("a")  # toggle all
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert set(app.result.pop_ids) == {"a", "b"}
    assert app.result.keep_ids == []


async def test_tab_marks_bundle_row_for_restore_and_pop() -> None:
    app = ModalHost([make_entry("bundle", "one\n---\ntwo")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["bundle"]
    assert app.result.keep_ids == []


async def test_toggle_all_selects_bundle_rows() -> None:
    app = ModalHost(
        [
            make_entry("bundle", "one\n---\ntwo", created_at="2026-06-16T12:00:00"),
            make_entry("a", "alpha", created_at="2026-06-16T11:00:00"),
            make_entry("b", "beta", created_at="2026-06-16T10:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert set(app.result.pop_ids) == {"bundle", "a", "b"}
    assert app.result.keep_ids == []


async def test_toggle_all_partitions_pinned_and_unpinned_rows() -> None:
    app = ModalHost(
        [
            make_entry("pinned", pinned=True, created_at="2026-06-16T12:00:00"),
            make_entry("unpinned", created_at="2026-06-16T11:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["unpinned"]
    assert app.result.keep_ids == ["pinned"]
    assert app.result.delete_ids == []


async def test_delete_mark_returns_delete_ids_not_restore() -> None:
    app = ModalHost([make_entry("a"), make_entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("d")  # mark "a" for deletion
        await pilot.press("j")  # highlight "b"
        await pilot.press("enter")  # confirm only the marked deletion
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert app.result.delete_ids == ["a"]


async def test_pin_is_orthogonal_to_delete_selection() -> None:
    app = ModalHost([make_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        await pilot.press("space")  # pin "a"
        await pilot.press("d")  # deletion is independent of pin state
        await pilot.pause()
        assert modal._pinned == {"a"}
        assert modal._deleted == {"a"}
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert app.result.delete_ids == ["a"]


async def test_delete_wins_over_prior_pop_selection() -> None:
    app = ModalHost([make_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("tab")  # pop "a"
        await pilot.press("d")  # then mark it for deletion (clears pop)
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert app.result.delete_ids == ["a"]


async def test_delete_all_replaces_restore_marks_and_preserves_pins() -> None:
    app = ModalHost(
        [
            make_entry("restore", created_at="2026-06-16T12:00:00"),
            make_entry(
                "pinned",
                pinned=True,
                created_at="2026-06-16T11:00:00",
            ),
            make_entry(
                "bundle",
                "one\n---\ntwo",
                created_at="2026-06-16T10:00:00",
            ),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)

        await pilot.press("tab")  # mark "restore" for restore-and-pop
        await pilot.press("D")
        await pilot.pause()

        assert modal._pop == set()
        assert modal._deleted == {"restore", "pinned", "bundle"}
        assert modal._pinned == {"pinned"}
        assert all(
            isinstance(option.prompt, Text) and option.prompt.plain[4:].startswith("✗")
            for option in modal._build_options()
        )

        await pilot.press("enter")
        await pilot.pause()

    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert set(app.result.delete_ids) == {"restore", "pinned", "bundle"}


async def test_single_delete_can_unmark_a_delete_all_row() -> None:
    app = ModalHost([make_entry("a"), make_entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)

        await pilot.press("D")
        await pilot.press("d")
        await pilot.pause()

        assert modal._deleted == {"b"}
        assert modal._pop == set()


async def test_delete_mark_can_delete_bundle_row() -> None:
    app = ModalHost([make_entry("bundle", "one\n---\ntwo")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert app.result.delete_ids == ["bundle"]


async def test_escape_cancels_with_none() -> None:
    app = ModalHost([make_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None
