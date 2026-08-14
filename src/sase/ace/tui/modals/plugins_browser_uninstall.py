"""Uninstall planning and actions for the Config Center Updates plugin browser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.proc_subprocess import ProcReporter
from sase.plugins.catalog import PluginCatalogEntry, PluginCatalogError
from sase.plugins.operations import (
    AlreadyAbsent,
    NotUvTool,
    UninstallOutcome,
    UninstallPlan,
    UninstallReady,
    UninstallUnknown,
    plan_uninstall,
)
from sase.plugins.render_common import humanize_duration
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError

from .confirm_dialog import ConfirmKind
from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from .plugins_browser_install import missing_plugin_message

if TYPE_CHECKING:
    from textual.worker import Worker


@dataclass(frozen=True)
class UninstallPreview:
    """Off-thread result of planning an uninstall for the confirm-preview modal.

    *plan* is the single :class:`UninstallPlan` outcome — a terminal one
    (:class:`NotUvTool` / :class:`AlreadyAbsent` / :class:`UninstallUnknown`)
    routed to a PatchI-matching toast, or an :class:`UninstallReady` opened in the
    confirm-preview modal. *error* carries a catalog/receipt failure message
    instead of a plan. Like update, uninstall offers no source toggle, so there
    is only ever one plan.
    """

    plan: UninstallPlan | None
    error: str | None = None


def plan_uninstall_preview(query: str, *, offline: bool) -> UninstallPreview:
    """Plan ``uninstall <query>`` for the confirm-preview modal.

    Delegates to :func:`sase.plugins.operations.plan_uninstall` — the single
    source of truth shared with the PatchI — once, cache-first (``refresh=False``).
    A catalog/receipt failure becomes a toast-able error rather than a plan.
    """
    try:
        plan = plan_uninstall(query, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return UninstallPreview(plan=None, error=str(exc))
    return UninstallPreview(plan=plan)


def uninstall_summary(plan: UninstallReady) -> str:
    """The resolved-plugin-set line shown in the confirm-preview modal.

    Mirrors the PatchI's ``uninstall --dry-run`` "Removes ... (other plugins stay
    installed)".
    """
    return f"Removes {plan.display_name}  (other plugins stay installed)"


def uninstall_success_message(outcome: UninstallOutcome) -> str:
    """A concise, CLI-flavored success toast: name + elapsed."""
    return (
        f"Uninstalled {outcome.plan.display_name} "
        f"in {humanize_duration(outcome.elapsed)}"
    )


def already_absent_message(name: str) -> str:
    """The ``uninstall`` already-absent toast, mirroring the PatchI's wording."""
    return f"{name} is not installed — nothing to uninstall."


class PluginUninstallActionsMixin:
    """Uninstall actions for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _loading: bool
        _offline: bool
        _uninstall_plan_worker: Worker[Any] | None
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _execute_uninstall(
            self, plan: UninstallReady, *, run_fn: Any = None
        ) -> UninstallOutcome: ...

        def _make_uninstall_preview(
            self, query: str, *, offline: bool
        ) -> UninstallPreview: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _handle_code_update_completion(
            self,
            completion: TrackedProcCompletion[Any],
            *,
            failure_prefix: str,
        ) -> None: ...

    def action_uninstall(self) -> None:
        """Uninstall the highlighted plugin (``x``) via a confirm-preview modal.

        Offered only for an *installed* plugin. Short-circuits with the PatchI's
        actionable message when sase is not a managed ``uv tool`` install or the
        highlighted plugin is not installed, then plans the uninstall off-thread
        and opens the confirm-preview modal; the ``uv`` re-install (minus the
        target) runs later, in a tracked background task, only if confirmed.
        """
        if self._loading or self._uninstall_plan_worker is not None:
            return
        entry = self._current_entry()
        if entry is None:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return
        if not entry.installed.installed:
            self._notify(already_absent_message(entry.name), severity="warning")
            return
        self._begin_uninstall_plan(entry.name)

    def _begin_uninstall_plan(self, query: str) -> None:
        offline = self._offline

        def task() -> UninstallPreview:
            return self._make_uninstall_preview(query, offline=offline)

        self._uninstall_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="plugin-uninstall-plan"
        )

    def _on_uninstall_preview(self, preview: UninstallPreview | None) -> None:
        """Route a planned uninstall to a toast (terminal) or the confirm modal."""
        if preview is None:
            return
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        plan = preview.plan
        if isinstance(plan, NotUvTool):
            self._notify(str(plan.error), severity="warning")
        elif isinstance(plan, AlreadyAbsent):
            self._notify(already_absent_message(plan.name))
        elif isinstance(plan, UninstallUnknown):
            self._notify(
                missing_plugin_message(plan.query, plan.suggestions), severity="error"
            )
        elif isinstance(plan, UninstallReady):
            self._open_uninstall_modal(plan)

    def _open_uninstall_modal(self, plan: UninstallReady) -> None:
        name = plan.display_name
        variants = [
            PluginActionVariant(
                key="uninstall",
                label="uninstall",
                argv=tuple(plan.argv),
                summary=uninstall_summary(plan),
                details=(
                    "ACE restarts after a successful uninstall to unload the plugin.",
                ),
            )
        ]
        modal = PluginActionConfirmModal(
            title=f"Uninstall {name}",
            intro=f"Confirm to remove {name} from sase's uv tool environment.",
            variants=variants,
            panel_title="Confirm uninstall",
            kind=ConfirmKind.DANGER,
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_uninstall_task(plan)

        self.app.push_screen(modal, _on_confirmed)

    def _submit_uninstall_task(self, plan: UninstallReady) -> None:
        """Run ``execute_uninstall`` in a tracked background task (never blocks)."""

        def task(reporter: ProcReporter) -> TrackedProcResult[UninstallOutcome]:
            try:
                reporter.phase(f"Uninstalling {plan.display_name}")
                outcome = self._execute_uninstall(plan, run_fn=reporter.uv_runner())
            except UvToolError as exc:
                return TrackedProcResult(
                    success=False, message=str(exc), error=str(exc)
                )
            message = uninstall_success_message(outcome)
            reporter.log(message, stream="result")
            return TrackedProcResult(
                success=True,
                message=message,
                payload=outcome,
            )

        submit = getattr(self.app, "_submit_tracked_proc", None)
        if submit is None:
            return
        name = plan.display_name
        submit(
            "plugin-uninstall",
            name,
            "",
            task,
            display_name=f"uninstall {name}",
            dedup_key=f"plugin-uninstall:{name}",
            duplicate_message=f"An uninstall is already running for {name}.",
            on_complete=self._on_uninstall_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_uninstall_complete(
        self, completion: TrackedProcCompletion[UninstallOutcome]
    ) -> None:
        """Toast/restart after uninstall; no-op uninstalls refresh in place."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="Uninstall failed",
        )


_UninstallPreview = UninstallPreview
_plan_uninstall_preview = plan_uninstall_preview
_uninstall_summary = uninstall_summary
_uninstall_success_message = uninstall_success_message
_already_absent_message = already_absent_message
