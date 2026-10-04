"""Existing-definition finder tests for the location-first mini-macro flow.

Split from ``tests.ace.tui.actions.test_prompt_mini_macro_location_flow``; the
original module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
import threading
from unittest.mock import patch

from textual.widgets import Input

from sase.ace.testing import wait_for
from sase.ace.tui.modals.existing_definition_finder_modal import (
    ExistingDefinitionFinderModal,
)
from sase.ace.tui.modals.save_location_choices import EXISTING_CHOICE_ID
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_mini_macro_location_flow_helpers import (
    MiniFlowApp,
    location_mod,
    make_definition,
    make_rows,
    patch_flow,
    wait_finder,
    wait_mini_pane,
    wait_mini_tasks,
    wait_name_modal,
    wait_picker,
    wait_picker_loaded,
    write_macro,
)

__all__ = [
    "test_existing_editable_opens_pane_with_loaded_body",
    "test_existing_finder_back_remembers_query_and_cancel_refocuses",
    "test_existing_finder_origin_lost_warns",
    "test_existing_read_only_override_picker_to_pane",
    "test_existing_row_is_present_and_disabled_when_empty",
    "test_existing_shadowed_edit_carries_warning",
    "test_existing_typeahead_seeds_finder_query",
]


async def test_existing_row_is_present_and_disabled_when_empty(tmp_path: Path) -> None:
    rows = make_rows(tmp_path)
    patches = patch_flow(rows)
    app = MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.disabled_reason == "no macros yet"
            assert existing.is_default is False


async def test_existing_editable_opens_pane_with_loaded_body(tmp_path: Path) -> None:
    rows = make_rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    write_macro(path, "loaded from disk")
    definition = make_definition("rev", path, location_path=project_row.location.path)
    patches = patch_flow(rows, definitions=(definition,))
    app = MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.disabled_reason is None
            assert "1 macros" in existing.badges
            await pilot.press("e")
            await wait_finder(pilot, app)
            await pilot.press("enter")
            await wait_mini_tasks(app)
            await wait_mini_pane(pilot, bar)
            mini = bar._stack.mini_macro_item
            assert mini is not None
            assert mini.mini_macro_target is not None
            assert "loaded from disk" in bar.active_text()
            assert mini.mini_macro_target.name == "rev"
            assert mini.mini_macro_target.save_warning is None


async def test_existing_shadowed_edit_carries_warning(tmp_path: Path) -> None:
    rows = make_rows(tmp_path)
    project_row, home_row = rows
    winner = Path(project_row.location.path) / "rev.md"
    shadowed = Path(home_row.location.path) / "rev.md"
    write_macro(winner, "project body")
    write_macro(shadowed, "home body")
    definitions = (
        make_definition(
            "rev",
            winner,
            location_path=project_row.location.path,
            precedence=0,
        ),
        make_definition(
            "rev",
            shadowed,
            location_path=home_row.location.path,
            effective=False,
            precedence=10,
            shadowed_by=str(winner),
        ),
    )
    patches = patch_flow(rows, definitions=definitions)
    app = MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await wait_mini_tasks(app)
            await wait_mini_pane(pilot, bar)
            mini = bar._stack.mini_macro_item
            assert mini is not None
            assert mini.mini_macro_target is not None
            assert "home body" in bar.active_text()
            assert mini.mini_macro_target.save_warning is not None
            assert "shadowed" in mini.mini_macro_target.save_warning


async def test_existing_read_only_override_picker_to_pane(tmp_path: Path) -> None:
    rows = make_rows(tmp_path)
    project_row, home_row = rows
    builtin = tmp_path / "default_macros" / "rev.md"
    write_macro(builtin, "built-in body")
    definition = make_definition(
        "rev",
        builtin,
        location_path=str(builtin.parent),
        compatibility="read_only",
        origin_label="built-in",
    )
    patches = patch_flow(rows, definitions=(definition,))
    app = MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await wait_finder(pilot, app)
            await pilot.press("enter")
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            assert picker._title.startswith("Override #rev")
            assert all(
                choice.choice_id != EXISTING_CHOICE_ID for choice in picker._choices
            )
            project_choice = next(
                choice
                for choice in picker._choices
                if choice.choice_id == project_row.location.path
            )
            assert project_choice.disabled_reason is not None
            assert "can't override" in project_choice.disabled_reason
            await pilot.press("h")
            modal = await wait_name_modal(pilot, app)
            await pilot.pause()
            assert modal.query_one("#mini-macro-name-input", Input).value == "rev"
            await pilot.press("enter")
            await wait_mini_tasks(app)
            await wait_mini_pane(pilot, bar)
            assert "built-in body" in bar.active_text()
            mini = bar._stack.mini_macro_item
            assert mini is not None
            assert mini.mini_macro_target is not None
            assert mini.mini_macro_target.location_path == home_row.location.path


async def test_existing_finder_back_remembers_query_and_cancel_refocuses(
    tmp_path: Path,
) -> None:
    rows = make_rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    write_macro(path, "body")
    definition = make_definition("rev", path, location_path=project_row.location.path)
    patches = patch_flow(rows, definitions=(definition,))
    app = MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            origin = bar.active_text_area()
            await pilot.press("g", "x")
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            finder = await wait_finder(pilot, app)
            await pilot.press("r", "e")
            await pilot.pause()
            await pilot.press("shift+tab")
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            assert picker.highlighted_id == EXISTING_CHOICE_ID
            await pilot.press("e")
            finder = await wait_finder(pilot, app)
            assert finder.query_one("#existing-finder-query", Input).value == "re"
            await pilot.press("escape")
            await wait_for(
                pilot,
                lambda: not isinstance(app.screen, ExistingDefinitionFinderModal),
            )
            await pilot.pause()
            assert bar.active_text_area() is origin
            assert origin.has_focus


async def test_existing_typeahead_seeds_finder_query(tmp_path: Path) -> None:
    rows = make_rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    write_macro(path, "body")
    definition = make_definition("rev", path, location_path=project_row.location.path)
    entered = threading.Event()
    release = threading.Event()

    def _slow_rows(project: str | None) -> list:
        entered.set()
        assert release.wait(timeout=10)
        return list(rows)

    last_used_patch, catalog_patch = patch_flow(rows, definitions=(definition,))[1:]
    app = MiniFlowApp("agent prompt")
    with (
        patch.object(location_mod, "_load_unified_save_rows", side_effect=_slow_rows),
        last_used_patch,
        catalog_patch,
    ):
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "x")
            await wait_picker(pilot, app)
            await wait_for(pilot, entered.is_set)
            await pilot.press("e", "r", "e", "v")
            release.set()
            finder = await wait_finder(pilot, app)

            def _query_value() -> str | None:
                try:
                    return finder.query_one("#existing-finder-query", Input).value
                except Exception:
                    return None

            await wait_for(pilot, lambda: _query_value() == "rev")


async def test_existing_finder_origin_lost_warns(tmp_path: Path) -> None:
    rows = make_rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    write_macro(path, "body")
    definition = make_definition("rev", path, location_path=project_row.location.path)
    patches = patch_flow(rows, definitions=(definition,))
    app = MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await wait_finder(pilot, app)
            bar.mini_macro_target_origin_available = (  # type: ignore[method-assign]
                lambda pane_id: False
            )
            await pilot.press("enter")
            await wait_for(
                pilot,
                lambda: not isinstance(app.screen, ExistingDefinitionFinderModal),
            )
            assert (
                "Prompt pane is no longer available - mini-macro discarded",
                "warning",
            ) in app.notifications
            assert bar._stack.mini_macro_item is None
