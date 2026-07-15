"""SASE self-update actions for the Config Center Updates tab."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Literal

from sase.dev_update.models import DevUpdatePlan
from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from .plugins_browser_dev_update import (
    DevUpdatePreview,
    dev_update_blocking_reason,
    dev_update_preview_details,
    dev_update_preview_summary,
)
from .plugins_browser_sase_update_summary import (
    _CORE_DIST_KEYS,
    SASE_UPDATE_NOOP_MESSAGE,
    combined_sase_update_success_message as _combined_sase_update_success_message,
    installed_version,
    load_receipt_for_summary,
    log_combined_update_result as _log_combined_update_result,
    log_update_summary as _log_update_summary,
    managed_update_changed as _managed_update_changed,
    plural as _plural,
    run_planned_sase_update_summary,
    run_sase_update_summary,
    sase_update_success_message,
)
from .plugins_browser_sase_update_tasks import (
    SaseUpdateTaskMixin,
    dev_update_reporter_runner as _dev_update_reporter_runner,
    running_background_tasks as _running_background_tasks,
)


class SaseUpdateActionsMixin(SaseUpdateTaskMixin):
    """Plan, confirm, and run ``sase update`` from the Updates tab."""

    if TYPE_CHECKING:
        _loading: bool
        _sase_update_plan_worker: Any | None
        _uv_tool: object | None
        app: Any
        screen: Any

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _make_sase_update_preview(
            self,
            receipt: object | None,
            *,
            already_refreshed_roots: Collection[str] = (),
        ) -> DevUpdatePreview: ...

        def _managed_sase_update_incoming_commits_loader(self) -> Any | None: ...

        def _dev_update_incoming_commits_loader(
            self, plan: DevUpdatePlan
        ) -> Any | None: ...

    def action_update_sase(self) -> None:
        """Run the ``u`` comprehensive update action.

        Updates the host ``sase`` package, core, and plugins. Dev/editable
        installs report no-op plans before confirmation; managed installs can
        only discover a no-op after the confirmed ``uv`` run, and surface it as
        an error toast.
        """
        self._start_sase_update_preview()

    def _start_sase_update_preview(
        self, *, already_refreshed_roots: Collection[str] = ()
    ) -> None:
        """Build the comprehensive preview, optionally reusing fresh git refs."""
        if self._loading or self._sase_update_plan_worker is not None:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return

        receipt = load_receipt_for_summary(self._uv_tool)
        fresh_roots = frozenset(already_refreshed_roots)

        def task() -> DevUpdatePreview:
            return self._make_sase_update_preview(
                receipt,
                already_refreshed_roots=fresh_roots,
            )

        self._sase_update_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="sase-update-plan"
        )

    def _on_sase_update_preview(self, preview: DevUpdatePreview | None) -> None:
        """Route a planned self-update to managed or dev confirmation."""
        if preview is None:
            return
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        if preview.plan is None:
            self._open_managed_sase_update_modal()
            return
        blocker = dev_update_blocking_reason(preview.plan)
        managed_can_proceed = bool(
            preview.managed_argv and not preview.plan.actionable_roots
        )
        if blocker is not None and not managed_can_proceed:
            self._notify(blocker, severity="error")
            return
        self._open_sase_dev_update_modal(preview)

    def _open_managed_sase_update_modal(self) -> None:
        """Open the existing managed ``uv tool upgrade sase`` confirm modal."""
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm to upgrade sase core and every installed plugin.",
            variants=[
                PluginActionVariant(
                    key="update-sase",
                    label="sase update",
                    argv=tuple(build_upgrade_all()),
                    summary="Upgrades sase core + every installed plugin",
                )
            ],
            panel_title="Confirm SASE update",
            icon="↑",
            incoming_commits_loader=self._managed_sase_update_incoming_commits_loader(),
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_sase_update_task()
            self._close_admin_center_after_sase_update()

        self.app.push_screen(modal, _on_confirmed)

    def _open_sase_dev_update_modal(self, preview: DevUpdatePreview) -> None:
        """Open the editable-checkout dev-update confirm modal."""
        assert preview.plan is not None
        plan = preview.plan
        subject = preview.subject
        mixed = bool(preview.managed_argv)
        summary = dev_update_preview_summary(plan, subject=subject)
        details = list(dev_update_preview_details(plan))
        if mixed:
            count = len(preview.managed_packages)
            summary += f"; re-resolves {count} managed {_plural(count, 'package')}"
            for package in preview.managed_packages:
                version = package.current_version or "unknown"
                details.append(f"upgrade {package.name} from {version}")
            details.append("managed reconciliation: " + " ".join(preview.managed_argv))
        modal = PluginActionConfirmModal(
            title="Update SASE" if mixed else "Update SASE dev checkouts",
            intro=(
                "Confirm to update eligible editable checkouts and reconcile "
                "managed SASE packages."
                if mixed
                else "Confirm to fetch, fast-forward, and reconcile editable "
                "SASE checkouts."
            ),
            variants=[
                PluginActionVariant(
                    key="dev-update-sase",
                    label="dev update",
                    argv=("sase", "update"),
                    summary=summary,
                    details=tuple(details),
                )
            ],
            panel_title="Confirm dev update",
            icon="↑",
            incoming_commits_loader=(
                self._managed_sase_update_incoming_commits_loader()
                if mixed
                else self._dev_update_incoming_commits_loader(plan)
            ),
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            if mixed:
                self._submit_combined_update_task(preview)
            else:
                self._submit_dev_update_task(
                    plan,
                    subject=subject,
                    display_name="sase update",
                    dedup_key="sase-update",
                    duplicate_message="A sase update is already running.",
                )
            self._close_admin_center_after_sase_update()

        self.app.push_screen(modal, _on_confirmed)

    def _close_admin_center_after_sase_update(self) -> None:
        """Dismiss the containing Admin Center after a confirmed full update.

        Once the user accepts a full SASE update the panel is no longer useful
        in the foreground: the task is already running and a successful code
        change will restart ACE. This is intentionally defensive -- it no-ops
        when the pane is detached, when its screen is not the Admin Center, or
        when dismissal races a teardown that is already in flight.
        """
        from .config_center_modal import ConfigCenterModal

        try:
            screen = self.screen
        except Exception:  # noqa: BLE001 - closing must never fail the update.
            return
        if not isinstance(screen, ConfigCenterModal):
            return
        try:
            screen.dismiss(None)
        except Exception:  # noqa: BLE001 - app may already be transitioning.
            pass


# Preserve the module's historical import and monkeypatch surface.
_SASE_UPDATE_NOOP_MESSAGE = SASE_UPDATE_NOOP_MESSAGE
_installed_version = installed_version
_load_receipt_for_summary = load_receipt_for_summary
_run_sase_update_summary = run_sase_update_summary
_run_planned_sase_update_summary = run_planned_sase_update_summary
_sase_update_success_message = sase_update_success_message
