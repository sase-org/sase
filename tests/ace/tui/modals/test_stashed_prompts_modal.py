"""Tests for the unified prompt-stash panel.

Covers the pure row helpers (preview truncation, project chip, marker styling,
and shortcut gutter) and the modal's selection model: digit keys restore a
numbered row, ``space`` toggles a persistent pin intent, ``tab`` marks
rows for restore, ``a`` toggles all rows, ``d`` marks a row for deletion,
``enter`` confirms (the marked set, or the highlighted row when nothing is
marked), and ``esc`` cancels. Pinned restores stay stashed; unpinned restores
are popped.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.prompt_stash_row import (
    append_shortcut,
    first_line_preview,
    stash_row_label,
)
from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
)
from sase.core.prompt_stash_wire import PromptStashEntryWire


def _entry(
    entry_id: str,
    text: str = "draft",
    *,
    created_at: str = "2026-06-16T10:00:00",
    project: str | None = "proj",
    pane_index: int = 0,
    pinned: bool = False,
) -> PromptStashEntryWire:
    return PromptStashEntryWire(
        id=entry_id,
        created_at=created_at,
        text=text,
        project=project,
        pane_index=pane_index,
        pinned=pinned,
    )


# --- pure helpers ----------------------------------------------------------


def test_first_line_preview_uses_first_nonblank_line() -> None:
    assert first_line_preview("\n\n  hello  \nworld", 64) == "hello"


def test_first_line_preview_truncates_with_ellipsis() -> None:
    out = first_line_preview("x" * 100, 10)
    assert out == "xxxxxxxxx…"
    assert len(out) == 10


def test_project_chip_pads_and_placeholders() -> None:
    plain = stash_row_label(
        _entry("a", "hello", project="proj"),
        marked_for_pop=False,
        marked_for_delete=False,
        pinned=False,
        age="2m ago",
    ).plain
    assert "proj".ljust(14) in plain
    assert (
        "—".ljust(14)
        in stash_row_label(
            _entry("b", "hello", project=None),
            marked_for_pop=False,
            marked_for_delete=False,
            pinned=False,
            age="2m ago",
        ).plain
    )
    assert (
        "a-very-long-p…"
        in stash_row_label(
            _entry("c", "hello", project="a-very-long-project-name"),
            marked_for_pop=False,
            marked_for_delete=False,
            pinned=False,
            age="2m ago",
        ).plain
    )


def test_row_label_markers() -> None:
    entry = _entry("a", "hello")
    plain_pop = stash_row_label(
        entry,
        marked_for_pop=True,
        marked_for_delete=False,
        pinned=False,
        age="2m ago",
    ).plain
    plain_pinned = stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_delete=False,
        pinned=True,
        age="2m ago",
    ).plain
    plain_deleted = stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_delete=True,
        pinned=False,
        age="2m ago",
    ).plain
    plain_plain = stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_delete=False,
        pinned=False,
        age="2m ago",
    ).plain
    assert plain_pop.startswith("✓")
    assert plain_pinned.startswith("  📌")
    assert plain_deleted.startswith("✗")
    assert plain_plain.startswith("    ")
    assert "2m ago" in plain_plain and "proj" in plain_plain and "hello" in plain_plain


def test_row_label_shows_bundle_marker() -> None:
    entry = _entry("bundle", "one\n---\ntwo")
    plain = stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_delete=False,
        pinned=False,
        age="2m ago",
        prompt_count=2,
    ).plain
    assert "2 prompts" in plain


def test_append_shortcut_builds_fixed_width_keycap_or_blank_gutter() -> None:
    with_key = Text()
    append_shortcut(with_key, "3")
    blank = Text()
    append_shortcut(blank, None)

    assert with_key.plain == " 3  "
    assert blank.plain == "    "
    assert with_key.cell_len == blank.cell_len == 4


def test_build_options_assigns_digit_gutters_to_first_ten_rows() -> None:
    entries = [
        _entry(
            f"row-{idx + 1}",
            created_at=f"2026-06-16T{23 - idx:02d}:00:00",
        )
        for idx in range(11)
    ]
    modal = StashedPromptsModal(entries)

    gutters: list[str] = []
    for option in modal._build_options():
        assert isinstance(option.prompt, Text)
        gutters.append(option.prompt.plain[:4])

    assert gutters[:10] == [
        " 1  ",
        " 2  ",
        " 3  ",
        " 4  ",
        " 5  ",
        " 6  ",
        " 7  ",
        " 8  ",
        " 9  ",
        " 0  ",
    ]
    assert gutters[10] == "    "


# --- modal interaction (pilot) ---------------------------------------------


class _ModalHost(App[None]):
    """Pushes the stash panel and captures its dismiss result."""

    def __init__(self, entries: list[PromptStashEntryWire]) -> None:
        super().__init__()
        self._entries = entries
        self.result: object = "UNSET"
        self.pin_events: list[StashedPromptsModal.PinToggled] = []

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            StashedPromptsModal(self._entries),
            lambda res: setattr(self, "result", res),
        )

    def on_stashed_prompts_modal_pin_toggled(
        self, event: StashedPromptsModal.PinToggled
    ) -> None:
        self.pin_events.append(event)


async def test_newest_first_ordering() -> None:
    entries = [
        _entry("old", created_at="2026-06-16T09:00:00"),
        _entry("new", created_at="2026-06-16T11:00:00"),
        _entry("mid", created_at="2026-06-16T10:00:00"),
    ]
    app = _ModalHost(entries)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        assert [e.id for e in modal._entries] == ["new", "mid", "old"]


async def test_enter_with_no_toggle_restores_highlighted() -> None:
    app = _ModalHost([_entry("a"), _entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("enter")  # confirm highlighted (first row)
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["a"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_enter_with_no_toggle_keeps_pinned_highlighted_bundle() -> None:
    app = _ModalHost([_entry("bundle", "one\n---\ntwo", pinned=True)])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == ["bundle"]
    assert app.result.delete_ids == []


async def test_enter_with_no_toggle_keeps_pinned_highlighted_row() -> None:
    app = _ModalHost([_entry("a")])
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
    app = _ModalHost(
        [
            _entry("first", created_at="2026-06-16T12:00:00"),
            _entry("target", created_at="2026-06-16T11:00:00"),
            _entry("third", created_at="2026-06-16T10:00:00"),
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
    app = _ModalHost(
        [
            _entry("first", created_at="2026-06-16T12:00:00"),
            _entry("target", created_at="2026-06-16T11:00:00"),
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
        _entry(
            f"row-{idx + 1}",
            created_at=f"2026-06-16T{23 - idx:02d}:00:00",
        )
        for idx in range(10)
    ]
    app = _ModalHost(entries)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["row-10"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_out_of_range_digit_is_noop() -> None:
    app = _ModalHost([_entry("a"), _entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("5")
        await pilot.pause()
        assert isinstance(app.screen, StashedPromptsModal)
    assert app.result == "UNSET"


async def test_digit_restores_bundle_row_to_pop() -> None:
    app = _ModalHost([_entry("bundle", "one\n---\ntwo")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["bundle"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_digit_restores_pinned_bundle_row_to_keep() -> None:
    app = _ModalHost([_entry("bundle", "one\n---\ntwo", pinned=True)])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == ["bundle"]
    assert app.result.delete_ids == []


async def test_space_toggles_pin_and_posts_events() -> None:
    app = _ModalHost([_entry("a")])
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
    app = _ModalHost([_entry("bundle", "one\n---\ntwo")])
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


async def test_tab_toggles_then_enter_restores_pop_set() -> None:
    app = _ModalHost(
        [
            _entry("a", created_at="2026-06-16T12:00:00"),
            _entry("b", created_at="2026-06-16T11:00:00"),
            _entry("c", created_at="2026-06-16T10:00:00"),
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
    app = _ModalHost([_entry("a")])
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
    app = _ModalHost([_entry("a"), _entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("a")  # toggle all
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert set(app.result.pop_ids) == {"a", "b"}
    assert app.result.keep_ids == []


async def test_tab_marks_bundle_row_for_restore_and_pop() -> None:
    app = _ModalHost([_entry("bundle", "one\n---\ntwo")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["bundle"]
    assert app.result.keep_ids == []


async def test_toggle_all_selects_bundle_rows() -> None:
    app = _ModalHost(
        [
            _entry("bundle", "one\n---\ntwo", created_at="2026-06-16T12:00:00"),
            _entry("a", "alpha", created_at="2026-06-16T11:00:00"),
            _entry("b", "beta", created_at="2026-06-16T10:00:00"),
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
    app = _ModalHost(
        [
            _entry("pinned", pinned=True, created_at="2026-06-16T12:00:00"),
            _entry("unpinned", created_at="2026-06-16T11:00:00"),
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
    app = _ModalHost([_entry("a"), _entry("b")])
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
    app = _ModalHost([_entry("a")])
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
    app = _ModalHost([_entry("a")])
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


async def test_delete_mark_can_delete_bundle_row() -> None:
    app = _ModalHost([_entry("bundle", "one\n---\ntwo")])
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
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


async def test_title_and_hints_describe_unified_panel() -> None:
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        assert modal._title_text() == "Stashed prompts (1)"
        hints = modal._hint_text()
        assert "1-9" in hints
        assert "restore row" in hints
        assert "tab ✓ restore" in hints
        assert "pin" in hints
        assert "📌" in hints
        assert "delete" in hints
