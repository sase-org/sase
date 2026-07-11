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
    existing_names_for_location,
    frontmatter_for_new_target,
    name_exists_at_location,
    short_display_path,
    target_for_new_xprompt,
    write_target_sync,
    write_binding_sync,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals import XPromptLocation, XPromptSaveTarget
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
        from ...modals.unified_xprompt_save_modal import load_unified_save_locations
        from ...widgets import PromptInputBar

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
        locations = await asyncio.to_thread(load_unified_save_locations, project)

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

        def _on_target(target: XPromptSaveTarget | None) -> None:
            if target is None:
                return
            if target.kind == "create":
                self._spawn_xprompt_save_task(
                    self._create_xprompt_flow(frontmatter, body, origin_bar=origin_bar)
                )
                return
            if target.kind == "write":
                prepared = frontmatter_for_new_target(target, frontmatter, target.name)
                self._spawn_xprompt_save_task(
                    self._write_xprompt_target(
                        target,
                        prepared,
                        body,
                        is_new=not target.exists,
                        toast_name=target.name,
                        origin_bar=origin_bar,
                    )
                )
                return
            if target.kind == "create_snippet":
                if not snippet_body:
                    self.notify(  # type: ignore[attr-defined]
                        "Current prompt pane is empty - nothing to save as a snippet",
                        severity="warning",
                    )
                    return
                self._spawn_xprompt_save_task(self._create_snippet_flow(snippet_body))
                return
            self._confirm_overwrite_xprompt(
                target, frontmatter, body, origin_bar=origin_bar
            )

        self.push_screen(  # type: ignore[attr-defined]
            UnifiedXPromptSaveModal(
                locations,
                initial_name=(
                    frontmatter.name
                    or (
                        origin_bar._stack.binding.name
                        if origin_bar is not None
                        and origin_bar._stack.binding is not None
                        else ""
                    )
                ),
                allow_create_snippet=True,
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

    def _confirm_overwrite_xprompt(
        self,
        target: XPromptSaveTarget,
        frontmatter: PromptFrontmatter,
        body: str,
        *,
        origin_bar: object | None = None,
    ) -> None:
        from ...modals import ConfirmActionModal, ConfirmKind

        display_path = target.display_path or target.path

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._spawn_xprompt_save_task(
                self._write_xprompt_target(
                    target,
                    frontmatter,
                    body,
                    is_new=False,
                    toast_name=target.name,
                    origin_bar=origin_bar,
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Overwrite XPrompt",
                f"Overwrite xprompt '{target.name}'?",
                subject=display_path,
                kind=ConfirmKind.DANGER,
                confirm_label="Overwrite",
                cancel_label="Cancel",
            ),
            _on_confirm,
        )

    async def _create_xprompt_flow(
        self,
        frontmatter: PromptFrontmatter,
        body: str,
        *,
        origin_bar: object | None = None,
    ) -> None:
        from ...modals import XPromptLocationModal

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )

        def _on_location(location: XPromptLocation | None) -> None:
            if location is None:
                return
            self._spawn_xprompt_save_task(
                self._ask_new_xprompt_name(
                    location, frontmatter, body, origin_bar=origin_bar
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            XPromptLocationModal(project=project),
            _on_location,
        )

    async def _ask_new_xprompt_name(
        self,
        location: XPromptLocation,
        frontmatter: PromptFrontmatter,
        body: str,
        *,
        origin_bar: object | None = None,
    ) -> None:
        import asyncio

        from ...modals import XPromptNameModal

        existing_names = await asyncio.to_thread(existing_names_for_location, location)

        def _on_name(name: str | None) -> None:
            if name is None:
                return
            target = target_for_new_xprompt(location, name)
            if name_exists_at_location(location, name, existing_names):
                self._confirm_create_overwrite(
                    target,
                    frontmatter,
                    body,
                    name,
                    origin_bar=origin_bar,
                )
                return
            self._spawn_xprompt_save_task(
                self._write_xprompt_target(
                    target,
                    frontmatter_for_new_target(target, frontmatter, name),
                    body,
                    is_new=True,
                    toast_name=name,
                    origin_bar=origin_bar,
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            XPromptNameModal(
                location_label=location.label,
                location_path=location.path,
                existing_names=existing_names,
            ),
            _on_name,
        )

    def _confirm_create_overwrite(
        self,
        target: XPromptSaveTarget,
        frontmatter: PromptFrontmatter,
        body: str,
        name: str,
        *,
        origin_bar: object | None = None,
    ) -> None:
        from ...modals import ConfirmActionModal, ConfirmKind

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._spawn_xprompt_save_task(
                self._write_xprompt_target(
                    target,
                    frontmatter_for_new_target(target, frontmatter, name),
                    body,
                    is_new=False,
                    toast_name=name,
                    origin_bar=origin_bar,
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Overwrite Existing XPrompt",
                f"'{name}' already exists at this location.",
                subject=target.display_path or target.path,
                kind=ConfirmKind.DANGER,
                confirm_label="Overwrite",
                cancel_label="Cancel",
            ),
            _on_confirm,
        )

    async def _write_xprompt_target(
        self,
        target: XPromptSaveTarget,
        frontmatter: PromptFrontmatter,
        body: str,
        *,
        is_new: bool,
        toast_name: str,
        origin_bar: object | None = None,
    ) -> None:
        import asyncio

        try:
            await asyncio.to_thread(write_target_sync, target, frontmatter, body)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save xprompt: {exc}",
                severity="error",
            )
            return

        verb = "Created" if is_new else "Saved draft as"
        self.notify(f"{verb} xprompt '{toast_name}'")  # type: ignore[attr-defined]
        self._bind_saved_stack(origin_bar, target)
        self._offer_git_commit(target.path, is_new=is_new, xprompt_name=toast_name)

    @staticmethod
    def _bind_saved_stack(origin_bar: object | None, target: XPromptSaveTarget) -> None:
        """Bind a still-mounted originating bar after successful save-as."""
        from ...widgets import PromptInputBar
        from ...widgets.prompt_stack import XPromptBinding

        if not isinstance(origin_bar, PromptInputBar) or not origin_bar.is_mounted:
            return
        try:
            if target.target_format is SaveTargetFormat.CONFIG:
                name = target.entry_name or target.name
                binding = XPromptBinding.for_config(target.path, name)
                source_markdown = None
            else:
                binding = XPromptBinding.for_file(target.path)
                from pathlib import Path

                source_markdown = Path(target.path).read_text(encoding="utf-8")
        except OSError:
            return
        origin_bar._stack.bind(binding, source_markdown=source_markdown)
        origin_bar._refresh_title()


_existing_names_for_location = existing_names_for_location
_existing_snippet_names = existing_snippet_names
_frontmatter_for_new_target = frontmatter_for_new_target
_name_exists_at_location = name_exists_at_location
_process_error_text = process_error_text
_run_git_commit_push_sync = run_git_commit_push_sync
_short_display_path = short_display_path
_target_for_new_xprompt = target_for_new_xprompt
_write_snippet_sync = write_snippet_sync
_write_target_sync = write_target_sync


__all__ = ["PromptBarSaveXpromptMixin"]
