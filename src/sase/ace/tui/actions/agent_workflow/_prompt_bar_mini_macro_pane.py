"""Mini-macro target pane request handling for the prompt bar."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._local_macro_conversion import (
    infer_local_xprompt_inputs as infer_local_macro_inputs,
)
from sase.macro.prompt_frontmatter import PromptFrontmatter
from sase.macro.save import SaveTargetFormat, load_config_macro_markdown

from ._types import PromptContext

if TYPE_CHECKING:
    from collections.abc import Coroutine, Sequence

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
    from sase.ace.tui.modals.save_location_picker_modal import (
        SaveLocationPickerModal,
    )
    from sase.ace.tui.modals.unified_macro_save_support import UnifiedSaveLocation
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint
    from sase.macro.save_state import SaveKind


@dataclass(frozen=True, slots=True)
class _MiniMacroDefinitionDraft:
    body: str
    frontmatter: str
    markdown: str | None
    fingerprint: SourceFingerprint | None
    destination_exists: bool


class PromptBarMiniMacroPaneMixin:
    """Open the mini-macro name modal and apply its result to the prompt bar."""

    _prompt_context: PromptContext | None

    async def on_prompt_input_bar_mini_macro_target_requested(
        self,
        event: object,
    ) -> None:
        """Handle pane-scoped mini-macro target requests location-first."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.MiniMacroTargetRequested):
            return

        origin_bar = event.origin_bar
        if not origin_bar.is_mounted:
            return
        if not origin_bar.mini_macro_target_origin_available(event.origin_pane_id):
            self.notify(  # type: ignore[attr-defined]
                "Prompt pane is no longer available - mini-macro discarded",
                severity="warning",
            )
            return

        _MiniMacroLocationFlow(
            self,
            origin_bar=origin_bar,
            origin_pane_id=event.origin_pane_id,
            initial_name=event.initial_name,
            current_location_path=event.current_location_path,
        ).start()

    async def on_prompt_input_bar_mini_macro_pane_save_requested(
        self,
        event: object,
    ) -> None:
        """Accept mini save-review requests until the persistence phase handles them."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.MiniMacroPaneSaveRequested):
            return
        self.notify(  # type: ignore[attr-defined]
            "Mini-macro save review is not wired yet",
            severity="warning",
        )

    async def _apply_mini_macro_name_result(
        self,
        origin_bar: PromptInputBar,
        origin_pane_id: str,
        result: MiniMacroNameResult,
    ) -> None:
        """Apply a mini-name result after off-thread definition reads."""
        try:
            draft = await asyncio.to_thread(
                _load_mini_macro_definition_draft,
                result,
                _origin_body_for_new_target(origin_bar, origin_pane_id),
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to open mini-macro: {exc}",
                severity="error",
            )
            return
        if not origin_bar.is_mounted:
            return
        opened = origin_bar.open_mini_macro_target_pane(
            result,
            origin_pane_id=origin_pane_id,
            body=draft.body,
            frontmatter=draft.frontmatter,
            loaded_markdown=draft.markdown,
            loaded_fingerprint=draft.fingerprint,
            destination_exists=draft.destination_exists,
        )
        if not opened:
            self.notify(  # type: ignore[attr-defined]
                "Prompt pane is no longer available - mini-macro discarded",
                severity="warning",
            )

    def _spawn_mini_macro_pane_task(
        self,
        coro: Coroutine[object, object, None],
    ) -> None:
        """Run a mini-pane coroutine, holding a reference until completion."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        task = loop.create_task(coro)
        tasks = getattr(self, "_mini_macro_pane_async_tasks", None)
        if tasks is None:
            tasks = set()
            self._mini_macro_pane_async_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)


class _MiniMacroLocationFlow:
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
        self._settled = False

    def start(self) -> None:
        """Push the picker synchronously and load destinations in the background."""
        from ...modals.save_location_picker_modal import SaveLocationPickerModal

        picker = SaveLocationPickerModal(
            kind="macro",
            title=_mini_macro_picker_title(
                self._seed_base, self._current_location_path
            ),
        )
        self._app.push_screen(picker, self._on_pick)  # type: ignore[attr-defined]
        self._app._spawn_mini_macro_pane_task(
            self._load_and_show(picker, name=self._seed_base, highlight_id=None)
        )

    def _origin_available(self) -> bool:
        return bool(
            self._origin_bar.is_mounted
            and self._origin_bar.mini_macro_target_origin_available(
                self._origin_pane_id
            )
        )

    async def _load_and_show(
        self,
        picker: SaveLocationPickerModal,
        *,
        name: str,
        highlight_id: str | None,
    ) -> None:
        """Load rows, catalog, and choices off-thread, then feed the picker."""
        try:
            rows = await asyncio.to_thread(_load_unified_save_rows, self._project)
            last_used = await asyncio.to_thread(_load_last_used_locations)
            catalog = await asyncio.to_thread(
                _load_mini_macro_catalog, self._project, rows
            )
            choices, _default_id = await asyncio.to_thread(
                _build_mini_macro_picker_choices,
                rows,
                last_used_path=last_used.get("xprompt"),
                current_path=self._current_location_path,
                home_mode=self._home_mode,
                project=self._project,
                name=name,
            )
        except Exception as exc:
            if self._settled:
                return
            if not self._origin_available():
                self._settled = True
                self._app.notify(  # type: ignore[attr-defined]
                    "Prompt pane is no longer available - mini-macro discarded",
                    severity="warning",
                )
                picker.dismiss(None)
                return
            self._app.notify(  # type: ignore[attr-defined]
                f"Failed to prepare mini-macro pane: {exc}",
                severity="error",
            )
            picker.set_load_error(f"Failed to load destinations: {exc}")
            return
        # Stored before set_choices so the dismiss callback, which may run
        # synchronously inside set_choices, can push the name step with no
        # further awaits.
        self._rows = tuple(rows)
        self._catalog = catalog
        if self._settled:
            return
        if not self._origin_available():
            self._settled = True
            self._app.notify(  # type: ignore[attr-defined]
                "Prompt pane is no longer available - mini-macro discarded",
                severity="warning",
            )
            picker.dismiss(None)
            return
        picker.set_choices(choices, highlight_id=highlight_id)

    def _on_pick(self, pick: SaveLocationPick | None) -> None:
        self._settled = True
        if pick is None or self._catalog is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        row = next(
            (item for item in self._rows if item.location.path == pick.choice_id),
            None,
        )
        if row is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        self._open_name_step(row, (self._seed_base or "") + (pick.typeahead or ""))

    def _open_name_step(self, row: UnifiedSaveLocation, raw_text: str) -> None:
        from ...modals import MiniMacroNameModal
        from ...modals.mini_macro_target_catalog import rebase_name_for_destination

        catalog = self._catalog
        assert catalog is not None
        from_row = next(
            (item for item in self._rows if item.location.path == self._seed_from_path),
            None,
        )
        seeded = rebase_name_for_destination(raw_text, row, from_destination=from_row)
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

        if result is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if isinstance(result, ChangeSaveLocationRequest):
            from ...modals.save_location_picker_modal import SaveLocationPickerModal

            self._settled = False
            self._seed_base = result.text
            self._seed_from_path = row.location.path
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
                    name=result.text,
                    highlight_id=row.location.path,
                )
            )
            return
        self._app._spawn_mini_macro_pane_task(
            self._app._apply_mini_macro_name_result(
                self._origin_bar,
                self._origin_pane_id,
                result,
            )
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


def _build_mini_macro_picker_choices(
    rows: Sequence[UnifiedSaveLocation],
    *,
    last_used_path: str | None,
    current_path: str | None,
    home_mode: bool,
    project: str | None,
    name: str,
) -> tuple[tuple[SaveLocationChoice, ...], str | None]:
    from sase.ace.tui.modals.save_location_choices import macro_location_choices

    return macro_location_choices(
        rows,
        last_used_path=last_used_path,
        current_path=current_path,
        home_mode=home_mode,
        project=project,
        name=name,
    )


def _load_last_used_locations() -> dict[SaveKind, str]:
    from sase.macro.save_state import load_last_used_locations

    return load_last_used_locations()


def _origin_body_for_new_target(origin_bar: PromptInputBar, origin_pane_id: str) -> str:
    """Return the origin pane body for a create result without filesystem I/O."""
    if not origin_bar.is_mounted:
        return ""
    origin_bar._sync_state_from_widgets()
    index = origin_bar._item_index_for_pane_id(origin_pane_id)
    if index is None:
        return ""
    item = origin_bar._stack.items[index]
    if item.is_auxiliary_pane:
        return ""
    return item.text.strip()


def _load_mini_macro_definition_draft(
    result: MiniMacroNameResult,
    origin_body: str,
) -> _MiniMacroDefinitionDraft:
    definition = _definition_to_load(result)
    destination_fingerprint = _fingerprint_for_path(result.destination.write_path)
    if definition is None:
        conversion = infer_local_macro_inputs(origin_body)
        if conversion is None:
            raise ValueError("origin pane has invalid Jinja")
        frontmatter = PromptFrontmatter(inputs=conversion.inputs).serialize()
        return _MiniMacroDefinitionDraft(
            body=conversion.body,
            frontmatter=frontmatter,
            markdown=None,
            fingerprint=destination_fingerprint,
            destination_exists=result.destination.exists_here,
        )

    markdown = _load_definition_markdown(definition)
    from sase.ace.tui.widgets.prompt_stack import split_frontmatter

    frontmatter, body = split_frontmatter(markdown)
    return _MiniMacroDefinitionDraft(
        body=body,
        frontmatter=frontmatter,
        markdown=markdown,
        fingerprint=destination_fingerprint,
        destination_exists=result.destination.exists_here,
    )


def _definition_to_load(
    result: MiniMacroNameResult,
) -> MiniMacroDefinition | None:
    if result.action == "create":
        return None
    if result.action == "edit":
        return result.definition or result.existing_definition
    return result.existing_definition


def _load_definition_markdown(definition: MiniMacroDefinition) -> str:
    source_path = definition.read_path or definition.source_path
    if not source_path:
        raise FileNotFoundError("Definition source is unavailable")
    if definition.storage_format is SaveTargetFormat.CONFIG:
        if not definition.entry_name:
            raise ValueError("config-backed macro is missing an entry name")
        return load_config_macro_markdown(source_path, definition.entry_name)
    return Path(source_path).read_text(encoding="utf-8")


def _fingerprint_for_path(path: str) -> SourceFingerprint | None:
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint

    try:
        return SourceFingerprint.from_path(path)
    except OSError:
        return None


__all__ = ["PromptBarMiniMacroPaneMixin"]
