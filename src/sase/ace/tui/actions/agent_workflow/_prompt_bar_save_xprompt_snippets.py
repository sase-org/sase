"""Write-side helpers for prompt-bar snippet saves."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ._prompt_bar_save_xprompt_git import PromptBarSaveXpromptGitMixin
from ._prompt_bar_save_xprompt_tasks import PromptBarSaveXpromptTaskMixin

if TYPE_CHECKING:
    from sase.ace.tui.modals.unified_xprompt_save_modal import (
        UnifiedXPromptSaveResult,
    )

log = logging.getLogger(__name__)


class PromptBarSaveSnippetMixin(
    PromptBarSaveXpromptTaskMixin,
    PromptBarSaveXpromptGitMixin,
):
    """Handle the write and cache refresh after the unified snippet panel."""

    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None
    _pending_snippet_saves: dict[str, str]

    async def _write_snippet_target(
        self,
        target: UnifiedXPromptSaveResult,
        body: str,
    ) -> None:
        import asyncio

        from sase.xprompt.save_state import save_last_used_location

        try:
            await asyncio.to_thread(write_snippet_sync, target.path, target.name, body)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save snippet: {exc}",
                severity="error",
            )
            return

        try:
            await asyncio.to_thread(
                save_last_used_location, "snippet", target.location_path
            )
        except Exception as exc:
            log.warning("Failed to remember snippet save location", exc_info=True)
            self.notify(  # type: ignore[attr-defined]
                f"Saved snippet, but failed to remember its location: {exc}",
                severity="warning",
            )

        await self._publish_saved_snippet(target.name, body)

        verb = "Saved" if target.exists else "Created"
        self.notify(  # type: ignore[attr-defined]
            f"{verb} snippet '{target.name}' in {target.display_path}"
        )
        self._offer_git_commit(
            target.path,
            is_new=not target.exists,
            xprompt_name=target.name,
            noun="snippet",
            commit_type="snippet",
        )

    async def _publish_saved_snippet(self, trigger: str, template: str) -> None:
        """Publish a durable save immediately, ahead of config convergence."""
        import asyncio

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
            base = (
                self._snippets_cache
                if self._snippets_cache is not None
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


__all__ = [
    "PromptBarSaveSnippetMixin",
    "existing_snippet_names",
    "write_snippet_sync",
]
