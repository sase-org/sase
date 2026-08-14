"""Write-side helpers for prompt-bar snippet saves."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ._prompt_bar_save_xprompt_git import PromptBarSaveXpromptGitMixin
from ._prompt_bar_save_xprompt_procs import PromptBarSaveXpromptTaskMixin

if TYPE_CHECKING:
    from sase.ace.tui.modals.unified_xprompt_save_modal import (
        UnifiedXPromptSaveResult,
    )
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_stack import SnippetPaneTarget, SourceFingerprint

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _SnippetPaneSaveSnapshot:
    bar: PromptInputBar
    item_id: str
    generation: int
    target: SnippetPaneTarget
    body: str


@dataclass(frozen=True, slots=True)
class _SnippetSaveDiskState:
    existing_body: str | None
    changed_on_disk: bool
    current_fingerprint: SourceFingerprint | None


class PromptBarSaveSnippetMixin(
    PromptBarSaveXpromptTaskMixin,
    PromptBarSaveXpromptGitMixin,
):
    """Handle the write and cache refresh after the unified snippet panel."""

    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None
    _pending_snippet_saves: dict[str, str]

    async def on_prompt_input_bar_snippet_pane_save_requested(
        self,
        event: object,
    ) -> None:
        """Open the save-confirmation panel for the active snippet pane."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SnippetPaneSaveRequested):
            return
        self._spawn_xprompt_save_task(self._open_snippet_save_confirm(event))

    async def _open_snippet_save_confirm(self, event: object) -> None:
        from ...modals import SnippetSaveConfirmModal, SnippetSaveConfirmState
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SnippetPaneSaveRequested):
            return
        snapshot = self._snippet_pane_save_snapshot(
            event.origin_bar,
            event.origin_pane_id,
        )
        if snapshot is None:
            return
        disk_state = await asyncio.to_thread(
            _load_snippet_save_disk_state,
            snapshot.target,
        )
        if not self._snippet_pane_snapshot_current(snapshot):
            self.notify(  # type: ignore[attr-defined]
                "Snippet draft changed - press Enter again to save",
                severity="warning",
            )
            return
        state = SnippetSaveConfirmState(
            trigger=snapshot.target.trigger,
            display_path=snapshot.target.display_path,
            body=snapshot.body,
            exists=disk_state.existing_body is not None,
            existing_body=disk_state.existing_body,
            changed_on_disk=disk_state.changed_on_disk,
            warning=_snippet_save_warning(snapshot.target),
        )

        def _on_confirm(choice: object | None) -> None:
            if choice == "reload":
                self._reload_snippet_pane_from_disk(snapshot, disk_state)
                return
            if choice == "close":
                snapshot.bar.close_snippet_target("saved")
                return
            if choice == "save":
                self._spawn_xprompt_save_task(
                    self._save_confirmed_snippet_pane(snapshot)
                )

        self.push_screen(  # type: ignore[attr-defined]
            SnippetSaveConfirmModal(state),
            _on_confirm,
        )

    def _snippet_pane_save_snapshot(
        self,
        bar: PromptInputBar,
        origin_pane_id: str,
    ) -> _SnippetPaneSaveSnapshot | None:
        if not bar.is_mounted:
            return None
        bar._sync_state_from_widgets()
        snippet = bar._stack.snippet_item
        if snippet is None or snippet.snippet_target is None:
            return None
        if origin_pane_id and bar._pane_id(snippet) != origin_pane_id:
            return None
        return _SnippetPaneSaveSnapshot(
            bar=bar,
            item_id=snippet.item_id,
            generation=bar._generation,
            target=snippet.snippet_target,
            body=snippet.text.strip(),
        )

    @staticmethod
    def _snippet_pane_snapshot_current(
        snapshot: _SnippetPaneSaveSnapshot,
    ) -> bool:
        bar = snapshot.bar
        if not bar.is_mounted or bar._generation != snapshot.generation:
            return False
        snippet = bar._stack.snippet_item
        return (
            snippet is not None
            and snippet.item_id == snapshot.item_id
            and snippet.snippet_target == snapshot.target
            and snippet.text.strip() == snapshot.body
        )

    def _reload_snippet_pane_from_disk(
        self,
        snapshot: _SnippetPaneSaveSnapshot,
        disk_state: _SnippetSaveDiskState,
    ) -> None:
        if disk_state.existing_body is None:
            self.notify(  # type: ignore[attr-defined]
                "Snippet no longer exists on disk",
                severity="warning",
            )
            return
        if not self._snippet_pane_snapshot_current(snapshot):
            self.notify(  # type: ignore[attr-defined]
                "Snippet draft changed - reload canceled",
                severity="warning",
            )
            return
        if snapshot.bar.reload_snippet_target_body(
            disk_state.existing_body,
            loaded_fingerprint=disk_state.current_fingerprint,
        ):
            self.notify(  # type: ignore[attr-defined]
                f"Reloaded snippet '{snapshot.target.trigger}'"
            )

    async def _save_confirmed_snippet_pane(
        self,
        snapshot: _SnippetPaneSaveSnapshot,
    ) -> None:
        success = await self.save_snippet(
            write_path=snapshot.target.write_path,
            read_path=snapshot.target.read_path,
            location_path=snapshot.target.write_path,
            display_path=snapshot.target.display_path,
            trigger=snapshot.target.trigger,
            body=snapshot.body,
            exists=snapshot.target.exists,
            apply_target=snapshot.target.apply_target,
            via_chezmoi=snapshot.target.via_chezmoi,
        )
        if success and self._snippet_pane_snapshot_current(snapshot):
            snapshot.bar.close_snippet_target("saved")

    async def _write_snippet_target(
        self,
        target: UnifiedXPromptSaveResult,
        body: str,
    ) -> None:
        await self.save_snippet(
            write_path=target.path,
            read_path=target.path,
            location_path=target.location_path,
            display_path=target.display_path,
            trigger=target.name,
            body=body,
            exists=target.exists,
        )

    async def save_snippet(
        self,
        *,
        write_path: str,
        read_path: str,
        location_path: str,
        display_path: str,
        trigger: str,
        body: str,
        exists: bool,
        apply_target: str | None = None,
        via_chezmoi: bool = False,
    ) -> bool:
        """Write one snippet, publish it live, and offer post-write actions."""
        from sase.xprompt.save_state import save_last_used_location

        try:
            await asyncio.to_thread(write_snippet_sync, write_path, trigger, body)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save snippet: {exc}",
                severity="error",
            )
            return False

        try:
            await asyncio.to_thread(save_last_used_location, "snippet", location_path)
        except Exception as exc:
            log.warning("Failed to remember snippet save location", exc_info=True)
            self.notify(  # type: ignore[attr-defined]
                f"Saved snippet, but failed to remember its location: {exc}",
                severity="warning",
            )

        await self._publish_saved_snippet(trigger, body)

        verb = "Saved" if exists else "Created"
        self.notify(  # type: ignore[attr-defined]
            f"{verb} snippet '{trigger}' in {display_path}"
        )
        from sase.xprompt.write_targets import (
            XPromptWriteTarget,
            classify_written_file,
            write_target_for_written_path,
        )

        if via_chezmoi or apply_target is not None:
            post_write_target = XPromptWriteTarget(
                read_path=Path(read_path).expanduser(),
                write_path=Path(write_path).expanduser(),
                apply_target=(
                    Path(apply_target).expanduser()
                    if apply_target is not None
                    else None
                ),
                via_chezmoi=via_chezmoi,
            )
        else:
            post_write_target = write_target_for_written_path(write_path)
        kind = classify_written_file(
            post_write_target.write_path,
            read_path=post_write_target.read_path,
        )
        await self._offer_post_write_actions(
            post_write_target,
            kind=kind,
            is_new=not exists,
            xprompt_name=trigger,
            noun="snippet",
            commit_type="snippet",
            refresh_config_on_success=True,
        )
        return True

    async def _publish_saved_snippet(self, trigger: str, template: str) -> None:
        """Publish a durable save immediately, ahead of config convergence."""
        from ...prompt_catalog import compose_pending_snippet_saves

        pending = getattr(self, "_pending_snippet_saves", None)
        if pending is None:
            pending = {}
            self._pending_snippet_saves = pending
        pending[trigger] = template
        if hasattr(self, "_prompt_catalog_generation"):
            self._prompt_catalog_generation += 1
        schedule_rebuild = getattr(self, "_schedule_prompt_catalog_rebuild", None)
        if callable(schedule_rebuild):
            schedule_rebuild(
                reason="snippet_save",
                force=True,
                config_dirty=True,
            )

        while True:
            generation = getattr(self, "_prompt_catalog_generation", None)
            catalog = getattr(self, "_prompt_catalog", None)
            base = (
                catalog.explicit_snippets
                if catalog is not None
                else self._user_snippets
            )
            base_snapshot = dict(base)
            pending_snapshot = dict(self._pending_snippet_saves)
            composed = await asyncio.to_thread(
                compose_pending_snippet_saves,
                base_snapshot,
                pending_snapshot,
            )
            if generation != getattr(self, "_prompt_catalog_generation", None):
                continue
            if pending_snapshot != self._pending_snippet_saves:
                continue
            self._snippets_cache = composed
            break

        refresh_surfaces = getattr(
            self,
            "_refresh_visible_prompt_catalog_surfaces",
            None,
        )
        if callable(refresh_surfaces):
            refresh_surfaces()


def existing_snippet_names(config_path: str) -> set[str]:
    """Return the snippet triggers defined in *config_path* only."""
    import yaml  # type: ignore[import-untyped]

    path = Path(config_path)
    if not path.is_file():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    ace = data.get("ace")
    if not isinstance(ace, dict):
        return set()
    snippets = ace.get("snippets")
    if not isinstance(snippets, dict):
        return set()
    return {str(name) for name in snippets}


def write_snippet_sync(config_path: str, name: str, body: str) -> None:
    from sase.xprompt.snippet_config_yaml import insert_snippet_into_config

    if not insert_snippet_into_config(config_path, name, body):
        raise RuntimeError("snippet insertion failed")


def _load_snippet_save_disk_state(
    target: SnippetPaneTarget,
) -> _SnippetSaveDiskState:
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint
    from sase.xprompt.snippet_targets import load_snippet_template

    try:
        existing_body = load_snippet_template(target.write_path, target.trigger)
    except Exception:
        existing_body = None

    current_signature = SourceFingerprint.stat_signature(target.write_path)
    loaded_signature = (
        None
        if target.loaded_fingerprint is None
        else (target.loaded_fingerprint.mtime_ns, target.loaded_fingerprint.size)
    )
    changed_on_disk = current_signature != loaded_signature
    try:
        current_fingerprint = SourceFingerprint.from_path(target.write_path)
    except OSError:
        current_fingerprint = None
    return _SnippetSaveDiskState(
        existing_body=existing_body,
        changed_on_disk=changed_on_disk,
        current_fingerprint=current_fingerprint,
    )


def _snippet_save_warning(target: SnippetPaneTarget) -> str | None:
    if target.save_warning:
        return target.save_warning
    if target.derived_from:
        return (
            f"⚠ ⇥ {target.trigger} comes from {target.derived_from} — "
            "this entry will override it"
        )
    if target.loaded_body is not None and not target.exists:
        return (
            f"⚠ ⇥ {target.trigger} was loaded from another config — "
            f"saving writes {target.display_path}"
        )
    return None


__all__ = [
    "PromptBarSaveSnippetMixin",
    "existing_snippet_names",
    "write_snippet_sync",
]
