"""Behavior of the shared save-location picker modal."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.testing.wait import wait_for as wait_for_pilot
from sase.ace.tui.modals.save_location_choices import (
    EXISTING_CHOICE_ID,
    SaveLocationChoice,
    SaveLocationPick,
)
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("")


def _choice(
    choice_id: str,
    hotkey: str | None,
    section: str = "Home",
    *,
    kind: str = "config",
    label: str = "User config",
    badges: tuple[str, ...] = (),
    disabled_reason: str | None = None,
    preview: str = "preview",
    is_default: bool = False,
    collapsed_group: bool = False,
    display_path: str | None = None,
) -> SaveLocationChoice:
    return SaveLocationChoice(
        choice_id=choice_id,
        hotkey=hotkey,
        section=section,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        display_path=choice_id if display_path is None else display_path,
        badges=badges,
        disabled_reason=disabled_reason,
        preview=preview,
        is_default=is_default,
        collapsed_group=collapsed_group,
    )


def _existing_choice(
    *,
    count: int = 12,
    disabled: bool = False,
) -> SaveLocationChoice:
    return _choice(
        EXISTING_CHOICE_ID,
        "e",
        "Existing",
        kind="existing",
        label="Edit existing macro…",
        badges=(f"{count} macros",),
        disabled_reason="no macros yet" if disabled else None,
        preview=(
            f"→ fuzzy-find {count} macros across 3 files "
            "· edit in place or override read-only ones"
        ),
        display_path="",
    )


def _choices_with_existing() -> tuple[SaveLocationChoice, ...]:
    return (_existing_choice(), *_standard_choices())


def _standard_choices() -> tuple[SaveLocationChoice, ...]:
    return (
        _choice("/proj", "p", "Project · sase", label="Project config"),
        _choice(
            "/user",
            "h",
            label="User config",
            badges=("★ default",),
            preview="user preview",
            is_default=True,
        ),
        _choice("/work", "1", label="sase_work.yml"),
    )


def _preview_text(modal: SaveLocationPickerModal) -> str:
    return modal.query_one("#save-location-picker-preview", Static).render().plain


def _hints_text(modal: SaveLocationPickerModal) -> str:
    return modal.query_one("#save-location-picker-hints", Static).render().plain


async def test_hotkey_dismisses_with_right_id() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            SaveLocationPickerModal(
                "snippet", "New snippet · where should it live?", _standard_choices()
            ),
            results.append,
        )
        await pilot.pause()
        await pilot.press("h")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick("/user", "")]


async def test_enter_picks_highlighted_default() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            SaveLocationPickerModal(
                "snippet", "New snippet · where should it live?", _standard_choices()
            ),
            results.append,
        )
        await pilot.pause()
        await pilot.press("enter")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick("/user", "")]


async def test_movement_skips_headers_and_disabled_rows() -> None:
    choices = (
        _choice("/proj", "p", "Project · sase", label="Project config"),
        _choice(
            "/locked",
            "P",
            "Project · sase",
            label="Project secrets",
            disabled_reason="read-only",
        ),
        _choice("/user", "h", label="User config"),
    )
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", choices)
        app.push_screen(modal)
        await pilot.pause()
        assert modal.highlighted_id == "/proj"
        await pilot.press("j")
        await pilot.pause()
        assert modal.highlighted_id == "/user"
        await pilot.press("j")
        await pilot.pause()
        assert modal.highlighted_id == "/proj"
        await pilot.press("k")
        await pilot.pause()
        assert modal.highlighted_id == "/user"
        for key in ("up", "down", "ctrl+p", "ctrl+n"):
            await pilot.press(key)
            await pilot.pause()
            assert modal.highlighted_id in ("/proj", "/user")


async def test_disabled_hotkey_shows_reason_and_stays_open() -> None:
    results: list[SaveLocationPick | None] = []
    choices = (
        _choice("/proj", "p", "Project · sase", label="Project config"),
        _choice(
            "/locked",
            "P",
            "Project · sase",
            label="Project secrets",
            disabled_reason="migrate legacy project config first",
        ),
        _choice("/user", "h", label="User config", is_default=True),
    )
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", choices)
        app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("P")
        await pilot.pause()
        assert results == []
        assert "migrate legacy project config first" in _preview_text(modal)
        assert modal.highlighted_id == "/user"


async def test_escape_and_q_dismiss_none() -> None:
    for key in ("escape", "q"):
        await _press_key_dismisses_none(key)


async def _press_key_dismisses_none(key: str) -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            SaveLocationPickerModal("snippet", "Pick", _standard_choices()),
            results.append,
        )
        await pilot.pause()
        await pilot.press(key)
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)
    assert results == [None]


async def test_plus_toggles_collapsed_section() -> None:
    choices = (
        _choice("/user", "h", label="User config", is_default=True),
        _choice(
            "/plugin",
            None,
            "Plugins & built-in",
            label="Plugin macros",
            collapsed_group=True,
        ),
    )
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("macro", "Pick", choices)
        app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one("#save-location-picker-list", OptionList)
        assert option_list.option_count == 3
        await pilot.press("plus")
        await pilot.pause()
        assert option_list.option_count == 4
        await pilot.press("plus")
        await pilot.pause()
        assert option_list.option_count == 3


async def test_collapsed_starts_expanded_for_default_inside() -> None:
    choices = (
        _choice("/user", "h", label="User config"),
        _choice(
            "/plugin",
            None,
            "Plugins & built-in",
            label="Plugin macros",
            badges=("★ default",),
            is_default=True,
            collapsed_group=True,
        ),
    )
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("macro", "Pick", choices)
        app.push_screen(modal)
        await pilot.pause()
        assert modal.highlighted_id == "/plugin"


async def test_loading_buffers_hotkey_and_typeahead() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", None)
        app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("h", "t", "o", "d", "o")
        await pilot.pause()
        assert modal.pending_pick == "h"
        assert modal.typeahead == "todo"
        assert results == []
        modal.set_choices(_standard_choices())
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick("/user", "todo")]


async def test_loading_buffers_enter_for_default() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", None)
        app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert modal.pending_pick == "enter"
        modal.set_choices(_standard_choices())
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick("/user", "")]


async def test_loading_backspace_edits_typeahead() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", None)
        app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("h", "t", "o", "backspace", "d", "o")
        await pilot.pause()
        assert modal.typeahead == "tdo"
        modal.set_choices(_standard_choices())
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick("/user", "tdo")]


async def test_loading_unknown_key_stays_open_with_message() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", None)
        app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()
        modal.set_choices(_standard_choices())
        await pilot.pause()
        assert results == []
        assert "no destination on z" in _preview_text(modal)
        assert modal.typeahead == ""


async def test_loading_escape_cancels() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            SaveLocationPickerModal("snippet", "Pick", None), results.append
        )
        await pilot.pause()
        await pilot.press("escape")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [None]


async def test_set_load_error_and_escape() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", None)
        app.push_screen(modal, results.append)
        await pilot.pause()
        modal.set_load_error("disk is gone")
        await pilot.pause()
        assert "disk is gone" in _preview_text(modal) or modal.query(
            "#save-location-picker-list"
        )
        await pilot.press("escape")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [None]


async def test_empty_state_enter_is_inert() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", ())
        app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert results == []
        assert "esc cancel" in _hints_text(modal)
        await pilot.press("escape")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [None]


async def test_click_selects_choice() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", _standard_choices())
        app.push_screen(modal, results.append)
        await pilot.pause()
        option_list = modal.query_one("#save-location-picker-list", OptionList)
        option = next(
            option for option in option_list.options if option.id == "choice__/proj"
        )
        option_list.post_message(OptionList.OptionSelected(option_list, option, 1))
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick("/proj", "")]


async def test_hints_line_reflects_hotkeys_and_default() -> None:
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("snippet", "Pick", _standard_choices())
        app.push_screen(modal)
        await pilot.pause()
        hints = _hints_text(modal)
        assert "p h 1 pick" in hints
        assert "↵ default" in hints
        assert "j/k move" in hints
        assert "esc cancel" in hints


async def test_existing_hotkey_dismisses_with_existing_id() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            SaveLocationPickerModal("macro", "Pick", _choices_with_existing()),
            results.append,
        )
        await pilot.pause()
        await pilot.press("e")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick(EXISTING_CHOICE_ID, "")]


async def test_existing_hints_and_enter_still_picks_default() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("macro", "Pick", _choices_with_existing())
        app.push_screen(modal, results.append)
        await pilot.pause()
        hints = _hints_text(modal)
        assert hints.startswith("e existing")
        assert "p h 1 pick" in hints
        assert "e p h 1 pick" not in hints
        assert "e existing" in hints
        assert modal.highlighted_id == "/user"
        option_list = modal.query_one("#save-location-picker-list", OptionList)
        prompt = next(
            option.prompt
            for option in option_list.options
            if option.id == f"choice__{EXISTING_CHOICE_ID}"
        )
        plain = prompt.plain if hasattr(prompt, "plain") else str(prompt)
        assert "✎" in plain
        assert "Edit existing macro…" in plain
        await pilot.press("enter")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick("/user", "")]


async def test_loading_buffers_existing_hotkey_and_typeahead() -> None:
    results: list[SaveLocationPick | None] = []
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("macro", "Pick", None)
        app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("e", "r", "e", "v")
        await pilot.pause()
        assert modal.pending_pick == "e"
        assert modal.typeahead == "rev"
        modal.set_choices(_choices_with_existing())
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick(EXISTING_CHOICE_ID, "rev")]


async def test_existing_row_is_not_writable_destination_fallback() -> None:
    results: list[SaveLocationPick | None] = []
    choices = (
        _existing_choice(),
        _choice(
            "/locked",
            "p",
            "Project · sase",
            label="Project config",
            disabled_reason="read-only",
        ),
    )
    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        modal = SaveLocationPickerModal("macro", "Pick", choices)
        app.push_screen(modal, results.append)
        await pilot.pause()
        option_list = modal.query_one("#save-location-picker-list", OptionList)
        plains = [
            option.prompt.plain
            if hasattr(option.prompt, "plain")
            else str(option.prompt)
            for option in option_list.options
        ]
        assert any("No writable destinations found" in text for text in plains)
        assert modal.highlighted_id != EXISTING_CHOICE_ID
        await pilot.press("enter")
        await pilot.pause()
        assert results == []
        await pilot.press("e")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    assert results == [SaveLocationPick(EXISTING_CHOICE_ID, "")]
