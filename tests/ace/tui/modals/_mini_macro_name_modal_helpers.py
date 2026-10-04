"""Shared helpers for the split mini-macro name modal tests.

The tests formerly lived in a single ``test_mini_macro_name_modal`` module.
Helpers needed by more than one split module live here under public names;
the ``test_mini_macro_name_modal_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing.wait import wait_for as wait_for_pilot
from sase.ace.tui.modals.macro_location_modal import MacroLocation
from sase.ace.tui.modals.mini_macro_name_modal import MiniMacroNameModal
from sase.ace.tui.modals.mini_macro_target_catalog import MiniMacroDefinition
from sase.ace.tui.modals.unified_macro_save_modal import UnifiedSaveLocation
from sase.macro.save import SaveTargetFormat

__all__ = [
    "MiniMacroNameModalApp",
    "make_definition",
    "make_row",
    "wait_for_analysis_idle",
    "wait_for_verdict",
]


class MiniMacroNameModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("")


def make_row(
    path: Path,
    *,
    names: frozenset[str] = frozenset(),
    location_type: str = "directory",
    label: str = "Test",
    group: str = "Project",
    precedence: int = 0,
    disabled_reason: str | None = None,
    namespace: str | None = None,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=MacroLocation(label, str(path), location_type),  # type: ignore[arg-type]
        group=group,
        display_path=str(path),
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
        namespace=namespace,
    )


def make_definition(
    name: str,
    path: Path,
    *,
    compatibility: str = "editable",
    workflow_kind: str = "macro",
    effective: bool = True,
    location_path: str | None = None,
    precedence: int = 0,
    reason: str | None = None,
) -> MiniMacroDefinition:
    return MiniMacroDefinition(
        name=name,
        workflow_kind=workflow_kind,  # type: ignore[arg-type]
        source_path=str(path),
        display_path=str(path),
        storage_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        location_path=location_path or str(path.parent),
        precedence=precedence,
        compatibility=compatibility,  # type: ignore[arg-type]
        incompatible_reason=reason,
        effective=effective,
        read_path=str(path),
        write_path=str(path),
    )


def _verdict_text(modal: MiniMacroNameModal) -> str | None:
    if not modal.query("#mini-macro-name-verdict"):
        return None
    return modal.query_one("#mini-macro-name-verdict", Static).render().plain


async def wait_for_analysis_idle(
    pilot: Any,
    modal: MiniMacroNameModal,
    *,
    timeout: float = 8.0,
) -> None:
    def _ready() -> bool:
        text = _verdict_text(modal)
        if text is None or "Checking #" in text:
            return False
        return not modal._pending_analyses and not modal._analysis_tasks

    await wait_for_pilot(pilot, _ready, timeout=timeout)


async def wait_for_verdict(
    pilot: Any,
    modal: MiniMacroNameModal,
    needle: str,
    *,
    timeout: float = 8.0,
) -> str:
    def _ready() -> bool:
        text = _verdict_text(modal)
        if text is None or "Checking #" in text:
            return False
        if modal._pending_analyses or modal._analysis_tasks:
            return False
        return needle in text

    await wait_for_pilot(pilot, _ready, timeout=timeout)
    rendered = _verdict_text(modal)
    assert rendered is not None
    return rendered
