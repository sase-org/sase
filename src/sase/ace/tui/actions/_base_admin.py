"""Admin Center and related panel actions for sase's TUI app."""

from __future__ import annotations

from typing import Any

from ._base_types import BaseActionsHost


class BaseAdminActionsMixin(BaseActionsHost):
    """Mixin providing Admin Center, logs, and provider-usage actions."""

    def action_open_projects_panel(self) -> None:
        """Open the SASE Admin Center on the Projects tab.

        Replaces the removed ``,p`` standalone project-management modal: the
        project lifecycle manager now lives in the Admin Center's Projects
        tab, so this fast path opens that modal pre-focused on Projects.
        """
        self._open_config_center("projects")

    def action_open_log_panel(self) -> None:
        """Open the SASE Admin Center on the Logs tab."""
        self._open_config_center("logs")

    def action_open_machines_panel(self) -> None:
        """Open the SASE Admin Center on the Machines tab."""
        self._open_config_center("machines")

    def action_jump_to_last_error(self) -> None:
        """Open the Logs tab on this session's most recent registered error."""
        from sase.logs import last_registered_error

        error = last_registered_error()
        if error is None:
            self.notify(  # type: ignore[attr-defined]
                "No error registered in this ACE session"
            )
        self._open_config_center("logs", log_error_target=error)

    def action_open_tasks_panel(self) -> None:
        """Open the SASE Admin Center on the Tasks tab."""
        self._open_config_center("procs")

    def action_open_statistics_panel(self) -> None:
        """Open the SASE Admin Center on the Statistics tab."""
        self._open_config_center("statistics")

    def action_open_provider_usage(self, provider: str | None = None) -> None:
        """Open the read-only Providers · Usage view."""
        from ..modals.models_panel_usage_modal import ProviderUsageModal
        from ..widgets.provider_usage_indicator import ProviderUsageIndicator

        initial = provider or None
        if not initial:
            try:
                indicator = self.query_one(  # type: ignore[attr-defined]
                    "#provider-usage-indicator",
                    ProviderUsageIndicator,
                )
            except Exception:
                indicator = None
            if indicator is not None:
                initial = indicator.usage_open_provider
        self.push_screen(  # type: ignore[attr-defined]
            ProviderUsageModal(initial_provider=initial or None)
        )

    def action_open_updates_panel(self) -> None:
        """Open the SASE Admin Center on the Updates tab."""
        self._open_config_center("updates")

    def action_open_update_procs(self) -> None:
        """Open the Admin Center Procs tab on the oldest running update."""
        from .._proc_observer_models import proc_gear_lanes
        from ..modals.config_center_session import (
            AdminCenterSessionState,
            SelectionBookmark,
        )

        try:
            projection_fn = getattr(self, "_effective_proc_projection", None)
            lanes = (
                proc_gear_lanes(projection_fn()) if callable(projection_fn) else None
            )
        except Exception:
            lanes = None
        if lanes is not None and lanes.update_rows:
            row = lanes.update_rows[0]
            session_state = getattr(self, "_admin_center_session_state", None)
            if not isinstance(session_state, AdminCenterSessionState):
                session_state = AdminCenterSessionState()
                self._admin_center_session_state = session_state
            session_state.procs.task = SelectionBookmark(
                identity=row.durable_proc_id or row.proc_id
            )
        self._open_config_center("procs")

    def action_open_config_center(self) -> None:
        """Open the SASE Admin Center on its lightweight home view."""
        self._open_config_center(None)

    def _open_config_center(
        self,
        initial_tab: Any,
        *,
        log_error_target: Any = None,
        config_entry: Any = None,
        on_dismissed: Any = None,
        proc_focus_target: str | None = None,
    ) -> None:
        """Open the SASE Admin Center and refresh updates state on dismiss."""
        from ..modals.config_center_modal import (
            ConfigCenterModal,
            validated_center_tab,
        )
        from ..modals.config_center_session import AdminCenterSessionState

        registry = getattr(self, "_keymap_registry", None)
        app_keymaps = getattr(registry, "app", None)
        opener_binding = getattr(app_keymaps, "open_config_center", "number_sign")
        resume_tab = validated_center_tab(getattr(self, "_last_admin_center_tab", None))
        history = getattr(self, "_admin_center_history", None)
        alternate_tab = validated_center_tab(
            history.alternate if history is not None else None
        )
        session_state = getattr(self, "_admin_center_session_state", None)
        if not isinstance(session_state, AdminCenterSessionState):
            session_state = AdminCenterSessionState()
            self._admin_center_session_state = session_state

        def _callback(result: object | None = None) -> None:
            self._on_config_center_dismissed(result)
            if on_dismissed is not None:
                on_dismissed(result)

        self.push_screen(  # type: ignore[attr-defined]
            ConfigCenterModal(
                initial_tab=initial_tab,
                resume_tab=resume_tab,
                alternate_tab=alternate_tab,
                opener_binding=opener_binding,
                log_error_target=log_error_target,
                session_state=session_state,
                on_tab_activated=self._on_admin_center_tab_activated,  # type: ignore[attr-defined]
                config_entry=config_entry,
                proc_focus_target=proc_focus_target,
            ),
            _callback,
        )

    def _on_config_center_dismissed(self, result: object | None = None) -> None:
        from ..modals.config_center_modal import validated_center_tab

        active_tab = validated_center_tab(result)
        if active_tab is not None:
            # Successful activation normally records this before dismissal.
            # Keep the result as an idempotent fallback for narrow callers.
            self._remember_admin_center_tab(active_tab)  # type: ignore[attr-defined]
        refresh = getattr(self, "_schedule_updates_indicator_revalidation", None)
        if callable(refresh):
            refresh()
