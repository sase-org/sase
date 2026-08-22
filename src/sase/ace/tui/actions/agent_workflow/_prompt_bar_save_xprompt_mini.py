"""Prompt-bar mini-xprompt pane save workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.xprompt.save import SkillPlacementError

from ._prompt_bar_save_xprompt_mini_io import (
    MiniXPromptSaveDiskState,
    load_mini_xprompt_save_disk_state,
    mini_xprompt_save_warning,
    write_mini_xprompt_sync,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_stack import MiniXPromptPaneTarget


@dataclass(frozen=True, slots=True)
class _MiniXPromptPaneSaveSnapshot:
    bar: PromptInputBar
    item_id: str
    generation: int
    target: MiniXPromptPaneTarget
    body: str
    frontmatter: str


class PromptBarMiniXPromptSaveMixin:
    """Save and publish edits from a prompt bar's mini-xprompt pane."""

    async def on_prompt_input_bar_mini_xprompt_pane_save_requested(
        self,
        event: object,
    ) -> None:
        """Open the save-review panel for the active mini-xprompt pane."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.MiniXPromptPaneSaveRequested):
            return
        self._spawn_xprompt_save_task(  # type: ignore[attr-defined]
            self._open_mini_xprompt_save_confirm(event)
        )

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
                load_mini_xprompt_save_disk_state,
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
        refreshed_snapshot = self._mini_xprompt_pane_save_snapshot(
            snapshot.bar,
            event.origin_pane_id,
        )
        if refreshed_snapshot is None:
            return
        snapshot = refreshed_snapshot

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
            warning=mini_xprompt_save_warning(snapshot.target),
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
                self._spawn_xprompt_save_task(  # type: ignore[attr-defined]
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
        disk_state: MiniXPromptSaveDiskState,
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
                write_mini_xprompt_sync,
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
        await self._offer_post_write_actions(  # type: ignore[attr-defined]
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


__all__ = ["PromptBarMiniXPromptSaveMixin"]
