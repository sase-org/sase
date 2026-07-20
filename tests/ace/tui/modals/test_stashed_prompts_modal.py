"""Tests for stashed-prompts row rendering and modal presentation."""

from __future__ import annotations

from rich.text import Text
from textual.containers import Container
from textual.widgets import OptionList, Static

from sase.ace.tui.modals._prompt_stash_preview import PromptStashPreviewPane
from sase.ace.tui.modals.prompt_stash_row import (
    append_shortcut,
    first_line_preview,
    stash_row_label,
)
from sase.ace.tui.modals.stashed_prompts_modal import StashedPromptsModal
from tests._project_display_case import ProjectDisplayCase
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import (
    ModalHost,
    make_entry,
)


def test_first_line_preview_uses_first_nonblank_line() -> None:
    assert first_line_preview("\n\n  hello  \nworld", 64) == "hello"


def test_first_line_preview_truncates_with_ellipsis() -> None:
    out = first_line_preview("x" * 100, 10)
    assert out == "xxxxxxxxx…"
    assert len(out) == 10


def test_project_chip_pads_and_placeholders() -> None:
    plain = stash_row_label(
        make_entry("a", "hello", project="proj"),
        marked_for_pop=False,
        marked_for_delete=False,
        pinned=False,
        age="2m ago",
    ).plain
    assert "proj".ljust(14) in plain
    assert (
        "—".ljust(14)
        in stash_row_label(
            make_entry("b", "hello", project=None),
            marked_for_pop=False,
            marked_for_delete=False,
            pinned=False,
            age="2m ago",
        ).plain
    )


def test_project_chip_uses_preloaded_label_without_changing_entry(
    project_display_case: ProjectDisplayCase,
) -> None:
    canonical = project_display_case.project_key
    entry = make_entry("display", project=canonical)
    label = stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_delete=False,
        pinned=False,
        age="2m ago",
        project_display_snapshot=project_display_case.snapshot,
    ).plain

    assert project_display_case.project_label in label
    assert canonical not in label
    assert entry.project == canonical
    assert (
        "a-very-long-p…"
        in stash_row_label(
            make_entry("c", "hello", project="a-very-long-project-name"),
            marked_for_pop=False,
            marked_for_delete=False,
            pinned=False,
            age="2m ago",
        ).plain
    )


def test_row_label_markers() -> None:
    entry = make_entry("a", "hello")
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
    entry = make_entry("bundle", "one\n---\ntwo")
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
        make_entry(
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


async def test_newest_first_ordering() -> None:
    entries = [
        make_entry("old", created_at="2026-06-16T09:00:00"),
        make_entry("new", created_at="2026-06-16T11:00:00"),
        make_entry("mid", created_at="2026-06-16T10:00:00"),
    ]
    app = ModalHost(entries)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        assert [entry.id for entry in modal._entries] == ["new", "mid", "old"]


async def test_preview_follows_debounced_highlight_and_caches_body() -> None:
    app = ModalHost(
        [
            make_entry("first", "# First", created_at="2026-06-16T12:00:00"),
            make_entry(
                "second",
                "%wait:planner\n\nSecond full prompt",
                created_at="2026-06-16T11:00:00",
            ),
        ]
    )
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        body = modal.query_one(".prompt-stash-preview-body", Static)
        assert body.render().plain == "# First"

        await pilot.press("j")
        await pilot.pause(0.2)
        assert body.render().plain == "%wait:planner\n\nSecond full prompt"
        assert set(modal._highlight_cache) == {"first", "second"}

        await pilot.press("space")
        await pilot.pause(0.2)
        assert body.render().plain == "%wait:planner\n\nSecond full prompt"
        assert modal.query_one(PromptStashPreviewPane).is_mounted


async def test_narrow_mode_preserves_legacy_row_budget() -> None:
    app = ModalHost([make_entry("a", "x" * 100)])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        container = modal.query_one("#stashed-prompts-container", Container)
        option_list = modal.query_one("#stashed-prompts-list", OptionList)
        assert container.has_class("-narrow")
        assert modal._last_preview_width_budget == 36
        option = option_list.get_option_at_index(0)
        assert isinstance(option.prompt, Text)
        assert option.prompt.plain.endswith("x" * 35 + "…")


async def test_title_and_hints_describe_unified_panel() -> None:
    app = ModalHost([make_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        assert modal._title_text() == "Stashed prompts (1)"
        hints = modal._hint_text()
        assert "1-9/0 restore" in hints
        assert "tab ✓" in hints
        assert "pin" in hints
        assert "📌" in hints
        assert "d delete row" in hints
        assert "D delete all" in hints
