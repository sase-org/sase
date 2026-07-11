"""Save prompt-bar drafts as reusable xprompts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat

from ._prompt_bar_save_xprompt_git import (
    process_error_text,
    run_git_commit_push_sync,
    subprocess as subprocess,
)
from ._prompt_bar_save_xprompt_snippets import (
    PromptBarSaveSnippetMixin,
    existing_snippet_names,
    write_snippet_sync,
)
from ._prompt_bar_save_xprompt_targets import (
    write_target_sync,
    write_binding_sync,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals.unified_xprompt_save_modal import (
        UnifiedXPromptSaveResult,
    )
    from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
        StashedPromptPane,
    )


class PromptBarSaveXpromptMixin(PromptBarSaveSnippetMixin):
    """Handle prompt-bar save-as-xprompt requests."""

    _prompt_context: PromptContext | None
    # Provided by the app's startup/state-init mixins; refreshed after snippet
    # writes so ``get_snippets()`` rebuilds with the new template.
    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None

    async def on_prompt_input_bar_save_as_xprompt_requested(
        self, event: object
    ) -> None:
        """Open the save-as-xprompt target picker for the captured draft."""
        import asyncio

        from ...modals import UnifiedXPromptSaveModal
        from ...modals.unified_xprompt_save_modal import (
            UnifiedXPromptSaveResult,
            load_unified_save_locations,
            load_unified_snippet_locations,
        )
        from ...widgets import PromptInputBar
        from sase.xprompt.save_state import load_last_used_locations

        if not isinstance(event, PromptInputBar.SaveAsXpromptRequested):
            return

        body = self._captured_xprompt_body(event.panes)
        frontmatter = self._captured_xprompt_frontmatter(event.panes)
        origin_bar = event.origin_bar
        if not body.strip() and frontmatter.is_empty:
            self.notify(  # type: ignore[attr-defined]
                "Nothing to save as an xprompt",
                severity="warning",
            )
            return

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )
        locations, snippet_locations, last_used = await asyncio.gather(
            asyncio.to_thread(load_unified_save_locations, project),
            asyncio.to_thread(load_unified_snippet_locations, project),
            asyncio.to_thread(load_last_used_locations),
        )

        non_empty_count = sum(1 for pane in event.panes if pane.text.strip())
        # The snippet save option is always offered. Its source is the active
        # pane captured separately as ``snippet_body``; a legacy/direct event
        # without that field falls back to the xprompt body, but only when a
        # single non-blank pane makes that unambiguous. Snippets are single
        # templates, so the active-pane body never carries ``---`` separators.
        snippet_body = event.snippet_body
        if snippet_body is None:
            snippet_body = body if non_empty_count == 1 else ""
        snippet_body = snippet_body.strip()

        def _on_target(target: UnifiedXPromptSaveResult | None) -> None:
            if target is None:
                return
            if target.mode == "xprompt":
                self._spawn_xprompt_save_task(
                    self._write_xprompt_target(
                        target,
                        body,
                        origin_bar=origin_bar,
                    )
                )
                return
            self._spawn_xprompt_save_task(
                self._write_snippet_target(target, snippet_body)
            )

        self.push_screen(  # type: ignore[attr-defined]
            UnifiedXPromptSaveModal(
                locations,
                snippet_locations=snippet_locations,
                frontmatter=frontmatter,
                body=body,
                snippet_body=snippet_body,
                pane_count=len(event.panes),
                initial_name=(
                    frontmatter.name
                    or (
                        origin_bar._stack.binding.name
                        if origin_bar is not None
                        and origin_bar._stack.binding is not None
                        else ""
                    )
                ),
                last_used=last_used,
            ),
            _on_target,
        )

    async def on_prompt_input_bar_write_xprompt_requested(self, event: object) -> None:
        """Write a bound xprompt, resolving external-change conflicts first."""
        import asyncio

        from ...modals import XPromptWriteConflictModal
        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import SourceFingerprint

        if not isinstance(event, PromptInputBar.WriteXpromptRequested):
            return
        bar = event.origin_bar
        if not bar.is_mounted or bar._stack.binding != event.binding:
            return
        body = self._captured_xprompt_body(event.panes)
        frontmatter = self._captured_xprompt_frontmatter(event.panes)
        try:
            current = await asyncio.to_thread(
                SourceFingerprint.from_path, event.binding.path
            )
        except OSError:
            current = None
        if current != event.binding.loaded_fingerprint:

            def _resolved(choice: str | None) -> None:
                if choice == "overwrite":
                    self._spawn_xprompt_save_task(
                        self._write_bound_xprompt(bar, event.binding, frontmatter, body)
                    )
                elif choice == "reload":
                    self._spawn_xprompt_save_task(
                        self._reload_bound_xprompt(bar, event.binding)
                    )
                elif choice == "save_as":
                    bar.request_save_as_xprompt()

            self.push_screen(  # type: ignore[attr-defined]
                XPromptWriteConflictModal(event.binding.name, event.binding.path),
                _resolved,
            )
            return
        await self._write_bound_xprompt(bar, event.binding, frontmatter, body)

    async def _write_bound_xprompt(
        self,
        bar: object,
        binding: object,
        frontmatter: PromptFrontmatter,
        body: str,
    ) -> None:
        import asyncio

        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import XPromptBinding
        from sase.xprompt.save import save_markdown_document

        if not isinstance(bar, PromptInputBar) or not isinstance(
            binding, XPromptBinding
        ):
            return
        preserved: str | None = None
        try:
            if binding.target_format is SaveTargetFormat.MARKDOWN:
                preserved = bar._stack.markdown_preserving_unchanged_body(frontmatter)
            if preserved is not None:
                await asyncio.to_thread(save_markdown_document, binding.path, preserved)
            else:
                await asyncio.to_thread(write_binding_sync, binding, frontmatter, body)
        except Exception as exc:
            self.notify(f"Failed to write xprompt: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        if bar.is_mounted and bar._stack.binding == binding:
            bar._stack.mark_written(source_markdown=preserved)
            bar._refresh_title()
        self.notify(f"Wrote xprompt '{binding.name}'")  # type: ignore[attr-defined]
        self._offer_git_commit(binding.path, is_new=False, xprompt_name=binding.name)

    async def _reload_bound_xprompt(self, bar: object, binding: object) -> None:
        import asyncio
        from pathlib import Path

        from sase.xprompt.save import load_config_xprompt_markdown

        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import XPromptBinding

        if not isinstance(bar, PromptInputBar) or not isinstance(
            binding, XPromptBinding
        ):
            return
        try:
            if binding.kind == "config" and binding.entry_name:
                markdown = await asyncio.to_thread(
                    load_config_xprompt_markdown, binding.path, binding.entry_name
                )
                refreshed = XPromptBinding.for_config(binding.path, binding.entry_name)
            else:
                markdown = await asyncio.to_thread(
                    Path(binding.path).read_text, encoding="utf-8"
                )
                refreshed = XPromptBinding.for_file(binding.path)
        except Exception as exc:
            self.notify(f"Failed to reload xprompt: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        if bar.is_mounted:
            bar.load_stack_from_xprompt_markdown(markdown, binding=refreshed)
            bar.auto_show_frontmatter_panel()
            bar._refresh_title()
            self.notify(f"Reloaded xprompt '{binding.name}'")  # type: ignore[attr-defined]

    @staticmethod
    def _captured_xprompt_body(panes: list[StashedPromptPane]) -> str:
        """Return canonical multi-prompt body text for captured panes."""
        return "\n---\n".join(pane.text for pane in panes if pane.text.strip())

    @staticmethod
    def _captured_xprompt_frontmatter(
        panes: list[StashedPromptPane],
    ) -> PromptFrontmatter:
        """Return parsed shared frontmatter from captured panes."""
        raw = next((pane.frontmatter for pane in panes if pane.frontmatter), "")
        return PromptFrontmatter.parse(raw)

    async def _write_xprompt_target(
        self,
        target: UnifiedXPromptSaveResult,
        body: str,
        *,
        origin_bar: object | None = None,
    ) -> None:
        import asyncio

        from sase.xprompt.save import build_markdown_xprompt
        from sase.xprompt.save_state import save_last_used_location

        source_markdown = (
            build_markdown_xprompt(target.frontmatter, body)
            if target.target_format is SaveTargetFormat.MARKDOWN
            else None
        )
        try:
            await asyncio.to_thread(write_target_sync, target, target.frontmatter, body)
            await asyncio.to_thread(
                save_last_used_location, "xprompt", target.location_path
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save xprompt: {exc}",
                severity="error",
            )
            return

        verb = "Created" if not target.exists else "Saved draft as"
        self.notify(f"{verb} xprompt '{target.name}'")  # type: ignore[attr-defined]
        self._bind_saved_stack(origin_bar, target, source_markdown=source_markdown)
        self._offer_git_commit(
            target.path, is_new=not target.exists, xprompt_name=target.name
        )

    @staticmethod
    def _bind_saved_stack(
        origin_bar: object | None,
        target: UnifiedXPromptSaveResult,
        *,
        source_markdown: str | None,
    ) -> None:
        """Bind a still-mounted originating bar after successful save-as."""
        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import XPromptBinding

        if not isinstance(origin_bar, PromptInputBar) or not origin_bar.is_mounted:
            return
        if target.target_format is SaveTargetFormat.CONFIG:
            name = target.entry_name or target.name
            binding = XPromptBinding.for_config(target.path, name)
            source_markdown = None
        else:
            binding = XPromptBinding.for_file(target.path)
        origin_bar._stack.bind(binding, source_markdown=source_markdown)
        origin_bar._refresh_title()


_existing_snippet_names = existing_snippet_names
_process_error_text = process_error_text
_run_git_commit_push_sync = run_git_commit_push_sync
_write_snippet_sync = write_snippet_sync
_write_target_sync = write_target_sync


__all__ = ["PromptBarSaveXpromptMixin"]
