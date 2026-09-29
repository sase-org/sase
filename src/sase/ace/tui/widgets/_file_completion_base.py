"""Shared state, panel, and candidate helpers for prompt completion."""

from __future__ import annotations

from sase.ace.tui.widgets._file_completion_base_inventories import (
    FileCompletionBaseInventoriesMixin,
)
from sase.xprompt.vcs_project_completion import build_vcs_project_completion_entries


class FileCompletionBaseMixin(FileCompletionBaseInventoriesMixin):
    """Mixin providing shared completion state helpers."""

    def _placeholder_completion_includes_common_at_empty_prefix(self) -> bool:
        """Return the empty-prefix rule for the placeholder menu that is open.

        A stray ``<`` is common in prose and code, so an automatically opened
        menu stays exactly as quiet as it is today until a prefix character
        narrows the saved group.  An explicit ``Ctrl+T`` asked for the full
        list and gets it.
        """
        return self._placeholder_completion_trigger == "manual"

    def _warm_common_placeholder_cache(self) -> None:
        """Warm saved placeholders off the mount and keystroke paths."""
        warmer = getattr(self.app, "warm_common_placeholders", None)
        if callable(warmer):
            warmer()

    def _warm_history_word_completion_cache(self) -> None:
        """Warm prompt-history words off the mount and keystroke paths."""
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        if self._prompt_completion_settings().history_word_count <= 0:
            return
        self._schedule_history_word_completion_load()

    def _warm_vcs_project_completion_catalog(self) -> None:
        """Warm the ``+`` project catalogs off the keystroke path.

        The catalog builds touch disk (project enumeration + provider
        detection), so they must never run synchronously inside key handling
        (``sase/memory/tui_perf.md``). Building once in a background thread
        populates the module-level cache in
        :mod:`sase.xprompt.vcs_project_completion` and the shared
        :mod:`sase.project_tags` snapshot, so the first valid ``+`` opens
        the menu instantly and tag prefills resolve. Gated on the real app's
        completion-settings capability so lightweight test harnesses skip it.
        """
        if getattr(self, "_vcs_project_catalog_warmed", False):
            return
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        self._vcs_project_catalog_warmed = True
        self.run_worker(
            _warm_vcs_completion_catalogs,
            name="prompt-vcs-project-catalog",
            thread=True,
        )

    def _warm_prompt_path_inventory(self) -> None:
        """Warm the prompt's base directory off the keystroke path."""
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        directory_key = self._prompt_path_directory_key()
        snapshot = self._get_warm_prompt_path_snapshot(directory_key)
        self._schedule_prompt_path_inventory_load(directory_key, snapshot)

    def _warm_model_completion_catalog(self) -> None:
        """Warm the static ``%model`` catalog off the keystroke path."""
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        self._schedule_model_completion_catalog_load()


def _warm_vcs_completion_catalogs() -> None:
    """Warm VCS project and ref-root namespace completion caches."""
    build_vcs_project_completion_entries()
    from sase.project_tags import load_project_tag_catalog

    load_project_tag_catalog()

    from sase.workspace_provider import get_workflow_names
    from sase.xprompt.vcs_ref_completion import vcs_ref_namespaces_by_workflow

    vcs_ref_namespaces_by_workflow(get_workflow_names())
