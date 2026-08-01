"""Tests for the spellcheck correction panel's footer and key bindings."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.modals.spellcheck_panel_modal import (
    SpellcheckChoice,
    SpellcheckPanelModal,
)

# Container `width: 56`, minus a 1-cell double border each side, minus `padding: 1 2`.
_CONTENT_WIDTH = 50


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def test_build_footer_with_suggestions_is_two_lines_and_fits_content_width() -> None:
    modal = SpellcheckPanelModal("accomodate", ("accommodate", "accommodated"))

    lines = modal._build_footer().split("\n")

    assert lines == [
        "1-9 apply | j/k move | Enter apply",
        "a accept | d add to aspell | Esc cancel",
    ]
    for line in lines:
        assert len(line) <= _CONTENT_WIDTH


def test_build_footer_without_suggestions_is_one_line_and_omits_move_hint() -> None:
    modal = SpellcheckPanelModal("zzzzz", ())

    footer = modal._build_footer()

    assert footer == "a accept | d add to aspell | Esc cancel"
    assert "j/k move" not in footer
    assert len(footer) <= _CONTENT_WIDTH


def test_every_named_footer_key_has_a_live_binding() -> None:
    with_suggestions = SpellcheckPanelModal("accomodate", ("accommodate",))
    without_suggestions = SpellcheckPanelModal("zzzzz", ())

    for modal in (with_suggestions, without_suggestions):
        bound_keys = {key for key, *_rest in modal.BINDINGS}
        # Named keys advertised in both footer variants: j, k, Enter, a, d, Esc.
        assert {"j", "k", "enter", "a", "d", "escape"} <= bound_keys


async def test_dictionary_key_dismisses_with_dictionary_action() -> None:
    result: SpellcheckChoice | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(choice: SpellcheckChoice | None) -> None:
            nonlocal result
            result = choice

        pilot.app.push_screen(
            SpellcheckPanelModal("accomodate", ("accommodate",)), on_dismiss
        )
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

    assert result == SpellcheckChoice(action="dictionary")


async def test_dictionary_key_works_on_no_suggestions_panel() -> None:
    result: SpellcheckChoice | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(choice: SpellcheckChoice | None) -> None:
            nonlocal result
            result = choice

        pilot.app.push_screen(SpellcheckPanelModal("zzzzz", ()), on_dismiss)
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

    assert result == SpellcheckChoice(action="dictionary")
