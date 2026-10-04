"""Navigation, completion, and chrome tests for the mini-macro name modal.

Split from ``test_mini_macro_name_modal``; shared helpers live in
``_mini_macro_name_modal_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.widgets import Input, Label, OptionList, Static

from sase.ace.testing.wait import wait_for as wait_for_pilot
from sase.ace.tui.modals.mini_macro_name_modal import MiniMacroNameModal
from sase.ace.tui.modals.mini_macro_target_catalog import MiniMacroTargetCatalog
from sase.ace.tui.modals.save_location_choices import ChangeSaveLocationRequest
from tests.ace.tui.modals._mini_macro_name_modal_helpers import (
    MiniMacroNameModalApp,
    make_definition,
    make_row,
    wait_for_analysis_idle,
)


async def _open_modal(
    modal: MiniMacroNameModal,
    *,
    size: tuple[int, int] = (110, 30),
) -> tuple[MiniMacroNameModalApp, Any]:
    app = MiniMacroNameModalApp()
    pilot_cm = app.run_test(size=size)
    pilot = await pilot_cm.__aenter__()
    app.push_screen(modal)
    await wait_for_analysis_idle(pilot, modal)
    return app, (pilot_cm, pilot)


async def test_prefix_order_tab_completion_and_match_navigation_keep_input_focus(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row = make_row(tmp_path / "macros")
    definitions = (
        make_definition("review", tmp_path / "macros" / "review.md"),
        make_definition("review_long", tmp_path / "macros" / "review_long.md"),
        make_definition("revise", tmp_path / "macros" / "revise.md"),
    )

    def fail_read_text(self: Path, *args, **kwargs) -> str:  # type: ignore[no-untyped-def]
        raise AssertionError("modal navigation should not read files")

    app = MiniMacroNameModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(definitions=definitions, destinations=(row,)),
                row,
                initial_name="rev",
            )
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_analysis_idle(pilot, modal)
        monkeypatch.setattr(Path, "read_text", fail_read_text)
        matches = modal.query_one("#mini-macro-name-matches", OptionList)
        rendered = "\n".join(
            getattr(option.prompt, "plain", str(option.prompt))
            for option in matches.options
        )
        assert "#review" in rendered
        assert "#review_long" in rendered
        input_field = modal.query_one("#mini-macro-name-input", Input)
        input_field.cursor_position = len(input_field.value)
        await pilot.press("down")
        await pilot.pause()
        assert input_field.has_focus
        assert input_field.cursor_position == len("rev")
        await pilot.press("tab")
        await pilot.pause()
        assert input_field.value == "review_long"


async def test_ctrl_n_moves_matches_without_changing_destination(
    tmp_path: Path,
) -> None:
    row = make_row(tmp_path / "macros")
    definitions = (
        make_definition("review", tmp_path / "macros" / "review.md"),
        make_definition("review_long", tmp_path / "macros" / "review_long.md"),
    )
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(definitions=definitions, destinations=(row,)),
                row,
                initial_name="rev",
            )
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_analysis_idle(pilot, modal)
        before = modal.query_one("#mini-macro-name-destination", Static).render().plain
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press("ctrl+p")
        await pilot.pause()
        after = modal.query_one("#mini-macro-name-destination", Static).render().plain
        assert before == after
        assert str(tmp_path / "macros") in after
        assert modal.query_one("#mini-macro-name-input", Input).has_focus


async def test_stale_async_analysis_is_not_cached(tmp_path: Path) -> None:
    row = make_row(tmp_path / "macros")
    app, handles = await _open_modal(
        MiniMacroNameModal(
            MiniMacroTargetCatalog(definitions=(), destinations=(row,)),
            row,
            initial_name="review",
        )
    )
    pilot_cm, _pilot = handles
    try:
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        modal._analysis_cache.clear()
        modal.query_one("#mini-macro-name-input", Input).value = "fresh"
        await modal._load_analysis(("review", str(tmp_path / "macros")))
        assert ("review", str(tmp_path / "macros")) not in modal._analysis_cache
    finally:
        await pilot_cm.__aexit__(None, None, None)


async def test_shift_tab_returns_change_location_request(tmp_path: Path) -> None:
    row = make_row(tmp_path / "macros")
    results: list[Any] = []
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(definitions=(), destinations=(row,)),
                row,
                initial_name="rev",
            ),
            results.append,
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_analysis_idle(pilot, modal)
        await pilot.press("shift+tab")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    result = results[0]
    assert isinstance(result, ChangeSaveLocationRequest)
    assert result.text == "rev"


async def test_tab_completion_keeps_locked_destination(tmp_path: Path) -> None:
    row = make_row(tmp_path / "macros")
    definitions = (
        make_definition("review", tmp_path / "macros" / "review.md"),
        make_definition("review_long", tmp_path / "macros" / "review_long.md"),
    )
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(definitions=definitions, destinations=(row,)),
                row,
                initial_name="rev",
            )
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_analysis_idle(pilot, modal)
        await pilot.press("tab")
        await pilot.pause()
        assert modal.query_one("#mini-macro-name-input", Input).value.startswith(
            "review"
        )
        assert modal._destination.location.path == str(tmp_path / "macros")


async def test_name_step_shows_stepper_saving_to_and_hints(tmp_path: Path) -> None:
    row = make_row(tmp_path / "macros", namespace="sase")
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(definitions=(), destinations=(row,)),
                row,
                initial_name="",
            )
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_analysis_idle(pilot, modal)
        title = modal.query_one("#mini-macro-name-title", Label).render().plain
        assert "● Name" in title
        assert row.location.label in title
        saving_to = (
            modal.query_one("#mini-macro-name-destination", Static).render().plain
        )
        assert "⇧Tab change location" in saving_to
        assert "namespace sase/" in saving_to
        hints = modal.query_one("#mini-macro-name-hints", Static).render().plain
        assert hints == (
            "tab complete · ↑↓ matches · ⇧tab location · enter open · esc cancel"
        )
