"""ChangeSpec onboarding visibility glue."""

from __future__ import annotations

from typing import Any

from .._widget_visibility import set_widget_hidden, widget_has_class


class ChangeSpecOnboardingMixin:
    """Mixin for toggling the PRs-tab empty-state onboarding panel."""

    _changespecs_first_load_done: bool
    _all_changespecs: list[Any]
    _saved_queries: dict[str, str]

    def _should_show_changespecs_onboarding(self) -> bool:
        """Return True when the PRs tab should show first-use onboarding."""
        if not getattr(self, "_changespecs_first_load_done", False):
            return False
        if getattr(self, "_all_changespecs", []):
            return False
        return not bool(getattr(self, "_saved_queries", {}))

    def _sync_changespecs_onboarding(self) -> bool:
        """Toggle the PRs empty-state onboarding panel.

        Returns True when onboarding is visible and callers should skip normal
        list/detail/search rendering.
        """
        from textual.css.query import NoMatches

        from ...widgets import ChangeSpecOnboarding

        show_onboarding = self._should_show_changespecs_onboarding()
        query_one = getattr(self, "query_one", None)
        if not callable(query_one):
            return False

        view: Any | None = None
        if not show_onboarding:
            try:
                view = query_one("#changespecs-view")
            except (NoMatches, LookupError):
                return False
            if not widget_has_class(view, "-onboarding-active"):
                return False

        try:
            if view is None:
                view = query_one("#changespecs-view")
            onboarding = query_one("#changespec-onboarding-panel", ChangeSpecOnboarding)
        except (NoMatches, LookupError):
            return False

        set_widget_hidden(onboarding, not show_onboarding)
        self._set_changespecs_onboarding_layout(view, show_onboarding)
        if not show_onboarding:
            return False

        registry = getattr(self, "_keymap_registry", None)
        if registry is not None:
            onboarding.set_keymap_registry(registry)
        else:
            onboarding.refresh_content()
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
