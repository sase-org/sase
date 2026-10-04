"""Shared fixtures for location-first mini-macro flow tests.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_prompt_mini_macro_location_flow_*`` split modules can
share them without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow import (
    _prompt_bar_mini_macro_location as location_mod,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_mini_macro_pane import (
    PromptBarMiniMacroPaneMixin,
)
from sase.ace.tui.modals.existing_definition_finder_modal import (
    ExistingDefinitionFinderModal,
)
from sase.ace.tui.modals.macro_location_modal import (
    MACRO_HOME_DIR_LABEL,
    MACRO_PROJECT_DIR_LABEL,
    MacroLocation,
)
from sase.ace.tui.modals.mini_macro_name_modal import MiniMacroNameModal
from sase.ace.tui.modals.mini_macro_target_catalog import (
    MiniMacroDefinition,
    MiniMacroTargetCatalog,
)
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
from sase.ace.tui.modals.unified_macro_save_support import UnifiedSaveLocation
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.macro.save import SaveTargetFormat

from ._prompt_save_macro_helpers import _SaveFlowApp


class MiniFlowApp(PromptBarMiniMacroPaneMixin, _SaveFlowApp):
    """Save-flow app with the mini-macro location-first handler enabled."""


def _make_row(
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


def make_rows(tmp_path: Path) -> tuple[UnifiedSaveLocation, UnifiedSaveLocation]:
    project_row = _make_row(
        tmp_path / "project-macros",
        MACRO_PROJECT_DIR_LABEL,
        namespace="sase",
        names=frozenset({"rev"}),
        precedence=0,
    )
    home_row = _make_row(
        tmp_path / "home-macros",
        MACRO_HOME_DIR_LABEL,
        precedence=10,
    )
    return project_row, home_row


def _make_catalog(
    rows: tuple[UnifiedSaveLocation, ...],
    definitions: tuple[MiniMacroDefinition, ...] = (),
) -> MiniMacroTargetCatalog:
    return MiniMacroTargetCatalog(definitions=definitions, destinations=tuple(rows))


def make_definition(
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


def write_macro(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def patch_flow(
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
            side_effect=lambda project, loaded: _make_catalog(
                tuple(loaded), definitions=definitions
            ),
        ),
    )


async def wait_mini_tasks(app: MiniFlowApp) -> None:
    tasks = list(getattr(app, "_mini_macro_pane_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def wait_picker(pilot, app: MiniFlowApp) -> SaveLocationPickerModal:
    await wait_for(pilot, lambda: isinstance(app.screen, SaveLocationPickerModal))
    screen = app.screen
    assert isinstance(screen, SaveLocationPickerModal)
    return screen


async def wait_picker_loaded(pilot, picker: SaveLocationPickerModal) -> None:
    await wait_for(pilot, lambda: picker.loaded and picker.highlighted_id is not None)


async def wait_name_modal(pilot, app: MiniFlowApp) -> MiniMacroNameModal:
    await wait_for(pilot, lambda: isinstance(app.screen, MiniMacroNameModal))
    screen = app.screen
    assert isinstance(screen, MiniMacroNameModal)
    return screen


async def wait_finder(pilot, app: MiniFlowApp) -> ExistingDefinitionFinderModal:
    await wait_for(pilot, lambda: isinstance(app.screen, ExistingDefinitionFinderModal))
    screen = app.screen
    assert isinstance(screen, ExistingDefinitionFinderModal)
    return screen


async def wait_mini_pane(pilot, bar: PromptInputBar) -> None:
    await wait_for(pilot, lambda: bar._stack.mini_macro_item is not None)
