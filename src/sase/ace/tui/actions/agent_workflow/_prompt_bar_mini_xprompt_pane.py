"""Mini-xprompt target pane request handling for the prompt bar."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._local_xprompt_conversion import infer_local_xprompt_inputs
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat, load_config_xprompt_markdown

from ._types import PromptContext

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from sase.ace.tui.modals.mini_xprompt_name_modal import MiniXPromptNameResult
    from sase.ace.tui.modals.mini_xprompt_target_catalog import (
        MiniXPromptDefinition,
        MiniXPromptTargetCatalog,
    )
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint
    from sase.xprompt.save_state import SaveKind


@dataclass(frozen=True, slots=True)
class _MiniXPromptDefinitionDraft:
    body: str
    frontmatter: str
    markdown: str | None
    fingerprint: SourceFingerprint | None
    destination_exists: bool


class PromptBarMiniXPromptPaneMixin:
    """Open the mini-xprompt name modal and apply its result to the prompt bar."""

    _prompt_context: PromptContext | None

    async def on_prompt_input_bar_mini_xprompt_target_requested(
        self,
        event: object,
    ) -> None:
        """Handle pane-scoped mini-xprompt target requests."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.MiniXPromptTargetRequested):
            return

        origin_bar = event.origin_bar
        if not origin_bar.is_mounted:
            return
        if not origin_bar.mini_xprompt_target_origin_available(event.origin_pane_id):
            self.notify(  # type: ignore[attr-defined]
                "Prompt pane is no longer available - mini-xprompt discarded",
                severity="warning",
            )
            return

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            and not self._prompt_context.is_home_mode
            else None
        )
        try:
            catalog, last_used = await asyncio.gather(
                asyncio.to_thread(_load_mini_xprompt_catalog, project),
                asyncio.to_thread(_load_last_used_locations),
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to prepare mini-xprompt pane: {exc}",
                severity="error",
            )
            return

        if (
            not origin_bar.is_mounted
            or not origin_bar.mini_xprompt_target_origin_available(event.origin_pane_id)
        ):
            self.notify(  # type: ignore[attr-defined]
                "Prompt pane is no longer available - mini-xprompt discarded",
                severity="warning",
            )
            return

        from ...modals import MiniXPromptNameModal

        def _on_result(result: MiniXPromptNameResult | None) -> None:
            if result is None:
                origin_bar.refocus_pane_id(event.origin_pane_id)
                return
            self._spawn_mini_xprompt_pane_task(
                self._apply_mini_xprompt_name_result(
                    origin_bar,
                    event.origin_pane_id,
                    result,
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            MiniXPromptNameModal(
                catalog,
                initial_name=event.initial_name,
                last_used_path=last_used.get("xprompt"),
            ),
            _on_result,
        )

    async def on_prompt_input_bar_mini_xprompt_pane_save_requested(
        self,
        event: object,
    ) -> None:
        """Accept mini save-review requests until the persistence phase handles them."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.MiniXPromptPaneSaveRequested):
            return
        self.notify(  # type: ignore[attr-defined]
            "Mini-xprompt save review is not wired yet",
            severity="warning",
        )

    async def _apply_mini_xprompt_name_result(
        self,
        origin_bar: PromptInputBar,
        origin_pane_id: str,
        result: MiniXPromptNameResult,
    ) -> None:
        """Apply a mini-name result after off-thread definition reads."""
        try:
            draft = await asyncio.to_thread(
                _load_mini_xprompt_definition_draft,
                result,
                _origin_body_for_new_target(origin_bar, origin_pane_id),
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to open mini-xprompt: {exc}",
                severity="error",
            )
            return
        if not origin_bar.is_mounted:
            return
        opened = origin_bar.open_mini_xprompt_target_pane(
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
                "Prompt pane is no longer available - mini-xprompt discarded",
                severity="warning",
            )

    def _spawn_mini_xprompt_pane_task(
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
        tasks = getattr(self, "_mini_xprompt_pane_async_tasks", None)
        if tasks is None:
            tasks = set()
            self._mini_xprompt_pane_async_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)


def _load_mini_xprompt_catalog(project: str | None) -> MiniXPromptTargetCatalog:
    from sase.ace.tui.modals.mini_xprompt_target_catalog import (
        load_mini_xprompt_target_catalog,
    )

    return load_mini_xprompt_target_catalog(project)


def _load_last_used_locations() -> dict[SaveKind, str]:
    from sase.xprompt.save_state import load_last_used_locations

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


def _load_mini_xprompt_definition_draft(
    result: MiniXPromptNameResult,
    origin_body: str,
) -> _MiniXPromptDefinitionDraft:
    definition = _definition_to_load(result)
    destination_fingerprint = _fingerprint_for_path(result.destination.write_path)
    if definition is None:
        conversion = infer_local_xprompt_inputs(origin_body)
        if conversion is None:
            raise ValueError("origin pane has invalid Jinja")
        frontmatter = PromptFrontmatter(inputs=conversion.inputs).serialize()
        return _MiniXPromptDefinitionDraft(
            body=conversion.body,
            frontmatter=frontmatter,
            markdown=None,
            fingerprint=destination_fingerprint,
            destination_exists=result.destination.exists_here,
        )

    markdown = _load_definition_markdown(definition)
    from sase.ace.tui.widgets.prompt_stack import split_frontmatter

    frontmatter, body = split_frontmatter(markdown)
    return _MiniXPromptDefinitionDraft(
        body=body,
        frontmatter=frontmatter,
        markdown=markdown,
        fingerprint=destination_fingerprint,
        destination_exists=result.destination.exists_here,
    )


def _definition_to_load(
    result: MiniXPromptNameResult,
) -> MiniXPromptDefinition | None:
    if result.action == "create":
        return None
    if result.action == "edit":
        return result.definition or result.existing_definition
    return result.existing_definition


def _load_definition_markdown(definition: MiniXPromptDefinition) -> str:
    source_path = definition.read_path or definition.source_path
    if not source_path:
        raise FileNotFoundError("Definition source is unavailable")
    if definition.storage_format is SaveTargetFormat.CONFIG:
        if not definition.entry_name:
            raise ValueError("config-backed xprompt is missing an entry name")
        return load_config_xprompt_markdown(source_path, definition.entry_name)
    return Path(source_path).read_text(encoding="utf-8")


def _fingerprint_for_path(path: str) -> SourceFingerprint | None:
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint

    try:
        return SourceFingerprint.from_path(path)
    except OSError:
        return None


__all__ = ["PromptBarMiniXPromptPaneMixin"]
