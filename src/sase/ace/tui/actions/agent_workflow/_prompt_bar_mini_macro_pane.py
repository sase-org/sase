"""Mini-macro target pane request handling for the prompt bar."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._local_macro_conversion import (
    infer_local_xprompt_inputs as infer_local_macro_inputs,
)
from sase.macro.prompt_frontmatter import PromptFrontmatter
from sase.macro.save import SaveTargetFormat, load_config_macro_markdown

from ._types import PromptContext

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from sase.ace.tui.modals.mini_macro_name_modal import MiniMacroNameResult
    from sase.ace.tui.modals.mini_macro_target_catalog import MiniMacroDefinition
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint


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

        from ._prompt_bar_mini_macro_location import MiniMacroLocationFlow

        MiniMacroLocationFlow(
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
        *,
        replace_draft: bool = False,
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
            replace_draft=replace_draft,
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
