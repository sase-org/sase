"""Patch onboarding visibility glue."""

from __future__ import annotations

from typing import Any

from .._widget_visibility import set_widget_hidden


class PatchOnboardingMixin:
    """Mixin for toggling the PRs-tab empty-state onboarding panel."""

    _patches_first_load_done: bool
    _all_patches: list[Any]
    patches: list[Any]

    def _should_show_patches_onboarding(self) -> bool:
        """Return True when the PRs tab has no filtered rows to show."""
        if not getattr(self, "_patches_first_load_done", False):
            return False
        return not bool(getattr(self, "patches", []))

    def _sync_patches_onboarding(self) -> bool:
        """Toggle the PRs empty-state onboarding panel.

        Returns True when onboarding is visible and callers should skip normal
        list/detail rendering.
        """
        from textual.css.query import NoMatches

        from ...widgets import TabQuickStart

        show_onboarding = self._should_show_patches_onboarding()
        query_one = getattr(self, "query_one", None)
        if not callable(query_one):
            return False

        try:
            view = query_one("#artifacts-view")
            quickstart = query_one("#patch-quickstart-panel", TabQuickStart)
        except (NoMatches, LookupError):
            return False

        views = [view]
        try:
            views.append(query_one("#changespecs-view"))  # legacy compatibility alias
        except (NoMatches, LookupError):
            pass

        set_widget_hidden(quickstart, not show_onboarding)
        for item in views:
            self._set_patches_onboarding_layout(item, show_onboarding)
        if not show_onboarding:
            return False

        registry = getattr(self, "_keymap_registry", None)
        quickstart.set_no_match_context(len(getattr(self, "_all_patches", [])))
        if registry is not None:
            quickstart.set_keymap_registry(registry)
        else:
            quickstart.refresh_content()
        return True

    @staticmethod
    def _set_patches_onboarding_layout(view: object, active: bool) -> None:
        """Collapse the PRs-tab chrome while onboarding is visible."""
        if active:
            add_class = getattr(view, "add_class", None)
            if callable(add_class):
                add_class("-onboarding-active")
        else:
            remove_class = getattr(view, "remove_class", None)
            if callable(remove_class):
                remove_class("-onboarding-active")
