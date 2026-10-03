"""Snippet target pane request handling for the prompt bar."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ._types import PromptContext

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from sase.ace.tui.modals.save_location_choices import SaveLocationChoice
    from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
    from sase.ace.tui.modals.snippet_name_modal import SnippetNameResult
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint
    from sase.macro.snippet_targets import SnippetConfigLocation, SnippetSaveTarget


class PromptBarSnippetPaneMixin:
    """Open the snippet-name modal and apply its result to the prompt bar."""

    _prompt_context: PromptContext | None
    _snippet_config_path: str

    async def on_prompt_input_bar_snippet_target_requested(
        self,
        event: object,
    ) -> None:
        """Handle ``gt`` / ``Ctrl+G t`` / ``Ctrl+G Ctrl+T`` snippet requests."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SnippetTargetRequested):
            return

        origin_bar = event.origin_bar
        if not origin_bar.is_mounted:
            return
        if not origin_bar.snippet_target_origin_available(event.origin_pane_id):
            self.notify(  # type: ignore[attr-defined]
                "Prompt pane is no longer available - snippet discarded",
                severity="warning",
            )
            return

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            and not self._prompt_context.is_home_mode
            else None
        )
        from ...modals.save_location_picker_modal import SaveLocationPickerModal

        flow = _SnippetLocationFlow(
            host=self,
            origin_bar=origin_bar,
            origin_pane_id=event.origin_pane_id,
            initial_trigger=event.initial_trigger,
            current_location_path=getattr(event, "current_location_path", None),
            project=project,
            configured=self._snippet_config_path,
        )
        picker = SaveLocationPickerModal(
            kind="snippet",
            title=flow.picker_title(event.initial_trigger),
        )
        flow.attach_picker(picker)

        def _on_picker_result(result: object) -> None:
            flow.on_picker_result(result)

        # Pushed synchronously, before any await: keystrokes typed while the
        # loaders run land in the picker (or its type-ahead), never in the
        # prompt pane.
        self.push_screen(  # type: ignore[attr-defined]
            picker,
            _on_picker_result,
        )
        self._spawn_snippet_pane_task(
            flow.load_and_deliver(event.initial_trigger),
        )

    async def _apply_snippet_name_result(
        self,
        origin_bar: PromptInputBar,
        origin_pane_id: str,
        result: SnippetNameResult,
    ) -> None:
        """Apply a modal result after off-thread fingerprint/existence checks."""
        destination_exists, loaded_fingerprint = await asyncio.to_thread(
            _snippet_destination_state,
            str(result.target.write_path),
            result.trigger,
        )
        if not origin_bar.is_mounted:
            return
        opened = origin_bar.open_snippet_target_pane(
            result,
            origin_pane_id=origin_pane_id,
            destination_exists=destination_exists,
            loaded_fingerprint=loaded_fingerprint,
        )
        if not opened:
            self.notify(  # type: ignore[attr-defined]
                "Prompt pane is no longer available - snippet discarded",
                severity="warning",
            )

    def _spawn_snippet_pane_task(
        self,
        coro: Coroutine[object, object, None],
    ) -> None:
        """Run a snippet-pane coroutine, holding a reference until completion."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        task = loop.create_task(coro)
        tasks = getattr(self, "_snippet_pane_async_tasks", None)
        if tasks is None:
            tasks = set()
            self._snippet_pane_async_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)


class _SnippetLocationFlow:
    """Location-first orchestration for one snippet target request."""

    def __init__(
        self,
        *,
        host: PromptBarSnippetPaneMixin,
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
        self._loaded_snippets: dict[str, str] = {}
        self._loaded_sources: dict[str, str] = {}
        self._targets_by_choice: dict[str, SnippetSaveTarget] = {}
        self._in_use_choice_id: str | None = None

    @staticmethod
    def picker_title(trigger: str) -> str:
        """Return the picker title for a new snippet or a rename."""
        if trigger:
            return f"Rename ⇥ {trigger} · where should it live?"
        return "New snippet · where should it live?"

    def attach_picker(self, picker: SaveLocationPickerModal) -> None:
        """Bind a freshly pushed picker as the live stage of this flow."""
        self._picker = picker
        self._picker_open = True

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
        self._host.notify(  # type: ignore[attr-defined]
            "Prompt pane is no longer available - snippet discarded",
            severity="warning",
        )

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

    async def load_and_deliver(self, trigger_text: str) -> None:
        """Load destinations off-thread, then feed them to the live picker."""
        picker = self._picker
        try:
            target, locations, derived, last_used, names = await asyncio.gather(
                asyncio.to_thread(_resolve_snippet_target, self._configured),
                asyncio.to_thread(_load_snippet_locations, self._project),
                asyncio.to_thread(_load_derived_snippet_catalog, self._project),
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
        derived_snippets, derived_sources = derived
        self._loaded_target = target
        self._loaded_locations = list(locations)
        self._loaded_snippets = dict(derived_snippets)
        self._loaded_sources = dict(derived_sources)
        try:
            choices, targets = await asyncio.to_thread(
                _build_snippet_picker_tables,
                tuple(locations),
                target,
                names,
                last_used,
                self._current_location_path,
                self._project,
                trigger_text,
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
        self._targets_by_choice = targets
        if target.fallback_reason:
            picker.set_notice(
                f"{self._configured} unusable: {target.fallback_reason}"
                f" — using {target.display_path}"
            )
        picker.set_choices(choices)

    async def redeliver_for_name(self, text: str) -> None:
        """Rebuild picker choices for the typed name after a ⇧Tab round trip."""
        picker = self._picker
        if self._loaded_target is None or not self._is_live_picker(picker):
            return
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
            choices, targets = await asyncio.to_thread(
                _build_snippet_picker_tables,
                tuple(self._loaded_locations),
                self._loaded_target,
                names,
                last_used,
                self._current_location_path,
                self._project,
                text,
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
        self._targets_by_choice = targets
        picker.set_choices(choices, highlight_id=self._in_use_choice_id)

    def on_picker_result(self, result: object) -> None:
        """Handle one picker dismissal: pick, cancel, or a stale callback."""
        from ...modals.save_location_choices import SaveLocationPick

        picker = self._picker
        self._picker_open = False
        if result is None:
            if self._origin_lost or not self._origin_available():
                self._host.notify(  # type: ignore[attr-defined]
                    "Prompt pane is no longer available - snippet discarded",
                    severity="warning",
                )
                return
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if not isinstance(result, SaveLocationPick):
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if (
            self._loaded_target is None
            or not self._origin_available()
            or picker is None
        ):
            if not self._origin_available():
                self._host.notify(  # type: ignore[attr-defined]
                    "Prompt pane is no longer available - snippet discarded",
                    severity="warning",
                )
            else:
                self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        target = self._targets_by_choice.get(result.choice_id)
        if target is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        self._in_use_choice_id = result.choice_id
        self._current_location_path = str(target.write_path)
        initial_trigger = self._initial_trigger + result.typeahead

        from ...modals import SnippetNameModal

        # Pushed synchronously: no await separates the pick from the name
        # step, so later keystrokes reach the name input, not the prompt pane.
        def _on_name_result(name_result: object) -> None:
            self.on_name_result(name_result)

        self._host.push_screen(  # type: ignore[attr-defined]
            SnippetNameModal(
                target,
                self._loaded_locations,
                derived_snippets=self._loaded_snippets,
                derived_sources=self._loaded_sources,
                initial_trigger=initial_trigger,
            ),
            _on_name_result,
        )

    def on_name_result(self, result: object) -> None:
        """Handle one name-step dismissal: save, ⇧Tab back, or cancel."""
        from ...modals.save_location_choices import ChangeSaveLocationRequest
        from ...modals.snippet_name_modal import SnippetNameResult

        if result is None:
            self._origin_bar.refocus_pane_id(self._origin_pane_id)
            return
        if not isinstance(result, SnippetNameResult):
            if isinstance(result, ChangeSaveLocationRequest):
                from ...modals.save_location_picker_modal import (
                    SaveLocationPickerModal,
                )

                self._initial_trigger = result.text
                picker = SaveLocationPickerModal(
                    kind="snippet",
                    title=self.picker_title(result.text),
                )
                self.attach_picker(picker)

                def _on_picker_result(pick: object) -> None:
                    self.on_picker_result(pick)

                self._host.push_screen(  # type: ignore[attr-defined]
                    picker,
                    _on_picker_result,
                )
                self._host._spawn_snippet_pane_task(
                    self.redeliver_for_name(result.text),
                )
            else:
                self._origin_bar.refocus_pane_id(self._origin_pane_id)
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


def _build_snippet_picker_tables(
    locations: tuple[SnippetConfigLocation, ...],
    resolved_target: SnippetSaveTarget,
    names_by_path: dict[str, frozenset[str]],
    last_used_path: str | None,
    current_path: str | None,
    project: str | None,
    trigger: str,
) -> tuple[tuple[SaveLocationChoice, ...], dict[str, SnippetSaveTarget]]:
    """Build picker choices plus the choice-id → save-target map off-thread."""
    from sase.ace.tui.modals.save_location_choices import (
        SNIPPET_CONFIGURED_SECTION,
        snippet_location_choices,
    )
    from sase.macro.snippet_targets import snippet_save_target_for_location

    choices, _default_id = snippet_location_choices(
        locations,
        resolved_target=resolved_target,
        names_by_path=names_by_path,
        last_used_path=last_used_path,
        current_path=current_path,
        project=project,
        trigger=trigger,
    )
    by_path = {location.path: location for location in locations}
    targets: dict[str, SnippetSaveTarget] = {}
    for choice in choices:
        if choice.section == SNIPPET_CONFIGURED_SECTION:
            targets[choice.choice_id] = resolved_target
            continue
        location = by_path.get(choice.choice_id)
        if location is None:
            targets[choice.choice_id] = resolved_target
        else:
            targets[choice.choice_id] = snippet_save_target_for_location(location)
    return choices, targets


def _resolve_snippet_target(configured: str) -> SnippetSaveTarget:
    from sase.macro.snippet_targets import resolve_snippet_save_target

    return resolve_snippet_save_target(configured)


def _load_snippet_locations(project: str | None) -> list[SnippetConfigLocation]:
    from sase.macro.snippet_targets import load_snippet_config_locations

    return load_snippet_config_locations(project)


def _load_derived_snippet_catalog(
    project: str | None,
) -> tuple[dict[str, str], dict[str, str]]:
    from sase.macro.snippet_bridge import get_xprompt_snippet_entries

    snippets: dict[str, str] = {}
    sources: dict[str, str] = {}
    for entry in get_xprompt_snippet_entries(project=project):
        snippets[entry.trigger] = entry.template
        sources[entry.trigger] = f"#{entry.xprompt_name}"
    return snippets, sources


def _load_snippet_last_used_path() -> str | None:
    from sase.macro.save_state import load_last_used_locations

    return load_last_used_locations().get("snippet")


def _load_snippet_names_by_path(
    project: str | None,
    configured: str,
) -> dict[str, frozenset[str]]:
    from sase.macro.save_index import names_for_location

    locations = _load_snippet_locations(project)
    paths = [location.path for location in locations]
    try:
        configured_target = _resolve_snippet_target(configured)
    except Exception:
        configured_target = None
    if configured_target is not None:
        configured_path = str(configured_target.write_path)
        if configured_path not in paths:
            paths.append(configured_path)
    names: dict[str, frozenset[str]] = {}
    for path in paths:
        try:
            names[path] = names_for_location("snippet_config", path)
        except Exception:
            names[path] = frozenset()
    return names


def _snippet_destination_state(
    write_path: str,
    trigger: str,
) -> tuple[bool, SourceFingerprint | None]:
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint
    from sase.macro.snippet_targets import load_snippet_template

    try:
        load_snippet_template(write_path, trigger)
    except Exception:
        destination_exists = False
    else:
        destination_exists = True

    try:
        fingerprint = SourceFingerprint.from_path(write_path)
    except OSError:
        fingerprint = None
    return destination_exists, fingerprint


__all__ = ["PromptBarSnippetPaneMixin"]
