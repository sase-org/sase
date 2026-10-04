"""Location-first mini-macro flow through the save-location picker."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from unittest.mock import patch

import pytest
from textual.widgets import Input

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow import (
    _prompt_bar_mini_macro_location as location_mod,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_mini_macro_pane import (
    PromptBarMiniMacroPaneMixin,
)
from sase.ace.tui.modals import ConfirmActionModal
from sase.ace.tui.modals.existing_definition_finder_modal import (
    ExistingDefinitionFinderModal,
)
from sase.ace.tui.modals.mini_macro_name_modal import (
    MiniMacroNameModal,
    MiniMacroNameResult,
)
from sase.ace.tui.modals.mini_macro_target_catalog import (
    MiniMacroDefinition,
    MiniMacroDestinationTarget,
    MiniMacroTargetCatalog,
)
from sase.ace.tui.modals.save_location_choices import EXISTING_CHOICE_ID
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
from sase.ace.tui.modals.unified_macro_save_support import UnifiedSaveLocation
from sase.ace.tui.modals.macro_location_modal import (
    MACRO_HOME_DIR_LABEL,
    MACRO_PROJECT_DIR_LABEL,
    MacroLocation,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.macro.naming import SaveResolution
from sase.macro.save import SaveTargetFormat

from ._prompt_save_macro_helpers import _SaveFlowApp


class _MiniFlowApp(PromptBarMiniMacroPaneMixin, _SaveFlowApp):
    """Save-flow app with the mini-macro location-first handler enabled."""


def _row(
    path: Path,
    label: str,
    *,
    namespace: str | None = None,
    names: frozenset[str] = frozenset(),
    precedence: int = 0,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=MacroLocation(label, str(path), "directory"),  # type: ignore[arg-type]
        group="Project" if label == MACRO_PROJECT_DIR_LABEL else "Home",
        display_path=str(path),
        names=names,
        precedence=precedence,
        namespace=namespace,
    )


def _rows(tmp_path: Path) -> tuple[UnifiedSaveLocation, UnifiedSaveLocation]:
    project_row = _row(
        tmp_path / "project-macros",
        MACRO_PROJECT_DIR_LABEL,
        namespace="sase",
        names=frozenset({"rev"}),
        precedence=0,
    )
    home_row = _row(
        tmp_path / "home-macros",
        MACRO_HOME_DIR_LABEL,
        precedence=10,
    )
    return project_row, home_row


def _catalog(
    rows: tuple[UnifiedSaveLocation, ...],
    definitions: tuple[MiniMacroDefinition, ...] = (),
) -> MiniMacroTargetCatalog:
    return MiniMacroTargetCatalog(definitions=definitions, destinations=tuple(rows))


def _definition(
    name: str,
    path: Path,
    *,
    location_path: str,
    compatibility: str = "editable",
    effective: bool = True,
    precedence: int = 0,
    origin_label: str | None = None,
    shadowed_by: str | None = None,
) -> MiniMacroDefinition:
    return MiniMacroDefinition(
        name=name,
        workflow_kind="macro",
        source_path=str(path),
        display_path=str(path),
        storage_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        location_path=location_path,
        precedence=precedence,
        compatibility=compatibility,  # type: ignore[arg-type]
        origin_label=origin_label,
        effective=effective,
        shadowed_by=shadowed_by,
        read_path=str(path),
        write_path=str(path),
    )


def _write_macro(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _patch_flow(
    rows: tuple[UnifiedSaveLocation, ...],
    *,
    last_used: dict | None = None,
    definitions: tuple[MiniMacroDefinition, ...] = (),
):
    """Patch the flow's loader seams to serve fixture rows and catalog."""
    return (
        patch.object(location_mod, "_load_unified_save_rows", return_value=list(rows)),
        patch.object(
            location_mod,
            "_load_last_used_locations",
            return_value={} if last_used is None else last_used,
        ),
        patch.object(
            location_mod,
            "_load_mini_macro_catalog",
            side_effect=lambda project, loaded: _catalog(
                tuple(loaded), definitions=definitions
            ),
        ),
    )


async def _wait_mini_tasks(app: _MiniFlowApp) -> None:
    tasks = list(getattr(app, "_mini_macro_pane_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def _wait_picker(pilot, app: _MiniFlowApp) -> SaveLocationPickerModal:
    await wait_for(pilot, lambda: isinstance(app.screen, SaveLocationPickerModal))
    screen = app.screen
    assert isinstance(screen, SaveLocationPickerModal)
    return screen


async def _wait_picker_loaded(pilot, picker: SaveLocationPickerModal) -> None:
    await wait_for(pilot, lambda: picker.loaded and picker.highlighted_id is not None)


async def _wait_name_modal(pilot, app: _MiniFlowApp) -> MiniMacroNameModal:
    await wait_for(pilot, lambda: isinstance(app.screen, MiniMacroNameModal))
    screen = app.screen
    assert isinstance(screen, MiniMacroNameModal)
    return screen


async def _wait_finder(pilot, app: _MiniFlowApp) -> ExistingDefinitionFinderModal:
    await wait_for(pilot, lambda: isinstance(app.screen, ExistingDefinitionFinderModal))
    screen = app.screen
    assert isinstance(screen, ExistingDefinitionFinderModal)
    return screen


async def _wait_mini_pane(pilot, bar: PromptInputBar) -> None:
    await wait_for(pilot, lambda: bar._stack.mini_macro_item is not None)


@pytest.mark.parametrize(
    "keys",
    [
        pytest.param(("g", "x"), id="gx"),
        pytest.param(("ctrl+g", "ctrl+x"), id="ctrl-g-ctrl-x"),
    ],
)
async def test_chord_shows_picker_before_loaders_finish(
    tmp_path: Path, keys: tuple[str, ...]
) -> None:
    rows = _rows(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def _slow_rows(project: str | None) -> list:
        entered.set()
        assert release.wait(timeout=10)
        return list(rows)

    last_used_patch, catalog_patch = _patch_flow(rows)[1], _patch_flow(rows)[2]
    app = _MiniFlowApp("agent prompt")
    with (
        patch.object(location_mod, "_load_unified_save_rows", side_effect=_slow_rows),
        last_used_patch,
        catalog_patch,
    ):
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            if keys[0] == "g":
                await pilot.press("escape")
            await pilot.press(*keys)
            picker = await _wait_picker(pilot, app)
            assert "where should it live?" in picker._title
            await wait_for(pilot, entered.is_set)
            release.set()
            await _wait_picker_loaded(pilot, picker)
            await _wait_mini_tasks(app)
            assert bar.current_prompt_text() == "agent prompt"


async def test_hotkey_pick_opens_name_step_on_project_row(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, _home_row = rows
    patches = _patch_flow(rows)
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("p")
            modal = await _wait_name_modal(pilot, app)
            assert modal._destination.location.path == project_row.location.path
            await pilot.pause()
            assert modal.query_one("#mini-macro-name-input", Input).value == ""


async def test_enter_takes_star_default(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, _home_row = rows
    patches = _patch_flow(rows)
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            default = next(choice for choice in picker._choices if choice.is_default)
            assert default.choice_id == project_row.location.path
            await pilot.press("enter")
            modal = await _wait_name_modal(pilot, app)
            assert modal._destination.location.path == project_row.location.path


async def test_fast_typeahead_seeds_namespaced_name(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def _slow_rows(project: str | None) -> list:
        entered.set()
        assert release.wait(timeout=10)
        return list(rows)

    last_used_patch, catalog_patch = _patch_flow(rows)[1], _patch_flow(rows)[2]
    app = _MiniFlowApp("agent prompt")
    with (
        patch.object(location_mod, "_load_unified_save_rows", side_effect=_slow_rows),
        last_used_patch,
        catalog_patch,
    ):
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            await _wait_picker(pilot, app)
            await wait_for(pilot, entered.is_set)
            await pilot.press("p", "r", "e", "v")
            release.set()
            modal = await _wait_name_modal(pilot, app)
            await pilot.pause()
            assert modal.query_one("#mini-macro-name-input", Input).value == "sase/rev"
            assert bar.current_prompt_text() == "agent prompt"


async def test_shift_tab_round_trip_rebases_name(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, home_row = rows
    entered = threading.Event()
    release = threading.Event()

    def _slow_rows(project: str | None) -> list:
        entered.set()
        assert release.wait(timeout=10)
        return list(rows)

    last_used_patch, catalog_patch = _patch_flow(rows)[1], _patch_flow(rows)[2]
    app = _MiniFlowApp("agent prompt")
    with (
        patch.object(location_mod, "_load_unified_save_rows", side_effect=_slow_rows),
        last_used_patch,
        catalog_patch,
    ):
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "x")
            await _wait_picker(pilot, app)
            await wait_for(pilot, entered.is_set)
            await pilot.press("p", "r", "e", "v")
            release.set()
            modal = await _wait_name_modal(pilot, app)

            def _name_value() -> str | None:
                try:
                    return modal.query_one("#mini-macro-name-input", Input).value
                except Exception:
                    return None

            await wait_for(pilot, lambda: _name_value() == "sase/rev", timeout=8.0)
            await pilot.press("shift+tab")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            assert picker.highlighted_id == project_row.location.path
            project_choice = next(
                choice
                for choice in picker._choices
                if choice.choice_id == project_row.location.path
            )
            assert any(badge.startswith("has #") for badge in project_choice.badges)
            await pilot.press("h")
            modal = await _wait_name_modal(pilot, app)

            def _rebased_value() -> str | None:
                try:
                    return modal.query_one("#mini-macro-name-input", Input).value
                except Exception:
                    return None

            await wait_for(pilot, lambda: _rebased_value() == "rev", timeout=8.0)
            assert modal._destination.location.path == home_row.location.path


async def test_esc_in_either_step_restores_origin(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    patches = _patch_flow(rows)
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            origin = bar.active_text_area()
            origin.cursor_location = (0, 3)
            await pilot.press("g", "x")
            await _wait_picker(pilot, app)
            await pilot.press("escape")
            await wait_for(
                pilot, lambda: not isinstance(app.screen, SaveLocationPickerModal)
            )
            await pilot.pause()
            assert bar.active_text_area().has_focus
            assert bar.active_text_area().cursor_location == (0, 3)

            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("p")
            await _wait_name_modal(pilot, app)
            await pilot.press("escape")
            await wait_for(
                pilot, lambda: not isinstance(app.screen, MiniMacroNameModal)
            )
            await pilot.pause()
            assert bar.active_text_area().has_focus


def _open_mini(
    bar: PromptInputBar, path: Path, *, name: str = "review"
) -> MiniMacroNameResult:
    target = MiniMacroDestinationTarget(
        name=name,
        location_path=str(path.parent),
        path=str(path),
        display_path=str(path),
        target_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        storage_name=name,
        read_path=str(path),
        write_path=str(path),
        apply_target=None,
        via_chezmoi=False,
        exists_here=True,
        resolution=SaveResolution(),
    )
    result = MiniMacroNameResult(
        name=name,
        action="edit",
        destination=target,
        definition=None,
        existing_definition=None,
    )
    assert bar.open_mini_macro_target_pane(
        result,
        origin_pane_id=bar.active_text_area().id or "",
        body="mini body",
        frontmatter="",
        loaded_markdown=None,
        loaded_fingerprint=None,
        destination_exists=True,
    )
    return result


async def test_retargeting_open_pane_defaults_to_current(tmp_path: Path) -> None:
    project_dir = tmp_path / "project-macros"
    project_dir.mkdir(parents=True, exist_ok=True)
    rows = _rows(tmp_path)
    project_row, _home_row = rows
    assert project_row.location.path == str(project_dir)
    patches = _patch_flow(rows)
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            _open_mini(bar, project_dir / "review.md")
            await pilot.pause()
            bar.request_mini_macro_target_pane()
            picker = await _wait_picker(pilot, app)
            assert picker._title.startswith("Retarget #review")
            await _wait_picker_loaded(pilot, picker)
            default = next(choice for choice in picker._choices if choice.is_default)
            assert default.choice_id == project_row.location.path
            assert "★ current" in default.badges


async def test_origin_vanished_closes_picker_with_warning(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def _slow_rows(project: str | None) -> list:
        entered.set()
        assert release.wait(timeout=10)
        return list(rows)

    last_used_patch, catalog_patch = _patch_flow(rows)[1], _patch_flow(rows)[2]
    app = _MiniFlowApp("agent prompt")
    with (
        patch.object(location_mod, "_load_unified_save_rows", side_effect=_slow_rows),
        last_used_patch,
        catalog_patch,
    ):
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            await _wait_picker(pilot, app)
            await wait_for(pilot, entered.is_set)
            bar.mini_macro_target_origin_available = lambda pane_id: False  # type: ignore[method-assign]
            release.set()
            await _wait_mini_tasks(app)
            await wait_for(
                pilot, lambda: not isinstance(app.screen, SaveLocationPickerModal)
            )
            assert (
                "Prompt pane is no longer available - mini-macro discarded",
                "warning",
            ) in app.notifications


async def test_existing_row_is_present_and_disabled_when_empty(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    patches = _patch_flow(rows)
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.disabled_reason == "no macros yet"
            assert existing.is_default is False


async def test_existing_editable_opens_pane_with_loaded_body(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    _write_macro(path, "loaded from disk")
    definition = _definition("rev", path, location_path=project_row.location.path)
    patches = _patch_flow(rows, definitions=(definition,))
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.disabled_reason is None
            assert "1 macros" in existing.badges
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_mini_tasks(app)
            await _wait_mini_pane(pilot, bar)
            mini = bar._stack.mini_macro_item
            assert mini is not None
            assert mini.mini_macro_target is not None
            assert "loaded from disk" in bar.active_text()
            assert mini.mini_macro_target.name == "rev"
            assert mini.mini_macro_target.save_warning is None


async def test_existing_shadowed_edit_carries_warning(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, home_row = rows
    winner = Path(project_row.location.path) / "rev.md"
    shadowed = Path(home_row.location.path) / "rev.md"
    _write_macro(winner, "project body")
    _write_macro(shadowed, "home body")
    definitions = (
        _definition(
            "rev",
            winner,
            location_path=project_row.location.path,
            precedence=0,
        ),
        _definition(
            "rev",
            shadowed,
            location_path=home_row.location.path,
            effective=False,
            precedence=10,
            shadowed_by=str(winner),
        ),
    )
    patches = _patch_flow(rows, definitions=definitions)
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await _wait_mini_tasks(app)
            await _wait_mini_pane(pilot, bar)
            mini = bar._stack.mini_macro_item
            assert mini is not None
            assert mini.mini_macro_target is not None
            assert "home body" in bar.active_text()
            assert mini.mini_macro_target.save_warning is not None
            assert "shadowed" in mini.mini_macro_target.save_warning


async def test_existing_read_only_override_picker_to_pane(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, home_row = rows
    builtin = tmp_path / "default_macros" / "rev.md"
    _write_macro(builtin, "built-in body")
    definition = _definition(
        "rev",
        builtin,
        location_path=str(builtin.parent),
        compatibility="read_only",
        origin_label="built-in",
    )
    patches = _patch_flow(rows, definitions=(definition,))
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
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
            modal = await _wait_name_modal(pilot, app)
            await pilot.pause()
            assert modal.query_one("#mini-macro-name-input", Input).value == "rev"
            await pilot.press("enter")
            await _wait_mini_tasks(app)
            await _wait_mini_pane(pilot, bar)
            assert "built-in body" in bar.active_text()
            mini = bar._stack.mini_macro_item
            assert mini is not None
            assert mini.mini_macro_target is not None
            assert mini.mini_macro_target.location_path == home_row.location.path


async def test_existing_finder_back_remembers_query_and_cancel_refocuses(
    tmp_path: Path,
) -> None:
    rows = _rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    _write_macro(path, "body")
    definition = _definition("rev", path, location_path=project_row.location.path)
    patches = _patch_flow(rows, definitions=(definition,))
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            origin = bar.active_text_area()
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            finder = await _wait_finder(pilot, app)
            await pilot.press("r", "e")
            await pilot.pause()
            await pilot.press("shift+tab")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            assert picker.highlighted_id == EXISTING_CHOICE_ID
            await pilot.press("e")
            finder = await _wait_finder(pilot, app)
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
    rows = _rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    _write_macro(path, "body")
    definition = _definition("rev", path, location_path=project_row.location.path)
    entered = threading.Event()
    release = threading.Event()

    def _slow_rows(project: str | None) -> list:
        entered.set()
        assert release.wait(timeout=10)
        return list(rows)

    last_used_patch, catalog_patch = _patch_flow(rows, definitions=(definition,))[1:]
    app = _MiniFlowApp("agent prompt")
    with (
        patch.object(location_mod, "_load_unified_save_rows", side_effect=_slow_rows),
        last_used_patch,
        catalog_patch,
    ):
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "x")
            await _wait_picker(pilot, app)
            await wait_for(pilot, entered.is_set)
            await pilot.press("e", "r", "e", "v")
            release.set()
            finder = await _wait_finder(pilot, app)

            def _query_value() -> str | None:
                try:
                    return finder.query_one("#existing-finder-query", Input).value
                except Exception:
                    return None

            await wait_for(pilot, lambda: _query_value() == "rev")


async def test_existing_finder_origin_lost_warns(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    _write_macro(path, "body")
    definition = _definition("rev", path, location_path=project_row.location.path)
    patches = _patch_flow(rows, definitions=(definition,))
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
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


async def test_existing_same_target_focuses_and_notifies(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, _home_row = rows
    path = Path(project_row.location.path) / "rev.md"
    _write_macro(path, "loaded from disk")
    definition = _definition("rev", path, location_path=project_row.location.path)
    patches = _patch_flow(rows, definitions=(definition,))
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_mini_tasks(app)
            await _wait_mini_pane(pilot, bar)
            bar.active_text_area().text = "user draft"
            bar._sync_state_from_widgets()

            bar.request_mini_macro_target_pane()
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.label.startswith("Switch to existing")
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_mini_tasks(app)
            await wait_for(
                pilot,
                lambda: any(
                    message == "Already editing #rev"
                    for message, _sev in app.notifications
                ),
            )
            assert bar.active_text() == "user draft"


async def test_existing_replaces_clean_open_pane(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    project_row, home_row = rows
    first = Path(project_row.location.path) / "rev.md"
    second = Path(home_row.location.path) / "todo.md"
    _write_macro(first, "first body")
    _write_macro(second, "second body")
    definitions = (
        _definition(
            "rev", first, location_path=project_row.location.path, precedence=0
        ),
        _definition(
            "todo", second, location_path=home_row.location.path, precedence=10
        ),
    )
    patches = _patch_flow(rows, definitions=definitions)
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_mini_tasks(app)
            await _wait_mini_pane(pilot, bar)
            assert "first body" in bar.active_text()
            restore = bar._mini_macro_focus_restore

            bar.request_mini_macro_target_pane()
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await _wait_mini_tasks(app)
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
    rows = _rows(tmp_path)
    project_row, home_row = rows
    first = Path(project_row.location.path) / "rev.md"
    second = Path(home_row.location.path) / "todo.md"
    _write_macro(first, "first body")
    _write_macro(second, "second body")
    definitions = (
        _definition(
            "rev", first, location_path=project_row.location.path, precedence=0
        ),
        _definition(
            "todo", second, location_path=home_row.location.path, precedence=10
        ),
    )
    patches = _patch_flow(rows, definitions=definitions)
    app = _MiniFlowApp("agent prompt")
    with patches[0], patches[1], patches[2]:
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "x")
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_mini_tasks(app)
            await _wait_mini_pane(pilot, bar)
            bar.active_text_area().text = "dirty draft"
            bar._sync_state_from_widgets()

            bar.request_mini_macro_target_pane()
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
            await pilot.press("n")
            await pilot.pause()
            assert bar.active_text() == "dirty draft"

            bar.request_mini_macro_target_pane()
            picker = await _wait_picker(pilot, app)
            await _wait_picker_loaded(pilot, picker)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
            await pilot.press("y")
            await _wait_mini_tasks(app)
            await wait_for(pilot, lambda: "second body" in bar.active_text())
