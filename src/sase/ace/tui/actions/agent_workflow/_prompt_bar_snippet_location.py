"""Location-first snippet flow: picker, existing finder, and override."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ._prompt_bar_snippet_location_data import (
    build_snippet_picker_payload as _picker_payload,
    load_snippet_flow_catalog as _load_snippet_catalog,
    load_snippet_flow_last_used as _load_snippet_last_used_path,
    load_snippet_flow_locations as _load_snippet_locations,
    load_snippet_flow_names as _load_snippet_names_by_path,
    resolve_snippet_flow_target as _resolve_snippet_target,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals.existing_definition_entries import ExistingDefinitionEntry
    from sase.ace.tui.modals.existing_definition_finder_modal import (
        ExistingDefinitionPick,
        ExistingFinderBack,
    )
    from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
    from sase.ace.tui.modals.snippet_name_modal import SnippetNameResult
    from sase.ace.tui.widgets import PromptInputBar
    from sase.macro.snippet_targets import SnippetConfigLocation, SnippetSaveTarget
    from sase.snippet.models import SnippetCatalog
    from sase.snippet.redefinition import SnippetDefinitionSite


_ORIGIN_LOST = "Prompt pane is no longer available - snippet discarded"


class SnippetLocationFlow:
    """One location-first snippet request, picker first then name step."""

    def __init__(
        self,
        *,
        host: Any,
        origin_bar: PromptInputBar,
        origin_pane_id: str,
        initial_trigger: str,
        current_location_path: str | None,
        project: str | None,
        configured: str,
    ) -> None:
        self._host = host
        self._origin_bar = origin_bar
        self._origin_pane_id = origin_pane_id
        self._initial_trigger = initial_trigger
        self._current_location_path = current_location_path
        self._project = project
        self._configured = configured
        self._picker: SaveLocationPickerModal | None = None
        self._picker_open = False
        self._origin_lost = False
        self._loaded_target: SnippetSaveTarget | None = None
        self._loaded_locations: list[SnippetConfigLocation] = []
        self._loaded_catalog: SnippetCatalog | None = None
        self._targets_by_choice: dict[str, SnippetSaveTarget] = {}
        self._in_use_choice_id: str | None = None
        self._entries: tuple[ExistingDefinitionEntry, ...] = ()
        self._sites_by_entry_id: dict[str, SnippetDefinitionSite] = {}
        self._finder_query: str | None = None
        self._override_name: str | None = None

    @staticmethod
    def picker_title(trigger: str) -> str:
        """Return the picker title for a new snippet or a rename."""
        if trigger:
            return f"Rename ⇥ {trigger} · where should it live?"
        return "New snippet · where should it live?"

    def start(self) -> None:
        """Push the picker synchronously and load destinations in the background."""
        self._push_normal_picker(highlight_id=None)

    def attach_picker(self, picker: SaveLocationPickerModal) -> None:
        """Bind a freshly pushed picker as the live stage of this flow."""
        self._picker = picker
        self._picker_open = True

    def _snippet_pane_is_open(self) -> bool:
        return bool(
            self._origin_bar.is_mounted
            and self._origin_bar._stack.snippet_item is not None
        )

    def _is_live_picker(self, picker: SaveLocationPickerModal | None) -> bool:
        """Return True when *picker* is still the flow's active stage."""
        return picker is not None and self._picker is picker and self._picker_open

    def _dismiss_for_origin_loss(self, picker: SaveLocationPickerModal | None) -> None:
        """Close the active picker after the origin disappears.

        The origin-lost warning is issued exactly once: through the picker
        dismissal callback when the dismiss lands, or directly when there is
        no mounted picker to dismiss (so no callback will fire).
        """
        self._origin_lost = True
        if not self._is_live_picker(picker):
            return
        assert picker is not None
        try:
            if picker.is_mounted:
                picker.dismiss(None)
                return
        except Exception:
            pass
        self._picker_open = False
        self._host.notify(_ORIGIN_LOST, severity="warning")  # type: ignore[attr-defined]

    def _fail_picker_load(
        self, picker: SaveLocationPickerModal | None, exc: BaseException
    ) -> None:
        """Show a recoverable load error on the live picker and notify."""
        if not self._is_live_picker(picker):
            return
        assert picker is not None
        try:
            picker.set_load_error(f"Failed to prepare snippet pane: {exc}")
        except Exception:
            pass
        self._host.notify(  # type: ignore[attr-defined]
            f"Failed to prepare snippet pane: {exc}",
            severity="error",
        )

    def _push_normal_picker(self, *, highlight_id: str | None) -> None:
        from ...modals.save_location_picker_modal import SaveLocationPickerModal

        self._override_name = None
        picker = SaveLocationPickerModal(
            kind="snippet",
            title=self.picker_title(self._initial_trigger),
        )
        self.attach_picker(picker)
        self._host.push_screen(picker, self.on_picker_result)  # type: ignore[attr-defined]
        self._host._spawn_snippet_pane_task(
            self.load_and_deliver(self._initial_trigger, highlight_id=highlight_id)
        )

    async def load_and_deliver(
        self,
        trigger_text: str,
        *,
        highlight_id: str | None = None,
    ) -> None:
        """Load destinations off-thread, then feed them to the live picker."""
        picker = self._picker
        switching = self._snippet_pane_is_open()
        try:
            target, locations, catalog, last_used, names = await asyncio.gather(
                asyncio.to_thread(_resolve_snippet_target, self._configured),
                asyncio.to_thread(_load_snippet_locations, self._project),
                asyncio.to_thread(_load_snippet_catalog, self._project),
                asyncio.to_thread(_load_snippet_last_used_path),
                asyncio.to_thread(
                    _load_snippet_names_by_path,
                    self._project,
                    self._configured,
                ),
            )
        except Exception as exc:
            if not self._is_live_picker(picker):
                return
            if not self._origin_available():
                self._dismiss_for_origin_loss(picker)
                return
            self._fail_picker_load(picker, exc)
            return
        if not self._is_live_picker(picker):
            return
        if not self._origin_available():
            self._dismiss_for_origin_loss(picker)
            return
        self._loaded_target = target
        self._loaded_locations = list(locations)
        self._loaded_catalog = catalog
        await self._deliver_payload(
            picker,
            trigger_text,
            names,
            last_used,
            switching=switching,
            highlight_id=highlight_id,
        )

    async def redeliver_for_name(
        self,
        text: str,
        *,
        highlight_id: str | None = None,
    ) -> None:
        """Rebuild picker choices for the typed name after a ⇧Tab round trip."""
        picker = self._picker
        if self._loaded_target is None or not self._is_live_picker(picker):
            return
        highlight = self._in_use_choice_id if highlight_id is None else highlight_id
        try:
            names = await asyncio.to_thread(
                _load_snippet_names_by_path,
                self._project,
                self._configured,
            )
            if not self._is_live_picker(picker):
                return
            if not self._origin_available():
                self._dismiss_for_origin_loss(picker)
                return
            last_used = await asyncio.to_thread(_load_snippet_last_used_path)
            if not self._is_live_picker(picker):
                return
            if not self._origin_available():
                self._dismiss_for_origin_loss(picker)
                return
        except Exception as exc:
            if not self._is_live_picker(picker):
                return
            if not self._origin_available():
                self._dismiss_for_origin_loss(picker)
                return
            self._fail_picker_load(picker, exc)
            return
        await self._deliver_payload(
            picker,
            text,
            names,
            last_used,
            switching=self._snippet_pane_is_open(),
            highlight_id=highlight,
        )

    async def _deliver_payload(
        self,
        picker: SaveLocationPickerModal | None,
        trigger_text: str,
        names: dict[str, frozenset[str]],
        last_used: str | None,
        *,
        switching: bool,
        highlight_id: str | None,
    ) -> None:
        if self._loaded_target is None:
            return
        try:
            payload = await asyncio.to_thread(
                _picker_payload,
                tuple(self._loaded_locations),
                self._loaded_target,
                names,
                last_used,
                self._current_location_path,
                self._project,
                trigger_text,
                self._loaded_catalog,
                switching,
                self._override_name,
            )
        except Exception as exc:
            if not self._is_live_picker(picker):
                return
            if not self._origin_available():
                self._dismiss_for_origin_loss(picker)
                return
            self._fail_picker_load(picker, exc)
            return
        if not self._is_live_picker(picker):
            return
        if not self._origin_available():
            self._dismiss_for_origin_loss(picker)
            return
        assert picker is not None
        self._targets_by_choice = payload.targets
        self._entries = payload.entries
        self._sites_by_entry_id = payload.sites_by_entry_id
        target = self._loaded_target
        if target.fallback_reason:
            picker.set_notice(
                f"{self._configured} unusable: {target.fallback_reason}"
                f" — using {target.display_path}"
            )
        picker.set_choices(payload.choices, highlight_id=highlight_id)

    def on_picker_result(self, result: object) -> None:
        """Handle one picker dismissal: pick, cancel, or a stale callback."""
        from ...modals.save_location_choices import EXISTING_CHOICE_ID, SaveLocationPick

        self._picker_open = False
        if result is None:
            if self._origin_lost or not self._origin_available():
                self._host.notify(  # type: ignore[attr-defined]
                    _ORIGIN_LOST,
                    severity="warning",
                )
                return
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if not isinstance(result, SaveLocationPick):
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if not self._origin_available():
            self._host.notify(_ORIGIN_LOST, severity="warning")  # type: ignore[attr-defined]
            return
        if result.choice_id == EXISTING_CHOICE_ID:
            query = (
                self._finder_query
                if self._finder_query is not None
                else (result.typeahead or "")
            )
            self._open_existing_finder(query)
            return
        if self._loaded_target is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        target = self._targets_by_choice.get(result.choice_id)
        if target is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        self._in_use_choice_id = result.choice_id
        self._current_location_path = str(target.write_path)
        seed = (
            self._override_name
            if self._override_name is not None
            else self._initial_trigger
        )
        self._open_name_step(target, seed + result.typeahead)

    def _open_existing_finder(self, query: str) -> None:
        from ...modals.existing_definition_finder_modal import (
            ExistingDefinitionFinderModal,
        )

        self._host.push_screen(  # type: ignore[attr-defined]
            ExistingDefinitionFinderModal(
                "snippet",
                self._entries,
                initial_query=query,
            ),
            self._on_finder_result,
        )

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
            self._host.notify(_ORIGIN_LOST, severity="warning")  # type: ignore[attr-defined]
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
        site = self._sites_by_entry_id.get(result.entry_id)
        entry = next(
            (item for item in self._entries if item.entry_id == result.entry_id),
            None,
        )
        if site is None or entry is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if entry.status == "read_only":
            self._open_override_picker(site.trigger)
            return
        name_result = self._name_result_for_site(site)
        if name_result is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        self._apply_existing_result(
            name_result, replace_draft=self._snippet_pane_is_open()
        )

    def _name_result_for_site(
        self, site: SnippetDefinitionSite
    ) -> SnippetNameResult | None:
        from ...modals.snippet_name_modal import SnippetNameResult
        from sase.snippet.redefinition import (
            snippet_redefinition,
            snippet_redefinition_warning,
        )

        catalog = self._loaded_catalog
        target = self._target_for_site(site)
        if catalog is None or target is None:
            return None
        redef = snippet_redefinition(
            catalog,
            site.trigger,
            str(target.write_path),
            locations=self._loaded_locations,
        )
        return SnippetNameResult(
            trigger=site.trigger,
            target=target,
            exists=True,
            existing_body=site.template,
            derived_from=None,
            save_warning=snippet_redefinition_warning(redef, target.display_path),
        )

    def _target_for_site(self, site: SnippetDefinitionSite) -> SnippetSaveTarget | None:
        from sase.macro.snippet_targets import (
            SnippetConfigLocation,
            snippet_save_target_for_location,
        )
        from sase.snippet.redefinition import paths_equivalent

        if not site.path:
            return None
        for location in self._loaded_locations:
            if paths_equivalent(location.path, site.path):
                return snippet_save_target_for_location(location)
        loaded = self._loaded_target
        if loaded is not None and (
            paths_equivalent(site.path, str(loaded.write_path))
            or paths_equivalent(site.path, str(loaded.read_path))
        ):
            return loaded
        return snippet_save_target_for_location(
            SnippetConfigLocation(
                label=site.display,
                path=site.path,
                display_path=site.display,
            )
        )

    def _already_editing(self, result: SnippetNameResult) -> bool:
        bar = self._origin_bar
        if not bar.is_mounted:
            return False
        bar._sync_state_from_widgets()
        snippet = bar._stack.snippet_item
        if snippet is None or snippet.snippet_target is None:
            return False
        target = snippet.snippet_target
        return (
            target.write_path == str(result.target.write_path)
            and target.trigger == result.trigger
        )

    def _focus_already_editing(self, trigger: str) -> None:
        bar = self._origin_bar
        index = bar._stack.snippet_index
        if index is not None:
            bar.focus_item(index)
        self._host.notify(f"Already editing ⇥ {trigger}")  # type: ignore[attr-defined]

    def _apply_existing_result(
        self,
        result: SnippetNameResult,
        *,
        replace_draft: bool,
    ) -> None:
        if not self._origin_available():
            self._host.notify(_ORIGIN_LOST, severity="warning")  # type: ignore[attr-defined]
            return
        if self._already_editing(result):
            self._focus_already_editing(result.trigger)
            return

        def proceed() -> None:
            self._host._spawn_snippet_pane_task(
                self._host._apply_snippet_name_result(
                    self._origin_bar,
                    self._origin_pane_id,
                    result,
                    replace_draft=replace_draft,
                )
            )

        if replace_draft and self._snippet_pane_is_open():
            self._origin_bar.confirm_discard_dirty_auxiliary(proceed)
            return
        proceed()

    def _open_override_picker(
        self,
        trigger: str,
        *,
        highlight_id: str | None = None,
        seed_trigger: str | None = None,
    ) -> None:
        from ...modals.save_location_picker_modal import SaveLocationPickerModal

        self._override_name = trigger
        self._initial_trigger = trigger if seed_trigger is None else seed_trigger
        if highlight_id is not None:
            self._in_use_choice_id = highlight_id
        picker = SaveLocationPickerModal(
            kind="snippet",
            title=f"Override ⇥ {trigger} · where should it live?",
        )
        self.attach_picker(picker)
        self._host.push_screen(picker, self.on_picker_result)  # type: ignore[attr-defined]
        if self._loaded_target is None:
            self._host._spawn_snippet_pane_task(
                self.load_and_deliver(self._initial_trigger, highlight_id=highlight_id)
            )
            return
        self._host._spawn_snippet_pane_task(
            self.redeliver_for_name(self._initial_trigger, highlight_id=highlight_id)
        )

    def _open_name_step(self, target: SnippetSaveTarget, initial_trigger: str) -> None:
        from ...modals import SnippetNameModal

        self._host.push_screen(  # type: ignore[attr-defined]
            SnippetNameModal(
                target,
                self._loaded_locations,
                catalog=self._loaded_catalog,
                initial_trigger=initial_trigger,
            ),
            lambda name_result: self.on_name_result(name_result, target),
        )

    def on_name_result(
        self,
        result: object,
        target: SnippetSaveTarget | None = None,
    ) -> None:
        """Handle one name-step dismissal: save, ⇧Tab back, or cancel."""
        from ...modals.save_location_choices import ChangeSaveLocationRequest
        from ...modals.save_location_picker_modal import SaveLocationPickerModal
        from ...modals.snippet_name_modal import SnippetNameResult

        if result is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if isinstance(result, ChangeSaveLocationRequest):
            self._initial_trigger = result.text
            if self._override_name is not None:
                highlight = str(target.write_path) if target is not None else None
                self._open_override_picker(
                    self._override_name,
                    highlight_id=highlight,
                    seed_trigger=result.text,
                )
                return
            picker = SaveLocationPickerModal(
                kind="snippet",
                title=self.picker_title(result.text),
            )
            self.attach_picker(picker)
            self._host.push_screen(picker, self.on_picker_result)  # type: ignore[attr-defined]
            self._host._spawn_snippet_pane_task(self.redeliver_for_name(result.text))
            return
        if not isinstance(result, SnippetNameResult):
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if self._override_name is not None:
            self._apply_existing_result(result, replace_draft=True)
            return
        self._host._spawn_snippet_pane_task(
            self._host._apply_snippet_name_result(
                self._origin_bar,
                self._origin_pane_id,
                result,
            )
        )

    def _origin_available(self) -> bool:
        try:
            return bool(
                self._origin_bar.is_mounted
                and self._origin_bar.snippet_target_origin_available(
                    self._origin_pane_id
                )
            )
        except Exception:
            return False


__all__ = ["SnippetLocationFlow"]
