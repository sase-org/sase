"""Snippet target pane request handling for the prompt bar."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ._types import PromptContext

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from sase.ace.tui.modals.snippet_name_modal import SnippetNameResult
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint
    from sase.xprompt.snippet_targets import SnippetConfigLocation, SnippetSaveTarget


class PromptBarSnippetPaneMixin:
    """Open the snippet-name modal and apply its result to the prompt bar."""

    _prompt_context: PromptContext | None
    _snippet_config_path: str

    async def on_prompt_input_bar_snippet_target_requested(
        self,
        event: object,
    ) -> None:
        """Handle ``gt`` / ``Ctrl+G t`` snippet target requests."""
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
        try:
            target, locations, derived = await asyncio.gather(
                asyncio.to_thread(
                    _resolve_snippet_target,
                    self._snippet_config_path,
                ),
                asyncio.to_thread(_load_snippet_locations, project),
                asyncio.to_thread(_load_derived_snippet_catalog, project),
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to prepare snippet pane: {exc}",
                severity="error",
            )
            return

        if not origin_bar.is_mounted or not origin_bar.snippet_target_origin_available(
            event.origin_pane_id
        ):
            self.notify(  # type: ignore[attr-defined]
                "Prompt pane is no longer available - snippet discarded",
                severity="warning",
            )
            return

        from ...modals import SnippetNameModal

        derived_snippets, derived_sources = derived

        def _on_result(result: SnippetNameResult | None) -> None:
            if result is None:
                origin_bar.refocus_pane_id(event.origin_pane_id)
                return
            self._spawn_snippet_pane_task(
                self._apply_snippet_name_result(
                    origin_bar,
                    event.origin_pane_id,
                    result,
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            SnippetNameModal(
                target,
                locations,
                derived_snippets=derived_snippets,
                derived_sources=derived_sources,
                initial_trigger=event.initial_trigger,
            ),
            _on_result,
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


def _resolve_snippet_target(configured: str) -> SnippetSaveTarget:
    from sase.xprompt.snippet_targets import resolve_snippet_save_target

    return resolve_snippet_save_target(configured)


def _load_snippet_locations(project: str | None) -> list[SnippetConfigLocation]:
    from sase.xprompt.snippet_targets import load_snippet_config_locations

    return load_snippet_config_locations(project)


def _load_derived_snippet_catalog(
    project: str | None,
) -> tuple[dict[str, str], dict[str, str]]:
    from sase.xprompt.snippet_bridge import get_xprompt_snippet_entries

    snippets: dict[str, str] = {}
    sources: dict[str, str] = {}
    for entry in get_xprompt_snippet_entries(project=project):
        snippets[entry.trigger] = entry.template
        sources[entry.trigger] = f"#{entry.xprompt_name}"
    return snippets, sources


def _snippet_destination_state(
    write_path: str,
    trigger: str,
) -> tuple[bool, SourceFingerprint | None]:
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint
    from sase.xprompt.snippet_targets import load_snippet_template

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
