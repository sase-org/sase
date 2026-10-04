"""Enter/submit action tests for the mini-macro name modal.

Split from ``test_mini_macro_name_modal``; shared helpers live in
``_mini_macro_name_modal_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

from textual.widgets import Static

from sase.ace.testing.wait import wait_for as wait_for_pilot
from sase.ace.tui.modals.mini_macro_name_modal import (
    MiniMacroNameModal,
    MiniMacroNameResult,
)
from sase.ace.tui.modals.mini_macro_target_catalog import MiniMacroTargetCatalog
from tests.ace.tui.modals._mini_macro_name_modal_helpers import (
    MiniMacroNameModalApp,
    make_definition,
    make_row,
    wait_for_analysis_idle,
    wait_for_verdict,
)


async def test_invalid_name_enter_is_inert(tmp_path: Path) -> None:
    row = make_row(tmp_path / "macros")
    results: list[MiniMacroNameResult | None] = []
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(definitions=(), destinations=(row,)),
                row,
                initial_name="#bad name",
            ),
            results.append,
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_verdict(pilot, modal, "Invalid name")
        await pilot.press("enter")
        await wait_for_analysis_idle(pilot, modal)
        assert (
            "Invalid name"
            in modal.query_one("#mini-macro-name-verdict", Static).render().plain
        )
        assert results == []


async def test_new_name_returns_create_target(tmp_path: Path) -> None:
    row = make_row(tmp_path / "macros")
    results: list[MiniMacroNameResult | None] = []
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(definitions=(), destinations=(row,)),
                row,
                initial_name="review",
            ),
            results.append,
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_verdict(pilot, modal, "Create #review")
        await pilot.press("enter")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    result = results[0]
    assert result is not None
    assert result.action == "create"
    assert result.destination.path == str(tmp_path / "macros" / "review.md")


async def test_exact_editable_match_returns_edit_action(tmp_path: Path) -> None:
    directory = tmp_path / "macros"
    row = make_row(directory, names=frozenset({"review"}))
    definition = make_definition("review", directory / "review.md")
    results: list[MiniMacroNameResult | None] = []
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(
                    definitions=(definition,),
                    destinations=(row,),
                ),
                row,
                initial_name="review",
            ),
            results.append,
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_analysis_idle(pilot, modal)
        await pilot.press("enter")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    result = results[0]
    assert result is not None
    assert result.action == "edit"
    assert result.definition == definition
    assert result.existing_definition == definition


async def test_read_only_match_returns_override_action(tmp_path: Path) -> None:
    readonly_dir = tmp_path / "readonly"
    writable_dir = tmp_path / "writable"
    readonly_row = make_row(
        readonly_dir,
        names=frozenset({"review"}),
        disabled_reason="read-only",
        precedence=0,
    )
    writable_row = make_row(writable_dir, precedence=1)
    definition = make_definition(
        "review",
        readonly_dir / "review.md",
        compatibility="read_only",
        location_path=str(readonly_dir),
    )
    results: list[MiniMacroNameResult | None] = []
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(
                    definitions=(definition,),
                    destinations=(readonly_row, writable_row),
                ),
                writable_row,
                initial_name="review",
            ),
            results.append,
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_analysis_idle(pilot, modal)
        assert (
            str(writable_dir)
            in modal.query_one("#mini-macro-name-destination", Static).render().plain
        )
        await pilot.press("enter")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    result = results[0]
    assert result is not None
    assert result.action == "override"
    assert result.existing_definition == definition
    assert result.save_warning is not None


async def test_incompatible_exact_match_refuses_open(tmp_path: Path) -> None:
    row = make_row(tmp_path / "macros")
    definition = make_definition(
        "review",
        tmp_path / "workflow.yml",
        compatibility="incompatible",
        workflow_kind="workflow",
        reason="workflow graphs must be edited elsewhere",
    )
    results: list[MiniMacroNameResult | None] = []
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(
                    definitions=(definition,),
                    destinations=(row,),
                ),
                row,
                initial_name="review",
            ),
            results.append,
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        await wait_for_verdict(pilot, modal, "Cannot open #review")
        await pilot.press("enter")
        await wait_for_analysis_idle(pilot, modal)

    assert results == []


async def test_locked_incompatible_destination_refuses_open(
    tmp_path: Path,
) -> None:
    high = tmp_path / "high"
    low = tmp_path / "low"
    high_row = make_row(high, names=frozenset({"review"}), precedence=0)
    low_row = make_row(low, names=frozenset({"review"}), precedence=10)
    editable = make_definition(
        "review",
        high / "review.md",
        location_path=str(high),
        precedence=0,
    )
    incompatible = make_definition(
        "review",
        low / "review.md",
        compatibility="incompatible",
        effective=False,
        location_path=str(low),
        precedence=10,
        reason="macro swarms cannot be opened as mini targets",
    )
    results: list[MiniMacroNameResult | None] = []
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(
                    definitions=(editable, incompatible),
                    destinations=(high_row, low_row),
                ),
                low_row,
                initial_name="review",
            ),
            results.append,
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        verdict = await wait_for_verdict(pilot, modal, "Cannot open #review at")
        assert "macro swarms" in verdict
        await pilot.press("enter")
        await wait_for_analysis_idle(pilot, modal)

    assert results == []
