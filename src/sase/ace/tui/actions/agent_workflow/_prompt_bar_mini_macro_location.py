"""Location-first mini-macro flow: picker, existing finder, and override."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import _prompt_bar_mini_macro_pane as _mini_pane

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sase.ace.tui.modals.existing_definition_entries import ExistingDefinitionEntry
    from sase.ace.tui.modals.existing_definition_finder_modal import (
        ExistingDefinitionPick,
        ExistingFinderBack,
    )
    from sase.ace.tui.modals.mini_macro_name_modal import MiniMacroNameResult
    from sase.ace.tui.modals.mini_macro_target_catalog import (
        MiniMacroDefinition,
        MiniMacroTargetCatalog,
    )
    from sase.ace.tui.modals.save_location_choices import (
        ChangeSaveLocationRequest,
        SaveLocationChoice,
        SaveLocationPick,
    )
    from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
    from sase.ace.tui.modals.unified_macro_save_support import UnifiedSaveLocation
    from sase.ace.tui.widgets import PromptInputBar
    from sase.macro.save_state import SaveKind


_ORIGIN_LOST = "Prompt pane is no longer available - mini-macro discarded"


class MiniMacroLocationFlow:
    """One location-first mini-macro request, picker first then name step."""

    def __init__(
        self,
        app: Any,
        *,
        origin_bar: PromptInputBar,
        origin_pane_id: str,
        initial_name: str,
        current_location_path: str | None,
    ) -> None:
        self._app = app
        self._origin_bar = origin_bar
        self._origin_pane_id = origin_pane_id
        self._seed_base = initial_name
        self._seed_from_path = current_location_path
        self._current_location_path = current_location_path
        context = app._prompt_context
        if context is not None and not context.is_home_mode:
            self._project: str | None = context.project_name
        else:
            self._project = None
        self._home_mode = bool(context is not None and context.is_home_mode)
        self._catalog: MiniMacroTargetCatalog | None = None
        self._rows: tuple[UnifiedSaveLocation, ...] = ()
        self._entries: tuple[ExistingDefinitionEntry, ...] = ()
        self._definitions_by_entry_id: dict[str, MiniMacroDefinition] = {}
        self._finder_query: str | None = None
        self._override_name: str | None = None
        self._settled = False

    def start(self) -> None:
        """Push the picker synchronously and load destinations in the background."""
        self._push_normal_picker(highlight_id=None)

    def _origin_available(self) -> bool:
        return bool(
            self._origin_bar.is_mounted
            and self._origin_bar.mini_macro_target_origin_available(
                self._origin_pane_id
            )
        )

    def _mini_pane_is_open(self) -> bool:
        return bool(
            self._origin_bar.is_mounted
            and self._origin_bar._stack.mini_macro_item is not None
        )

    def _discard_origin_lost(self) -> None:
        self._app.notify(  # type: ignore[attr-defined]
            _ORIGIN_LOST,
            severity="warning",
        )

    def _push_normal_picker(self, *, highlight_id: str | None) -> None:
        from ...modals.save_location_picker_modal import SaveLocationPickerModal

        self._settled = False
        self._override_name = None
        picker = SaveLocationPickerModal(
            kind="macro",
            title=_mini_macro_picker_title(
                self._seed_base, self._current_location_path
            ),
        )
        self._app.push_screen(picker, self._on_pick)  # type: ignore[attr-defined]
        self._app._spawn_mini_macro_pane_task(
            self._load_and_show(
                picker,
                name=self._seed_base,
                highlight_id=highlight_id,
            )
        )

    async def _load_and_show(
        self,
        picker: SaveLocationPickerModal,
        *,
        name: str,
        highlight_id: str | None,
        override_name: str | None = None,
    ) -> None:
        """Load rows, catalog, and choices off-thread, then feed the picker."""
        switching = self._mini_pane_is_open()
        try:
            rows = await asyncio.to_thread(_load_unified_save_rows, self._project)
            last_used = await asyncio.to_thread(_load_last_used_locations)
            catalog = await asyncio.to_thread(
                _load_mini_macro_catalog, self._project, rows
            )
            payload = await asyncio.to_thread(
                _picker_payload,
                rows,
                catalog,
                last_used_path=last_used.get("macro"),
                current_path=self._current_location_path,
                home_mode=self._home_mode,
                project=self._project,
                name=name,
                switching=switching,
                override_name=override_name,
            )
        except Exception as exc:
            if self._settled:
                return
            if not self._origin_available():
                self._settled = True
                self._discard_origin_lost()
                picker.dismiss(None)
                return
            self._app.notify(  # type: ignore[attr-defined]
                f"Failed to prepare mini-macro pane: {exc}",
                severity="error",
            )
            picker.set_load_error(f"Failed to load destinations: {exc}")
            return
        # Stored before set_choices so the dismiss callback, which may run
        # synchronously inside set_choices, can push the next step with no
        # further awaits.
        self._rows = tuple(rows)
        self._catalog = catalog
        self._entries = payload.entries
        self._definitions_by_entry_id = payload.definitions_by_entry_id
        if self._settled:
            return
        if not self._origin_available():
            self._settled = True
            self._discard_origin_lost()
            picker.dismiss(None)
            return
        picker.set_choices(payload.choices, highlight_id=highlight_id)

    def _on_pick(self, pick: SaveLocationPick | None) -> None:
        from ...modals.save_location_choices import EXISTING_CHOICE_ID

        self._settled = True
        if pick is None or self._catalog is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if not self._origin_available():
            self._discard_origin_lost()
            return
        if pick.choice_id == EXISTING_CHOICE_ID:
            query = (
                self._finder_query if self._finder_query is not None else pick.typeahead
            )
            self._open_existing_finder(query)
            return
        row = next(
            (item for item in self._rows if item.location.path == pick.choice_id),
            None,
        )
        if row is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        self._open_name_step(row, (self._seed_base or "") + (pick.typeahead or ""))

    def _open_existing_finder(self, query: str) -> None:
        from ...modals.existing_definition_finder_modal import (
            ExistingDefinitionFinderModal,
        )

        modal = ExistingDefinitionFinderModal(
            "macro",
            self._entries,
            initial_query=query,
            preview_loader=self._preview_loader,
        )
        self._app.push_screen(  # type: ignore[attr-defined]
            modal, self._on_finder_result
        )

    def _preview_loader(self, entry_id: str) -> str:
        definition = self._definitions_by_entry_id.get(entry_id)
        if definition is None:
            raise FileNotFoundError(f"Unknown definition {entry_id}")
        return _mini_pane._load_definition_markdown(definition)

    def _on_finder_result(
        self,
        result: ExistingDefinitionPick | ExistingFinderBack | None,
    ) -> None:
        from ...modals.existing_definition_finder_modal import (
            ExistingDefinitionPick,
            ExistingFinderBack,
        )
        from ...modals.save_location_choices import EXISTING_CHOICE_ID

        if not self._origin_available():
            self._discard_origin_lost()
            return
        if result is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if isinstance(result, ExistingFinderBack):
            self._finder_query = result.query
            self._push_normal_picker(highlight_id=EXISTING_CHOICE_ID)
            return
        if not isinstance(result, ExistingDefinitionPick):
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        definition = self._definitions_by_entry_id.get(result.entry_id)
        entry = next(
            (item for item in self._entries if item.entry_id == result.entry_id),
            None,
        )
        if definition is None or entry is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if entry.status == "read_only":
            self._open_override_picker(definition.name)
            return
        name_result = self._name_result_for_definition(definition)
        if name_result is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        self._apply_existing_result(
            name_result, replace_draft=self._mini_pane_is_open()
        )

    def _name_result_for_definition(
        self, definition: MiniMacroDefinition
    ) -> MiniMacroNameResult | None:
        from ...modals.mini_macro_name_modal import MiniMacroNameResult
        from ...modals.mini_macro_redefinition import (
            macro_redefinition,
            macro_redefinition_warning,
        )
        from ...modals.mini_macro_target_catalog import destination_target_for_name

        catalog = self._catalog
        if catalog is None:
            return None
        row = next(
            (
                item
                for item in self._rows
                if item.location.path == definition.location_path
            ),
            None,
        )
        if row is None:
            return None
        redef = macro_redefinition(catalog, definition.name, row)
        return MiniMacroNameResult(
            name=definition.name,
            action="edit",
            destination=destination_target_for_name(
                row, definition.name, destinations=catalog.destinations
            ),
            definition=definition,
            existing_definition=redef.active,
            save_warning=macro_redefinition_warning(redef),
        )

    def _already_editing(self, result: MiniMacroNameResult) -> bool:
        bar = self._origin_bar
        if not bar.is_mounted:
            return False
        bar._sync_state_from_widgets()
        mini = bar._stack.mini_macro_item
        if mini is None or mini.mini_macro_target is None:
            return False
        target = mini.mini_macro_target
        return (
            target.write_path == result.destination.write_path
            and target.name == result.name
        )

    def _focus_already_editing(self, name: str) -> None:
        bar = self._origin_bar
        index = bar._stack.mini_macro_index
        if index is not None:
            bar.focus_item(index)
        self._app.notify(f"Already editing #{name}")  # type: ignore[attr-defined]

    def _apply_existing_result(
        self,
        result: MiniMacroNameResult,
        *,
        replace_draft: bool,
    ) -> None:
        if not self._origin_available():
            self._discard_origin_lost()
            return
        if self._already_editing(result):
            self._focus_already_editing(result.name)
            return

        def proceed() -> None:
            self._app._spawn_mini_macro_pane_task(
                self._app._apply_mini_macro_name_result(
                    self._origin_bar,
                    self._origin_pane_id,
                    result,
                    replace_draft=replace_draft,
                )
            )

        if replace_draft and self._mini_pane_is_open():
            self._origin_bar.confirm_discard_dirty_auxiliary(proceed)
            return
        proceed()

    def _open_override_picker(
        self,
        name: str,
        *,
        highlight_id: str | None = None,
        seed_name: str | None = None,
    ) -> None:
        from ...modals.save_location_picker_modal import SaveLocationPickerModal

        self._settled = False
        self._override_name = name
        self._seed_base = name if seed_name is None else seed_name
        picker = SaveLocationPickerModal(
            kind="macro",
            title=f"Override #{name} · where should your copy live?",
        )
        self._app.push_screen(picker, self._on_override_pick)  # type: ignore[attr-defined]
        self._app._spawn_mini_macro_pane_task(
            self._load_and_show(
                picker,
                name=self._seed_base,
                highlight_id=highlight_id,
                override_name=name,
            )
        )

    def _on_override_pick(self, pick: SaveLocationPick | None) -> None:
        self._settled = True
        if pick is None or self._catalog is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if not self._origin_available():
            self._discard_origin_lost()
            return
        row = next(
            (item for item in self._rows if item.location.path == pick.choice_id),
            None,
        )
        if row is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        self._open_name_step(row, self._seed_base, rebase=False)

    def _open_name_step(
        self,
        row: UnifiedSaveLocation,
        raw_text: str,
        *,
        rebase: bool = True,
    ) -> None:
        from ...modals import MiniMacroNameModal
        from ...modals.mini_macro_target_catalog import rebase_name_for_destination

        catalog = self._catalog
        assert catalog is not None
        if rebase:
            from_row = next(
                (
                    item
                    for item in self._rows
                    if item.location.path == self._seed_from_path
                ),
                None,
            )
            seeded = rebase_name_for_destination(
                raw_text, row, from_destination=from_row
            )
        else:
            seeded = raw_text
        modal = MiniMacroNameModal(catalog, row, initial_name=seeded)
        self._app.push_screen(  # type: ignore[attr-defined]
            modal, lambda result: self._on_name_result(result, row)
        )

    def _on_name_result(
        self,
        result: MiniMacroNameResult | ChangeSaveLocationRequest | None,
        row: UnifiedSaveLocation,
    ) -> None:
        from ...modals.save_location_choices import ChangeSaveLocationRequest

        if not self._origin_available():
            self._discard_origin_lost()
            return
        if result is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if isinstance(result, ChangeSaveLocationRequest):
            self._seed_from_path = row.location.path
            if self._override_name is not None:
                self._open_override_picker(
                    self._override_name,
                    highlight_id=row.location.path,
                    seed_name=result.text,
                )
                return
            self._seed_base = result.text
            self._push_normal_picker(highlight_id=row.location.path)
            return
        if self._override_name is not None:
            self._apply_existing_result(result, replace_draft=True)
            return
        self._app._spawn_mini_macro_pane_task(
            self._app._apply_mini_macro_name_result(
                self._origin_bar,
                self._origin_pane_id,
                result,
            )
        )


@dataclass(frozen=True, slots=True)
class _PickerPayload:
    choices: tuple[SaveLocationChoice, ...]
    entries: tuple[ExistingDefinitionEntry, ...]
    definitions_by_entry_id: dict[str, MiniMacroDefinition]


def _picker_payload(
    rows: list[UnifiedSaveLocation],
    catalog: MiniMacroTargetCatalog,
    *,
    last_used_path: str | None,
    current_path: str | None,
    home_mode: bool,
    project: str | None,
    name: str,
    switching: bool,
    override_name: str | None,
) -> _PickerPayload:
    from sase.ace.tui.modals.existing_definition_entries import macro_existing_entries
    from sase.ace.tui.modals.mini_macro_redefinition import macro_redefinition
    from sase.ace.tui.modals.save_location_choices import (
        ExistingRowSpec,
        macro_location_choices,
    )

    entries = macro_existing_entries(catalog)
    definitions_by_entry_id = {
        entry.entry_id: definition
        for definition, entry in zip(catalog.definitions, entries, strict=True)
    }
    existing = None
    shadowed_by: dict[str, str] | None = None
    if override_name is None:
        existing = ExistingRowSpec(
            count=_existing_macro_count(catalog),
            switching=switching,
        )
    else:
        shadowed_by = {}
        for row in rows:
            winner = macro_redefinition(catalog, override_name, row).winner_after_save
            if winner:
                shadowed_by[row.location.path] = winner
    choices, _default_id = macro_location_choices(
        rows,
        last_used_path=last_used_path,
        current_path=current_path,
        home_mode=home_mode,
        project=project,
        name=name,
        existing=existing,
        override_name=override_name,
        shadowed_by=shadowed_by,
    )
    return _PickerPayload(choices, entries, definitions_by_entry_id)


def _existing_macro_count(catalog: MiniMacroTargetCatalog) -> int:
    return len(
        {
            definition.name
            for definition in catalog.definitions
            if definition.workflow_kind == "macro"
        }
    )


def _mini_macro_picker_title(
    initial_name: str, current_location_path: str | None
) -> str:
    """Return the picker title for a new mini-macro or a retarget."""
    if current_location_path and initial_name:
        return f"Retarget #{initial_name} · where should it live?"
    return "New mini-macro · where should it live?"


def _load_unified_save_rows(
    project: str | None,
) -> list[UnifiedSaveLocation]:
    from sase.ace.tui.modals.unified_macro_save_support import (
        load_unified_save_locations,
    )

    return load_unified_save_locations(project)


def _load_mini_macro_catalog(
    project: str | None,
    rows: Sequence[UnifiedSaveLocation],
) -> MiniMacroTargetCatalog:
    from sase.ace.tui.modals.mini_macro_target_catalog import (
        load_mini_macro_target_catalog,
    )

    return load_mini_macro_target_catalog(project, locations=rows)


def _load_last_used_locations() -> dict[SaveKind, str]:
    from sase.macro.save_state import load_last_used_locations

    return load_last_used_locations()


__all__ = ["MiniMacroLocationFlow"]
