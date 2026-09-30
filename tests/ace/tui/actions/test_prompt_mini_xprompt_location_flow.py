"""Location-first mini-xprompt flow through the save-location picker."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from unittest.mock import patch

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow import (
    _prompt_bar_mini_xprompt_pane as mini_pane_mod,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_mini_xprompt_pane import (
    PromptBarMiniXPromptPaneMixin,
)
from sase.ace.tui.modals.mini_xprompt_name_modal import (
    MiniXPromptNameModal,
    MiniXPromptNameResult,
)
from sase.ace.tui.modals.mini_xprompt_target_catalog import (
    MiniXPromptDestinationTarget,
    MiniXPromptTargetCatalog,
)
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
from sase.ace.tui.modals.unified_xprompt_save_support import UnifiedSaveLocation
from sase.ace.tui.modals.xprompt_location_modal import (
    XPROMPT_HOME_DIR_LABEL,
    XPROMPT_PROJECT_DIR_LABEL,
    XPromptLocation,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.naming import SaveResolution
from sase.xprompt.save import SaveTargetFormat

from ._prompt_save_xprompt_helpers import _SaveFlowApp


class _MiniFlowApp(PromptBarMiniXPromptPaneMixin, _SaveFlowApp):
    """Save-flow app with the mini-xprompt location-first handler enabled."""


def _row(
    path: Path,
    label: str,
    *,
    namespace: str | None = None,
    names: frozenset[str] = frozenset(),
    precedence: int = 0,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=XPromptLocation(label, str(path), "directory"),  # type: ignore[arg-type]
        group="Project" if label == XPROMPT_PROJECT_DIR_LABEL else "Home",
        display_path=str(path),
        names=names,
        precedence=precedence,
        namespace=namespace,
    )


def _rows(tmp_path: Path) -> tuple[UnifiedSaveLocation, UnifiedSaveLocation]:
    project_row = _row(
        tmp_path / "project-xprompts",
        XPROMPT_PROJECT_DIR_LABEL,
        namespace="sase",
        names=frozenset({"rev"}),
        precedence=0,
    )
    home_row = _row(
        tmp_path / "home-xprompts",
        XPROMPT_HOME_DIR_LABEL,
        precedence=10,
    )
    return project_row, home_row


def _catalog(rows: tuple[UnifiedSaveLocation, ...]) -> MiniXPromptTargetCatalog:
    return MiniXPromptTargetCatalog(definitions=(), destinations=tuple(rows))


def _patch_flow(
    rows: tuple[UnifiedSaveLocation, ...],
    *,
    last_used: dict | None = None,
):
    """Patch the flow's loader seams to serve fixture rows and catalog."""
    return (
        patch.object(mini_pane_mod, "_load_unified_save_rows", return_value=list(rows)),
        patch.object(
            mini_pane_mod,
            "_load_last_used_locations",
            return_value={} if last_used is None else last_used,
        ),
        patch.object(
            mini_pane_mod,
            "_load_mini_xprompt_catalog",
            side_effect=lambda project, rows: _catalog(tuple(rows)),
        ),
    )


async def _wait_mini_tasks(app: _MiniFlowApp) -> None:
    tasks = list(getattr(app, "_mini_xprompt_pane_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def _wait_picker(pilot, app: _MiniFlowApp) -> SaveLocationPickerModal:
    await wait_for(pilot, lambda: isinstance(app.screen, SaveLocationPickerModal))
    screen = app.screen
    assert isinstance(screen, SaveLocationPickerModal)
    return screen


async def _wait_picker_loaded(pilot, picker: SaveLocationPickerModal) -> None:
    await wait_for(pilot, lambda: picker.loaded and picker.highlighted_id is not None)


async def _wait_name_modal(pilot, app: _MiniFlowApp) -> MiniXPromptNameModal:
    await wait_for(pilot, lambda: isinstance(app.screen, MiniXPromptNameModal))
    screen = app.screen
    assert isinstance(screen, MiniXPromptNameModal)
    return screen


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
        patch.object(mini_pane_mod, "_load_unified_save_rows", side_effect=_slow_rows),
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
            assert modal.query_one("#mini-xprompt-name-input", Input).value == ""


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
        patch.object(mini_pane_mod, "_load_unified_save_rows", side_effect=_slow_rows),
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
            assert (
                modal.query_one("#mini-xprompt-name-input", Input).value == "sase/rev"
            )
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
        patch.object(mini_pane_mod, "_load_unified_save_rows", side_effect=_slow_rows),
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
                    return modal.query_one("#mini-xprompt-name-input", Input).value
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
                    return modal.query_one("#mini-xprompt-name-input", Input).value
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
                pilot, lambda: not isinstance(app.screen, MiniXPromptNameModal)
            )
            await pilot.pause()
            assert bar.active_text_area().has_focus


def _open_mini(
    bar: PromptInputBar, path: Path, *, name: str = "review"
) -> MiniXPromptNameResult:
    target = MiniXPromptDestinationTarget(
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
    result = MiniXPromptNameResult(
        name=name,
        action="edit",
        destination=target,
        definition=None,
        existing_definition=None,
    )
    assert bar.open_mini_xprompt_target_pane(
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
    project_dir = tmp_path / "project-xprompts"
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
            bar.request_mini_xprompt_target_pane()
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
        patch.object(mini_pane_mod, "_load_unified_save_rows", side_effect=_slow_rows),
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
            bar.mini_xprompt_target_origin_available = lambda pane_id: False  # type: ignore[method-assign]
            release.set()
            await _wait_mini_tasks(app)
            await wait_for(
                pilot, lambda: not isinstance(app.screen, SaveLocationPickerModal)
            )
            assert (
                "Prompt pane is no longer available - mini-xprompt discarded",
                "warning",
            ) in app.notifications
