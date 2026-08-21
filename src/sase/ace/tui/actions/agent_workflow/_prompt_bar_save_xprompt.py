"""Save prompt-bar drafts as reusable xprompts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.widgets._local_xprompt_conversion import (
    convert_placeholders_to_inputs,
)
from sase.xprompt.jinja_inspect import inspect_template
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import (
    SaveTargetFormat,
    SkillPlacementError,
    load_config_xprompt_markdown,
    save_config_xprompt,
    save_markdown_document,
)

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
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
        StashedPromptPane,
    )
    from sase.ace.tui.widgets.prompt_stack import (
        MiniXPromptPaneTarget,
        SourceFingerprint,
    )


@dataclass(frozen=True, slots=True)
class _MiniXPromptPaneSaveSnapshot:
    bar: PromptInputBar
    item_id: str
    generation: int
    target: MiniXPromptPaneTarget
    body: str
    frontmatter: str


@dataclass(frozen=True, slots=True)
class _MiniXPromptSaveDiskState:
    existing_markdown: str | None
    changed_on_disk: bool
    current_fingerprint: SourceFingerprint | None


@dataclass(frozen=True, slots=True)
class _MiniXPromptWriteResult:
    source_markdown: str | None


class PromptBarSaveXpromptMixin(PromptBarSaveSnippetMixin):
    """Handle prompt-bar save-as-xprompt requests."""

    _prompt_context: PromptContext | None
    # Provided by the app's startup/state-init mixins; refreshed after snippet
    # writes so ``get_snippets()`` rebuilds with the new template.
    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None
    _snippet_config_path: str

    async def on_prompt_input_bar_save_as_xprompt_requested(
        self, event: object
    ) -> None:
        """Schedule the save-target load without holding the app pump."""
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

        existing = {arg.name for arg in frontmatter.inputs}
        existing.update(inspect_template(body).unknown_variables)
        conversion = convert_placeholders_to_inputs(body, existing=existing)
        for arg in conversion.inputs:
            frontmatter.set_input(arg)

        self._spawn_xprompt_save_task(
            self._open_save_as_xprompt_picker(
                panes=event.panes,
                snippet_body=event.snippet_body,
                origin_bar=origin_bar,
                body=conversion.body,
                frontmatter=frontmatter,
            )
        )

    async def _open_save_as_xprompt_picker(
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

        from ...modals import UnifiedXPromptSaveModal
        from ...modals.unified_xprompt_save_modal import (
            UnifiedXPromptSaveResult,
            ensure_unified_snippet_target_location,
            load_unified_save_locations,
            load_unified_snippet_locations,
        )
        from sase.xprompt.save_state import load_last_used_locations
        from sase.xprompt.snippet_targets import resolve_snippet_save_target

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

        non_empty_count = sum(1 for pane in panes if pane.text.strip())
        # Snippet mode is always available. Its source is the active
        # pane captured separately as ``snippet_body``; a legacy/direct event
        # without that field falls back to the xprompt body, but only when a
        # single non-blank pane makes that unambiguous. Snippets are single
        # templates, so the active-pane body never carries ``---`` separators.
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
                last_used=last_used,
                preferred_snippet_path=str(snippet_target.write_path),
                preferred_snippet_fallback_reason=snippet_target.fallback_reason,
            ),
            _on_target,
        )

    async def on_prompt_input_bar_write_xprompt_requested(self, event: object) -> None:
        """Schedule bound-xprompt conflict IO outside the app pump."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.WriteXpromptRequested):
            return
        self._spawn_xprompt_save_task(self._handle_write_xprompt_requested(event))

    async def on_prompt_input_bar_mini_xprompt_pane_save_requested(
        self,
        event: object,
    ) -> None:
        """Open the save-review panel for the active mini-xprompt pane."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.MiniXPromptPaneSaveRequested):
            return
        self._spawn_xprompt_save_task(self._open_mini_xprompt_save_confirm(event))

    async def _open_mini_xprompt_save_confirm(self, event: object) -> None:
        import asyncio

        from ...modals import (
            MiniXPromptSaveConfirmModal,
            MiniXPromptSaveConfirmState,
        )
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.MiniXPromptPaneSaveRequested):
            return
        snapshot = self._mini_xprompt_pane_save_snapshot(
            event.origin_bar,
            event.origin_pane_id,
        )
        if snapshot is None:
            return
        try:
            disk_state = await asyncio.to_thread(
                _load_mini_xprompt_save_disk_state,
                snapshot.target,
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to prepare mini-xprompt save review: {exc}",
                severity="error",
            )
            return
        if not self._mini_xprompt_pane_snapshot_current(snapshot):
            self.notify(  # type: ignore[attr-defined]
                "Mini-xprompt draft changed - press Enter again to save",
                severity="warning",
            )
            return
        snapshot.bar.mark_mini_xprompt_changed_on_disk(
            item_id=snapshot.item_id,
            changed=disk_state.changed_on_disk,
        )

        state = MiniXPromptSaveConfirmState(
            name=snapshot.target.name,
            display_path=snapshot.target.display_path,
            body=snapshot.body,
            frontmatter=snapshot.frontmatter,
            target_format=snapshot.target.target_format,
            entry_name=snapshot.target.entry_name,
            exists=disk_state.existing_markdown is not None,
            existing_markdown=disk_state.existing_markdown,
            changed_on_disk=disk_state.changed_on_disk,
            warning=_mini_xprompt_save_warning(snapshot.target),
        )

        def _on_confirm(choice: object | None) -> None:
            if choice == "reload":
                self._reload_mini_xprompt_pane_from_disk(snapshot, disk_state)
                return
            if choice == "retarget":
                snapshot.bar.request_mini_xprompt_target_pane()
                return
            if choice == "close":
                if snapshot.bar.close_mini_xprompt_target("saved"):
                    self.notify(  # type: ignore[attr-defined]
                        f"No changes for mini-xprompt '#{snapshot.target.name}'"
                    )
                return
            if choice in {"save", "overwrite"}:
                self._spawn_xprompt_save_task(
                    self._save_confirmed_mini_xprompt_pane(
                        snapshot,
                        force_overwrite=choice == "overwrite",
                    )
                )

        self.push_screen(  # type: ignore[attr-defined]
            MiniXPromptSaveConfirmModal(state),
            _on_confirm,
        )

    def _mini_xprompt_pane_save_snapshot(
        self,
        bar: PromptInputBar,
        origin_pane_id: str,
    ) -> _MiniXPromptPaneSaveSnapshot | None:
        if not bar.is_mounted:
            return None
        bar._sync_state_from_widgets()
        mini = bar._stack.mini_xprompt_item
        if mini is None or mini.mini_xprompt_target is None:
            return None
        if origin_pane_id and bar._pane_id(mini) != origin_pane_id:
            return None
        return _MiniXPromptPaneSaveSnapshot(
            bar=bar,
            item_id=mini.item_id,
            generation=bar._generation,
            target=mini.mini_xprompt_target,
            body=mini.text.strip(),
            frontmatter=mini.mini_xprompt_target.frontmatter,
        )

    @staticmethod
    def _mini_xprompt_pane_snapshot_current(
        snapshot: _MiniXPromptPaneSaveSnapshot,
    ) -> bool:
        bar = snapshot.bar
        if not bar.is_mounted or bar._generation != snapshot.generation:
            return False
        mini = bar._stack.mini_xprompt_item
        return (
            mini is not None
            and mini.item_id == snapshot.item_id
            and mini.mini_xprompt_target == snapshot.target
            and mini.text.strip() == snapshot.body
        )

    def _reload_mini_xprompt_pane_from_disk(
        self,
        snapshot: _MiniXPromptPaneSaveSnapshot,
        disk_state: _MiniXPromptSaveDiskState,
    ) -> None:
        if disk_state.existing_markdown is None:
            self.notify(  # type: ignore[attr-defined]
                "Mini-xprompt no longer exists on disk",
                severity="warning",
            )
            return
        if not self._mini_xprompt_pane_snapshot_current(snapshot):
            self.notify(  # type: ignore[attr-defined]
                "Mini-xprompt draft changed - reload canceled",
                severity="warning",
            )
            return
        from ...widgets.prompt_stack import split_frontmatter

        frontmatter, body = split_frontmatter(disk_state.existing_markdown)
        if snapshot.bar.reload_mini_xprompt_target_body(
            body,
            frontmatter=frontmatter,
            loaded_markdown=disk_state.existing_markdown,
            loaded_fingerprint=disk_state.current_fingerprint,
        ):
            self.notify(  # type: ignore[attr-defined]
                f"Reloaded mini-xprompt '#{snapshot.target.name}'"
            )

    async def _save_confirmed_mini_xprompt_pane(
        self,
        snapshot: _MiniXPromptPaneSaveSnapshot,
        *,
        force_overwrite: bool = False,
    ) -> None:
        import asyncio

        from ...widgets.prompt_stack import SourceFingerprint
        from sase.xprompt.save_state import save_last_used_location
        from sase.xprompt.write_targets import (
            XPromptWriteTarget,
            classify_written_file,
            write_target_for_written_path,
        )

        if not self._mini_xprompt_pane_snapshot_current(snapshot):
            self.notify(  # type: ignore[attr-defined]
                "Mini-xprompt draft changed - press Enter again to save",
                severity="warning",
            )
            return
        if not force_overwrite:
            try:
                current = await asyncio.to_thread(
                    SourceFingerprint.from_path,
                    snapshot.target.write_path,
                )
            except OSError:
                current = None
            if current != snapshot.target.loaded_fingerprint:
                self.notify(  # type: ignore[attr-defined]
                    "Mini-xprompt changed on disk - press Enter again to review",
                    severity="warning",
                )
                return

        try:
            write_result = await asyncio.to_thread(
                _write_mini_xprompt_sync,
                snapshot.target,
                snapshot.frontmatter,
                snapshot.body,
            )
        except SkillPlacementError as exc:
            self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
            return
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save mini-xprompt: {exc}",
                severity="error",
            )
            return

        try:
            await asyncio.to_thread(
                save_last_used_location,
                "xprompt",
                snapshot.target.location_path,
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Saved mini-xprompt, but failed to remember its location: {exc}",
                severity="warning",
            )

        try:
            loaded_fingerprint = await asyncio.to_thread(
                SourceFingerprint.from_path,
                snapshot.target.write_path,
            )
        except OSError as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Saved mini-xprompt, but failed to refresh fingerprint: {exc}",
                severity="error",
            )
            return

        await self._publish_saved_mini_xprompt(snapshot.target)

        if self._mini_xprompt_pane_snapshot_current(snapshot):
            if snapshot.bar.mark_mini_xprompt_target_written(
                item_id=snapshot.item_id,
                body=snapshot.body,
                frontmatter=snapshot.frontmatter,
                source_markdown=write_result.source_markdown,
                loaded_fingerprint=loaded_fingerprint,
            ):
                snapshot.bar.close_mini_xprompt_target("saved")
        else:
            self.notify(  # type: ignore[attr-defined]
                "Saved mini-xprompt; keeping pane open because the draft changed",
                severity="warning",
            )

        verb = "Saved" if snapshot.target.exists else "Created"
        self.notify(  # type: ignore[attr-defined]
            f"{verb} mini-xprompt '#{snapshot.target.name}'"
        )

        if snapshot.target.via_chezmoi or snapshot.target.apply_target is not None:
            post_write_target = XPromptWriteTarget(
                read_path=Path(snapshot.target.read_path).expanduser(),
                write_path=Path(snapshot.target.write_path).expanduser(),
                apply_target=(
                    Path(snapshot.target.apply_target).expanduser()
                    if snapshot.target.apply_target is not None
                    else None
                ),
                via_chezmoi=snapshot.target.via_chezmoi,
            )
        else:
            post_write_target = write_target_for_written_path(
                snapshot.target.write_path
            )
        kind = classify_written_file(
            post_write_target.write_path,
            read_path=post_write_target.read_path,
        )
        await self._offer_post_write_actions(
            post_write_target,
            kind=kind,
            is_new=not snapshot.target.exists,
            xprompt_name=snapshot.target.name,
            refresh_config_on_success=True,
        )

    async def _publish_saved_mini_xprompt(
        self,
        target: MiniXPromptPaneTarget,
    ) -> None:
        import asyncio

        from sase.xprompt.save_index import invalidate_save_index

        await asyncio.to_thread(invalidate_save_index, target.location_path)
        refresh_config = getattr(self, "_request_prompt_catalog_config_refresh", None)
        if callable(refresh_config):
            refresh_config(reason="mini_xprompt_save")
            return
        if hasattr(self, "_prompt_catalog_generation"):
            self._prompt_catalog_generation += 1
        schedule_rebuild = getattr(self, "_schedule_prompt_catalog_rebuild", None)
        if callable(schedule_rebuild):
            schedule_rebuild(
                reason="mini_xprompt_save",
                force=True,
                config_dirty=True,
            )
        refresh_surfaces = getattr(
            self,
            "_refresh_visible_prompt_catalog_surfaces",
            None,
        )
        if callable(refresh_surfaces):
            refresh_surfaces()

    async def _handle_write_xprompt_requested(self, event: object) -> None:
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
                SourceFingerprint.from_path, event.binding.write_path
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
                XPromptWriteConflictModal(event.binding.name, event.binding.write_path),
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
        from ...widgets.prompt_stack import SourceFingerprint, XPromptBinding
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
            self.notify(f"Failed to write xprompt: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        try:
            loaded_fingerprint = await asyncio.to_thread(
                SourceFingerprint.from_path,
                binding.write_path,
            )
        except OSError as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to refresh xprompt fingerprint: {exc}", severity="error"
            )
            return
        if bar.is_mounted and bar._stack.binding == binding:
            bar._stack.mark_written(
                source_markdown=preserved,
                loaded_fingerprint=loaded_fingerprint,
            )
            bar._mark_xprompt_source_fresh()
            bar._refresh_title()
        self.notify(f"Wrote xprompt '{binding.name}'")  # type: ignore[attr-defined]
        from pathlib import Path

        from sase.xprompt.write_targets import (
            XPromptWriteTarget,
            classify_written_file,
        )

        target = XPromptWriteTarget(
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
            xprompt_name=binding.name,
        )

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
                refreshed = XPromptBinding.for_config(
                    binding.path,
                    binding.entry_name,
                    reference=binding.reference,
                )
            else:
                markdown = await asyncio.to_thread(
                    Path(binding.path).read_text, encoding="utf-8"
                )
                refreshed = XPromptBinding.for_file(
                    binding.path,
                    reference=binding.reference,
                )
        except Exception as exc:
            self.notify(f"Failed to reload xprompt: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        if bar.is_mounted:
            bar.load_stack_from_xprompt_markdown(markdown, binding=refreshed)
            bar.auto_show_frontmatter_panel()
            bar._mark_xprompt_source_fresh()
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
        except SkillPlacementError as exc:
            # The message already names the source and the required move.
            self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
            return
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save xprompt: {exc}",
                severity="error",
            )
            return

        verb = "Created" if not target.exists else "Saved draft as"
        self.notify(f"{verb} xprompt '{target.name}'")  # type: ignore[attr-defined]
        self._bind_saved_stack(origin_bar, target, source_markdown=source_markdown)
        from sase.xprompt.write_targets import (
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
            xprompt_name=target.name,
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
            binding = XPromptBinding.for_config(
                target.path,
                name,
                reference=f"#{name}",
            )
            source_markdown = None
        else:
            reference = None if target.frontmatter.skill else f"#{target.name}"
            binding = XPromptBinding.for_file(target.path, reference=reference)
        origin_bar.target_xprompt(binding, source_markdown=source_markdown)


def _load_mini_xprompt_save_disk_state(
    target: MiniXPromptPaneTarget,
) -> _MiniXPromptSaveDiskState:
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint

    existing_markdown = _load_existing_mini_xprompt_markdown(target)
    try:
        current_fingerprint = SourceFingerprint.from_path(target.write_path)
    except OSError:
        current_fingerprint = None
    return _MiniXPromptSaveDiskState(
        existing_markdown=existing_markdown,
        changed_on_disk=current_fingerprint != target.loaded_fingerprint,
        current_fingerprint=current_fingerprint,
    )


def _load_existing_mini_xprompt_markdown(
    target: MiniXPromptPaneTarget,
) -> str | None:
    path = Path(target.write_path)
    if not path.exists():
        return None
    if target.target_format is SaveTargetFormat.CONFIG:
        if not target.entry_name:
            raise ValueError("config-backed mini-xprompt is missing an entry name")
        try:
            return load_config_xprompt_markdown(path, target.entry_name)
        except KeyError:
            return None
        except ValueError:
            if not target.exists:
                return None
            raise
    return path.read_text(encoding="utf-8")


def _write_mini_xprompt_sync(
    target: MiniXPromptPaneTarget,
    frontmatter: str,
    body: str,
) -> _MiniXPromptWriteResult:
    """Write one mini-xprompt through the established xprompt save primitives."""
    from sase.xprompt.models import XPrompt
    from sase.xprompt.segment_separators import xprompt_has_segment_separators

    if not body.strip():
        raise ValueError("mini-xprompt body is empty")
    if xprompt_has_segment_separators(XPrompt(name=target.name, content=body)):
        raise ValueError("mini-xprompt body contains a top-level --- separator")

    frontmatter_model = _mini_xprompt_frontmatter_for_save(frontmatter)
    if target.target_format is SaveTargetFormat.MARKDOWN:
        source_markdown = _mini_xprompt_markdown_document(target, frontmatter, body)
        save_markdown_document(target.write_path, source_markdown)
        return _MiniXPromptWriteResult(source_markdown=source_markdown)
    if target.target_format is SaveTargetFormat.CONFIG:
        entry_name = target.entry_name or target.storage_name or target.name
        if not save_config_xprompt(
            target.write_path,
            entry_name,
            frontmatter_model,
            body,
        ):
            raise RuntimeError("config insertion failed")
        return _MiniXPromptWriteResult(source_markdown=None)
    raise RuntimeError("unsupported mini-xprompt save target")


def _mini_xprompt_frontmatter_for_save(raw: str) -> PromptFrontmatter:
    """Parse frontmatter strictly enough for a final write."""
    import yaml  # type: ignore[import-untyped]

    from sase.xprompt.loader_parsing import parse_yaml_front_matter

    text = raw.strip()
    if not text:
        return PromptFrontmatter()
    if text.startswith("---"):
        mapping, _ = parse_yaml_front_matter(text)
        if mapping is None:
            raise ValueError("frontmatter block is invalid or unterminated")
    else:
        try:
            mapping = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"frontmatter YAML is invalid: {exc}") from exc
        if mapping is not None and not isinstance(mapping, dict):
            raise ValueError("frontmatter must be a YAML mapping")
    return PromptFrontmatter.parse(raw)


def _mini_xprompt_markdown_document(
    target: MiniXPromptPaneTarget,
    frontmatter: str,
    body: str,
) -> str:
    """Build the markdown file text, preserving unchanged source body bytes."""
    if target.loaded_markdown is not None and target.loaded_body == body:
        from sase.ace.tui.widgets.prompt_stack import split_frontmatter

        old_frontmatter, _ = split_frontmatter(target.loaded_markdown)
        return _replace_markdown_frontmatter(
            target.loaded_markdown,
            old_frontmatter,
            frontmatter.strip(),
        )
    return _raw_markdown_xprompt(frontmatter, body)


def _replace_markdown_frontmatter(
    source_markdown: str,
    old_frontmatter: str,
    new_frontmatter: str,
) -> str:
    if old_frontmatter:
        remainder = source_markdown[len(old_frontmatter) :]
        return (
            new_frontmatter + remainder if new_frontmatter else remainder.lstrip("\r\n")
        )
    if new_frontmatter:
        return f"{new_frontmatter}\n\n{source_markdown}"
    return source_markdown


def _raw_markdown_xprompt(frontmatter: str, body: str) -> str:
    clean_frontmatter = frontmatter.strip()
    clean_body = body.rstrip()
    if clean_frontmatter and clean_body:
        return f"{clean_frontmatter}\n\n{clean_body}\n"
    if clean_frontmatter:
        return f"{clean_frontmatter}\n"
    return f"{clean_body}\n"


def _mini_xprompt_save_warning(target: MiniXPromptPaneTarget) -> str | None:
    if target.save_warning:
        return target.save_warning
    if target.derived_from:
        return (
            f"# {target.name} comes from {target.derived_from} - "
            f"this save writes {target.display_path}"
        )
    if target.loaded_body is not None and not target.exists:
        return (
            f"# {target.name} was loaded from another source - "
            f"this save writes {target.display_path}"
        )
    return None


_existing_snippet_names = existing_snippet_names
_process_error_text = process_error_text
_run_git_commit_push_sync = run_git_commit_push_sync
_write_snippet_sync = write_snippet_sync
_write_target_sync = write_target_sync


__all__ = ["PromptBarSaveXpromptMixin"]
