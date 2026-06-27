"""Snippet save flow for prompt-bar drafts."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.actions.agent_workflow._types import PromptContext

from ._prompt_bar_save_xprompt_git import PromptBarSaveXpromptGitMixin
from ._prompt_bar_save_xprompt_tasks import PromptBarSaveXpromptTaskMixin


class PromptBarSaveSnippetMixin(
    PromptBarSaveXpromptTaskMixin,
    PromptBarSaveXpromptGitMixin,
):
    """Handle saving the active prompt pane as an ACE snippet."""

    _prompt_context: PromptContext | None
    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None

    async def _create_snippet_flow(self, body: str) -> None:
        import asyncio

        from ...modals import (
            SnippetConfigLocation,
            SnippetConfigLocationModal,
            load_snippet_config_locations,
        )

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )
        locations = await asyncio.to_thread(load_snippet_config_locations, project)
        if not any(location.is_selectable for location in locations):
            self.notify(  # type: ignore[attr-defined]
                "No writable config file available to store a snippet",
                severity="warning",
            )
            return

        def _on_location(location: SnippetConfigLocation | None) -> None:
            if location is None:
                return
            self._spawn_xprompt_save_task(self._ask_snippet_name(location, body))

        self.push_screen(  # type: ignore[attr-defined]
            SnippetConfigLocationModal(locations),
            _on_location,
        )

    async def _ask_snippet_name(
        self,
        location: object,
        body: str,
    ) -> None:
        import asyncio

        from ...modals import SnippetConfigLocation, SnippetNameModal

        assert isinstance(location, SnippetConfigLocation)
        existing_names = await asyncio.to_thread(existing_snippet_names, location.path)

        def _on_name(name: str | None) -> None:
            if name is None:
                return
            self._spawn_xprompt_save_task(self._write_snippet(location, name, body))

        self.push_screen(  # type: ignore[attr-defined]
            SnippetNameModal(
                config_path=location.path,
                display_path=location.display_path,
                existing_names=existing_names,
            ),
            _on_name,
        )

    async def _write_snippet(
        self,
        location: object,
        name: str,
        body: str,
    ) -> None:
        import asyncio

        from ...modals import SnippetConfigLocation

        assert isinstance(location, SnippetConfigLocation)
        try:
            await asyncio.to_thread(write_snippet_sync, location.path, name, body)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save snippet: {exc}",
                severity="error",
            )
            return

        self.notify(  # type: ignore[attr-defined]
            f"Created snippet '{name}' in {location.display_path}"
        )
        self._refresh_snippet_caches()
        self._offer_git_commit(
            location.path,
            is_new=True,
            xprompt_name=name,
            noun="snippet",
            commit_type="snippet",
        )

    def _refresh_snippet_caches(self) -> None:
        """Reload merged ``ace.snippets`` and drop the resolved snippet cache.

        The merged-config cache invalidates itself by file mtime, so re-reading
        it after the write picks up the new entry; we then refresh the app's
        ``_user_snippets`` and clear ``_snippets_cache`` so the next
        ``get_snippets()`` rebuilds with the new template.
        """
        from sase.config import load_merged_config

        merged = load_merged_config()
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


def existing_snippet_names(config_path: str) -> set[str]:
    """Return the snippet triggers defined in *config_path* only.

    Reads ``ace.snippets`` from the single selected YAML file (not the merged
    config) so the name modal's "already defined" warning and overwrite behavior
    reflect what writing to this file would actually replace.
    """
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
