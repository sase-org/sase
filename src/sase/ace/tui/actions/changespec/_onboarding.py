"""ChangeSpec onboarding visibility glue."""

from __future__ import annotations

from typing import Any

from .._widget_visibility import set_widget_hidden


class ChangeSpecOnboardingMixin:
    """Mixin for toggling the PRs-tab empty-state onboarding panel."""

    _changespecs_first_load_done: bool
    _all_changespecs: list[Any]
    changespecs: list[Any]

    def _should_show_changespecs_onboarding(self) -> bool:
        """Return True when the PRs tab has no filtered rows to show."""
        if not getattr(self, "_changespecs_first_load_done", False):
            return False
        return not bool(getattr(self, "changespecs", []))

    def _sync_changespecs_onboarding(self) -> bool:
        """Toggle the PRs empty-state onboarding panel.

        Returns True when onboarding is visible and callers should skip normal
        list/detail rendering.
        """
        from textual.css.query import NoMatches

        from ...widgets import TabQuickStart

        show_onboarding = self._should_show_changespecs_onboarding()
        query_one = getattr(self, "query_one", None)
        if not callable(query_one):
            return False

        try:
            view = query_one("#changespecs-view")
            quickstart = query_one("#changespec-quickstart-panel", TabQuickStart)
        except (NoMatches, LookupError):
            return False

        set_widget_hidden(quickstart, not show_onboarding)
        self._set_changespecs_onboarding_layout(view, show_onboarding)
        if not show_onboarding:
            return False

        registry = getattr(self, "_keymap_registry", None)
        quickstart.set_no_match_context(len(getattr(self, "_all_changespecs", [])))
        if registry is not None:
            quickstart.set_keymap_registry(registry)
        else:
            quickstart.refresh_content()
        return True

    @staticmethod
    def _set_changespecs_onboarding_layout(view: object, active: bool) -> None:
        """Collapse the PRs-tab chrome while onboarding is visible."""
        if active:
            add_class = getattr(view, "add_class", None)
            if callable(add_class):
                add_class("-onboarding-active")
        else:
            remove_class = getattr(view, "remove_class", None)
            if callable(remove_class):
                remove_class("-onboarding-active")
