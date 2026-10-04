"""Open-pane replace tests for the location-first mini-macro flow.

Split from ``tests.ace.tui.actions.test_prompt_mini_macro_location_flow``; the
original module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

from sase.ace.testing import wait_for
from sase.ace.tui.modals import ConfirmActionModal
from sase.ace.tui.modals.save_location_choices import EXISTING_CHOICE_ID
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_mini_macro_location_flow_helpers import (
    MiniFlowApp,
    make_definition,
    make_rows,
    patch_flow,
    wait_finder,
    wait_mini_pane,
    wait_mini_tasks,
    wait_picker,
    wait_picker_loaded,
    write_macro,
)

__all__ = [
    "test_existing_dirty_open_pane_confirms_before_replace",
    "test_existing_replaces_clean_open_pane",
    "test_existing_same_target_focuses_and_notifies",
]


async def test_existing_same_target_focuses_and_notifies(tmp_path: Path) -> None:
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
            await pilot.press("e")
            await wait_finder(pilot, app)
            await pilot.press("enter")
            await wait_mini_tasks(app)
            await wait_mini_pane(pilot, bar)
            bar.active_text_area().text = "user draft"
            bar._sync_state_from_widgets()

            bar.request_mini_macro_target_pane()
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.label.startswith("Switch to existing")
            await pilot.press("e")
            await wait_finder(pilot, app)
            await pilot.press("enter")
            await wait_mini_tasks(app)
            await wait_for(
                pilot,
                lambda: any(
                    message == "Already editing #rev"
                    for message, _sev in app.notifications
                ),
            )
            assert bar.active_text() == "user draft"


async def test_existing_replaces_clean_open_pane(tmp_path: Path) -> None:
    rows = make_rows(tmp_path)
    project_row, home_row = rows
    first = Path(project_row.location.path) / "rev.md"
    second = Path(home_row.location.path) / "todo.md"
    write_macro(first, "first body")
    write_macro(second, "second body")
    definitions = (
        make_definition(
            "rev", first, location_path=project_row.location.path, precedence=0
        ),
        make_definition(
            "todo", second, location_path=home_row.location.path, precedence=10
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
            await pilot.press("enter")
            await wait_mini_tasks(app)
            await wait_mini_pane(pilot, bar)
            assert "first body" in bar.active_text()
            restore = bar._mini_macro_focus_restore

            bar.request_mini_macro_target_pane()
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await wait_mini_tasks(app)
            await wait_for(pilot, lambda: "second body" in bar.active_text())
            mini = bar._stack.mini_macro_item
            assert mini is not None
            assert mini.mini_macro_target is not None
            assert mini.mini_macro_target.name == "todo"
            assert bar._mini_macro_focus_restore is restore
            assert bar.active_text_area()._vim_mode == "insert"


async def test_existing_dirty_open_pane_confirms_before_replace(
    tmp_path: Path,
) -> None:
    rows = make_rows(tmp_path)
    project_row, home_row = rows
    first = Path(project_row.location.path) / "rev.md"
    second = Path(home_row.location.path) / "todo.md"
    write_macro(first, "first body")
    write_macro(second, "second body")
    definitions = (
        make_definition(
            "rev", first, location_path=project_row.location.path, precedence=0
        ),
        make_definition(
            "todo", second, location_path=home_row.location.path, precedence=10
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
            await pilot.press("enter")
            await wait_mini_tasks(app)
            await wait_mini_pane(pilot, bar)
            bar.active_text_area().text = "dirty draft"
            bar._sync_state_from_widgets()

            bar.request_mini_macro_target_pane()
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
            await pilot.press("n")
            await pilot.pause()
            assert bar.active_text() == "dirty draft"

            bar.request_mini_macro_target_pane()
            picker = await wait_picker(pilot, app)
            await wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
            await pilot.press("y")
            await wait_mini_tasks(app)
            await wait_for(pilot, lambda: "second body" in bar.active_text())
