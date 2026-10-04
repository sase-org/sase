"""Save prompt-bar drafts as reusable macros."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.widgets._local_macro_conversion import (
    convert_placeholders_to_inputs,
)
from sase.macro.jinja_assist import JinjaScope
from sase.macro.jinja_inspect import undeclared_variables
from sase.macro.prompt_frontmatter import PromptFrontmatter
from sase.macro.save import SaveTargetFormat, SkillPlacementError

from . import _prompt_bar_save_macro_mini_io as _mini_macro_io
from ._prompt_bar_save_macro_git import (
    process_error_text,
    run_git_commit_push_sync,
    subprocess as subprocess,
)
from ._prompt_bar_save_macro_mini import PromptBarMiniMacroSaveMixin
from ._prompt_bar_save_macro_snippets import (
    PromptBarSaveSnippetMixin,
    existing_snippet_names,
    write_snippet_sync,
)
from ._prompt_bar_save_macro_targets import (
    write_binding_sync,
    write_target_sync,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals.unified_macro_save_modal import (
        UnifiedMacroSaveResult,
    )
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
        StashedPromptPane,
    )


class PromptBarSaveMacroMixin(
    PromptBarMiniMacroSaveMixin,
    PromptBarSaveSnippetMixin,
):
    """Handle prompt-bar save-as-macro requests."""

    _prompt_context: PromptContext | None
    # Provided by the app's startup/state-init mixins; refreshed after snippet
    # writes so ``get_snippets()`` rebuilds with the new template.
    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None
    _snippet_config_path: str

    async def on_prompt_input_bar_save_as_macro_requested(self, event: object) -> None:
        """Schedule the save-target load without holding the app pump."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SaveAsMacroRequested):
            return

        body = self._captured_macro_body(event.panes)
        frontmatter = self._captured_macro_frontmatter(event.panes)
        origin_bar = event.origin_bar
        if not body.strip() and frontmatter.is_empty:
            self.notify(  # type: ignore[attr-defined]
                "Nothing to save as a macro",
                severity="warning",
            )
            return

        existing = {arg.name for arg in frontmatter.inputs}
        unknown = undeclared_variables(
            body, JinjaScope(kind="xprompt", frontmatter=None)
        )
        # Engine scope variables (``wait``, ``patch_name``, ``n``, ...) are
        # render-time builtins and must never become inferred inputs.
        existing.update(unknown or ())
        conversion = convert_placeholders_to_inputs(body, existing=existing)
        for arg in conversion.inputs:
            frontmatter.set_input(arg)

        self._spawn_macro_save_task(
            self._open_save_as_macro_picker(
                panes=event.panes,
                snippet_body=event.snippet_body,
                origin_bar=origin_bar,
                body=conversion.body,
                frontmatter=frontmatter,
            )
        )

    async def _open_save_as_macro_picker(
        self,
        *,
        panes: list[StashedPromptPane],
        snippet_body: str | None,
        origin_bar: PromptInputBar | None,
        body: str,
        frontmatter: PromptFrontmatter,
    ) -> None:
        """Load save destinations off-thread, then push the picker."""
        import asyncio

        from ...modals import UnifiedMacroSaveModal
        from ...modals.unified_macro_save_modal import (
            UnifiedMacroSaveResult,
            ensure_unified_snippet_target_location,
            load_unified_save_locations,
            load_unified_snippet_locations,
        )
        from ...modals.unified_macro_save_support import SaveMode
        from sase.macro.save_state import load_last_used_locations
        from sase.macro.snippet_targets import resolve_snippet_save_target

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )
        # A draft declaring ``skill:`` may only be written to a canonical
        # ``skills/`` directory, so it gets a different destination index.
        locations, snippet_locations, last_used, snippet_target = await asyncio.gather(
            asyncio.to_thread(
                load_unified_save_locations, project, skill=bool(frontmatter.skill)
            ),
            asyncio.to_thread(load_unified_snippet_locations, project),
            asyncio.to_thread(load_last_used_locations),
            asyncio.to_thread(resolve_snippet_save_target, self._snippet_config_path),
        )
        snippet_locations = ensure_unified_snippet_target_location(
            snippet_locations,
            snippet_target,
        )
        last_used_for_modal: dict[SaveMode, str] = {}
        if "macro" in last_used:
            last_used_for_modal["macro"] = last_used["macro"]
        if "snippet" in last_used:
            last_used_for_modal["snippet"] = last_used["snippet"]

        non_empty_count = sum(1 for pane in panes if pane.text.strip())
        # Snippet mode is always available. Its source is the active
        # pane captured separately as ``snippet_body``; a legacy/direct event
        # without that field falls back to the macro body, but only when a
        # single non-blank pane makes that unambiguous. Snippets are single
        # templates, so the active-pane body never carries ``---`` separators.
        if snippet_body is None:
            snippet_body = body if non_empty_count == 1 else ""
        snippet_body = snippet_body.strip()

        def _on_target(target: UnifiedMacroSaveResult | None) -> None:
            if target is None:
                return
            if target.mode == "macro":
                self._spawn_macro_save_task(
                    self._write_macro_target(
                        target,
                        body,
                        origin_bar=origin_bar,
                    )
                )
                return
            self._spawn_macro_save_task(
                self._write_snippet_target(target, snippet_body)
            )

        self.push_screen(  # type: ignore[attr-defined]
            UnifiedMacroSaveModal(
                locations,
                snippet_locations=snippet_locations,
                frontmatter=frontmatter,
                body=body,
                snippet_body=snippet_body,
                pane_count=len(panes),
                initial_name=(
                    frontmatter.name
                    or (
                        origin_bar._stack.binding.name
                        if origin_bar is not None
                        and origin_bar._stack.binding is not None
                        else ""
                    )
                ),
                last_used=last_used_for_modal,
                preferred_snippet_path=str(snippet_target.write_path),
                preferred_snippet_fallback_reason=snippet_target.fallback_reason,
            ),
            _on_target,
        )

    async def on_prompt_input_bar_write_macro_requested(self, event: object) -> None:
        """Schedule bound-macro conflict IO outside the app pump."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.WriteMacroRequested):
            return
        self._spawn_macro_save_task(self._handle_write_macro_requested(event))

    async def _handle_write_macro_requested(self, event: object) -> None:
        """Write a bound macro, resolving external-change conflicts first."""
        import asyncio

        from ...modals import MacroWriteConflictModal
        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import SourceFingerprint

        if not isinstance(event, PromptInputBar.WriteMacroRequested):
            return
        bar = event.origin_bar
        if not bar.is_mounted or bar._stack.binding != event.binding:
            return
        body = self._captured_macro_body(event.panes)
        frontmatter = self._captured_macro_frontmatter(event.panes)
        try:
            current = await asyncio.to_thread(
                SourceFingerprint.from_path, event.binding.write_path
            )
        except OSError:
            current = None
        if current != event.binding.loaded_fingerprint:

            def _resolved(choice: str | None) -> None:
                if choice == "overwrite":
                    self._spawn_macro_save_task(
                        self._write_bound_macro(bar, event.binding, frontmatter, body)
                    )
                elif choice == "reload":
                    self._spawn_macro_save_task(
                        self._reload_bound_macro(bar, event.binding)
                    )
                elif choice == "save_as":
                    bar.request_save_as_macro()

            self.push_screen(  # type: ignore[attr-defined]
                MacroWriteConflictModal(event.binding.name, event.binding.write_path),
                _resolved,
            )
            return
        await self._write_bound_macro(bar, event.binding, frontmatter, body)

    async def _write_bound_macro(
        self,
        bar: object,
        binding: object,
        frontmatter: PromptFrontmatter,
        body: str,
    ) -> None:
        import asyncio

        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import (
            SourceFingerprint,
            MacroBinding as MacroBinding,
        )
        from sase.macro.save import save_markdown_document

        if not isinstance(bar, PromptInputBar) or not isinstance(binding, MacroBinding):
            return
        preserved: str | None = None
        try:
            if binding.target_format is SaveTargetFormat.MARKDOWN:
                preserved = bar._stack.markdown_preserving_unchanged_body(frontmatter)
            if preserved is not None:
                await asyncio.to_thread(
                    save_markdown_document,
                    binding.write_path,
                    preserved,
                )
            else:
                await asyncio.to_thread(write_binding_sync, binding, frontmatter, body)
        except SkillPlacementError as exc:
            self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
            return
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to write macro: {exc}", severity="error"
            )
            return
        try:
            loaded_fingerprint = await asyncio.to_thread(
                SourceFingerprint.from_path,
                binding.write_path,
            )
        except OSError as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to refresh macro fingerprint: {exc}", severity="error"
            )
            return
        if bar.is_mounted and bar._stack.binding == binding:
            bar._stack.mark_written(
                source_markdown=preserved,
                loaded_fingerprint=loaded_fingerprint,
            )
            bar._mark_macro_source_fresh()
            bar._refresh_title()
        self.notify(f"Wrote macro '{binding.name}'")  # type: ignore[attr-defined]
        from pathlib import Path

        from sase.macro.write_targets import (
            MacroWriteTarget,
            classify_written_file,
        )

        target = MacroWriteTarget(
            read_path=Path(binding.path).expanduser(),
            write_path=Path(binding.write_path).expanduser(),
            apply_target=(
                Path(binding.apply_target).expanduser()
                if binding.apply_target is not None
                else None
            ),
            via_chezmoi=binding.via_chezmoi,
        )
        kind = classify_written_file(target.write_path, read_path=target.read_path)
        await self._offer_post_write_actions(
            target,
            kind=kind,
            is_new=False,
            macro_name=binding.name,
        )

    async def _reload_bound_macro(self, bar: object, binding: object) -> None:
        import asyncio
        from pathlib import Path

        from sase.macro.save import load_config_macro_markdown

        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import MacroBinding as MacroBinding

        if not isinstance(bar, PromptInputBar) or not isinstance(binding, MacroBinding):
            return
        try:
            if binding.kind == "config" and binding.entry_name:
                markdown = await asyncio.to_thread(
                    load_config_macro_markdown, binding.path, binding.entry_name
                )
                refreshed = MacroBinding.for_config(
                    binding.path,
                    binding.entry_name,
                    reference=binding.reference,
                )
            else:
                markdown = await asyncio.to_thread(
                    Path(binding.path).read_text, encoding="utf-8"
                )
                refreshed = MacroBinding.for_file(
                    binding.path,
                    reference=binding.reference,
                )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to reload macro: {exc}", severity="error"
            )
            return
        if bar.is_mounted:
            bar.load_stack_from_macro_markdown(markdown, binding=refreshed)
            bar.auto_show_frontmatter_panel()
            bar._mark_macro_source_fresh()
            bar._refresh_title()
            self.notify(  # type: ignore[attr-defined]
                f"Reloaded macro '{binding.name}'"
            )

    @staticmethod
    def _captured_macro_body(panes: list[StashedPromptPane]) -> str:
        """Return canonical multi-prompt body text for captured panes."""
        return "\n---\n".join(pane.text for pane in panes if pane.text.strip())

    @staticmethod
    def _captured_macro_frontmatter(
        panes: list[StashedPromptPane],
    ) -> PromptFrontmatter:
        """Return parsed shared frontmatter from captured panes."""
        raw = next((pane.frontmatter for pane in panes if pane.frontmatter), "")
        return PromptFrontmatter.parse(raw)

    async def _write_macro_target(
        self,
        target: UnifiedMacroSaveResult,
        body: str,
        *,
        origin_bar: object | None = None,
    ) -> None:
        import asyncio

        from sase.macro.save import build_markdown_macro
        from sase.macro.save_state import save_last_used_location

        source_markdown = (
            build_markdown_macro(target.frontmatter, body)
            if target.target_format is SaveTargetFormat.MARKDOWN
            else None
        )
        try:
            await asyncio.to_thread(write_target_sync, target, target.frontmatter, body)
            await asyncio.to_thread(
                save_last_used_location, "macro", target.location_path
            )
        except SkillPlacementError as exc:
            # The message already names the source and the required move.
            self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
            return
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save macro: {exc}",
                severity="error",
            )
            return

        verb = "Created" if not target.exists else "Saved draft as"
        self.notify(  # type: ignore[attr-defined]
            f"{verb} macro '{target.name}'"
        )
        self._bind_saved_stack(origin_bar, target, source_markdown=source_markdown)
        from sase.macro.write_targets import (
            classify_written_file,
            write_target_for_written_path,
        )

        post_write_target = write_target_for_written_path(target.path)
        kind = classify_written_file(
            post_write_target.write_path,
            read_path=post_write_target.read_path,
        )
        await self._offer_post_write_actions(
            post_write_target,
            kind=kind,
            is_new=not target.exists,
            macro_name=target.name,
        )

    @staticmethod
    def _bind_saved_stack(
        origin_bar: object | None,
        target: UnifiedMacroSaveResult,
        *,
        source_markdown: str | None,
    ) -> None:
        """Bind a still-mounted originating bar after successful save-as."""
        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import MacroBinding as MacroBinding

        if not isinstance(origin_bar, PromptInputBar) or not origin_bar.is_mounted:
            return
        if target.target_format is SaveTargetFormat.CONFIG:
            name = target.entry_name or target.name
            binding = MacroBinding.for_config(
                target.path,
                name,
                reference=f"#{name}",
            )
            source_markdown = None
        else:
            reference = None if target.frontmatter.skill else f"#{target.name}"
            binding = MacroBinding.for_file(target.path, reference=reference)
        origin_bar.target_macro(binding, source_markdown=source_markdown)


# Compatibility aliases for callers that imported the old monolithic helpers.
_MiniMacroSaveDiskState = _mini_macro_io.MiniMacroSaveDiskState
_load_existing_mini_macro_markdown = _mini_macro_io._load_existing_mini_macro_markdown
_load_mini_macro_save_disk_state = _mini_macro_io.load_mini_macro_save_disk_state
_mini_macro_frontmatter_for_save = _mini_macro_io._mini_macro_frontmatter_for_save
_mini_macro_markdown_document = _mini_macro_io._mini_macro_markdown_document
_mini_macro_save_warning = _mini_macro_io.mini_macro_save_warning
_raw_markdown_macro = _mini_macro_io._raw_markdown_macro
_replace_markdown_frontmatter = _mini_macro_io._replace_markdown_frontmatter
_write_mini_macro_sync = _mini_macro_io.write_mini_macro_sync

_existing_snippet_names = existing_snippet_names
_process_error_text = process_error_text
_run_git_commit_push_sync = run_git_commit_push_sync
_write_snippet_sync = write_snippet_sync
_write_target_sync = write_target_sync


__all__ = ["PromptBarSaveMacroMixin"]
