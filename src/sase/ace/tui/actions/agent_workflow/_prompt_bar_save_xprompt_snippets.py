"""Write-side helpers for prompt-bar snippet saves."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ._prompt_bar_save_xprompt_git import PromptBarSaveXpromptGitMixin
from ._prompt_bar_save_xprompt_tasks import PromptBarSaveXpromptTaskMixin

if TYPE_CHECKING:
    from sase.ace.tui.modals.unified_xprompt_save_modal import (
        UnifiedXPromptSaveResult,
    )


class PromptBarSaveSnippetMixin(
    PromptBarSaveXpromptTaskMixin,
    PromptBarSaveXpromptGitMixin,
):
    """Handle the write and cache refresh after the unified snippet panel."""

    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None

    async def _write_snippet_target(
        self,
        target: UnifiedXPromptSaveResult,
        body: str,
    ) -> None:
        import asyncio

        from sase.config import load_merged_config
        from sase.xprompt.save_state import save_last_used_location

        try:
            await asyncio.to_thread(write_snippet_sync, target.path, target.name, body)
            await asyncio.to_thread(
                save_last_used_location, "snippet", target.location_path
            )
            merged = await asyncio.to_thread(load_merged_config)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save snippet: {exc}",
                severity="error",
            )
            return

        verb = "Saved" if target.exists else "Created"
        self.notify(  # type: ignore[attr-defined]
            f"{verb} snippet '{target.name}' in {target.display_path}"
        )
        self._refresh_snippet_caches(merged)
        self._offer_git_commit(
            target.path,
            is_new=not target.exists,
            xprompt_name=target.name,
            noun="snippet",
            commit_type="snippet",
        )

    def _refresh_snippet_caches(self, merged: object) -> None:
        """Apply an already-loaded merged config to the in-memory caches."""
        ace_cfg = merged.get("ace", {}) if isinstance(merged, dict) else {}
        raw = ace_cfg.get("snippets", {}) if isinstance(ace_cfg, dict) else {}
        if isinstance(raw, dict):
            self._user_snippets = {
                key: value
                for key, value in raw.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        else:
            self._user_snippets = {}
        self._snippets_cache = None
        if hasattr(self, "_prompt_catalog_generation"):
            self._prompt_catalog_generation += 1
        schedule_rebuild = getattr(self, "_schedule_prompt_catalog_rebuild", None)
        if callable(schedule_rebuild):
            schedule_rebuild(reason="snippet_save", force=True)


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
