"""Save prompt-bar drafts as reusable xprompts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

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

        from ...modals import XPromptSaveTargetModal
        from ...modals.xprompt_save_target_modal import load_xprompt_save_rows
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SaveAsXpromptRequested):
            return

        body = self._captured_xprompt_body(event.panes)
        frontmatter = self._captured_xprompt_frontmatter(event.panes)
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
        rows = await asyncio.to_thread(load_xprompt_save_rows, project)

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
                    self._create_xprompt_flow(frontmatter, body)
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
            self._confirm_overwrite_xprompt(target, frontmatter, body)

        self.push_screen(  # type: ignore[attr-defined]
            XPromptSaveTargetModal(
                rows,
                project=project,
                pane_count=non_empty_count,
                has_frontmatter=not frontmatter.is_empty,
                allow_create_snippet=True,
            ),
            _on_target,
        )

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
                self._ask_new_xprompt_name(location, frontmatter, body)
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
    ) -> None:
        import asyncio

        from ...modals import XPromptNameModal

        existing_names = await asyncio.to_thread(existing_names_for_location, location)

        def _on_name(name: str | None) -> None:
            if name is None:
                return
            target = target_for_new_xprompt(location, name)
            if name_exists_at_location(location, name, existing_names):
                self._confirm_create_overwrite(target, frontmatter, body, name)
                return
            self._spawn_xprompt_save_task(
                self._write_xprompt_target(
                    target,
                    frontmatter_for_new_target(target, frontmatter, name),
                    body,
                    is_new=True,
                    toast_name=name,
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
        self._offer_git_commit(target.path, is_new=is_new, xprompt_name=toast_name)


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
