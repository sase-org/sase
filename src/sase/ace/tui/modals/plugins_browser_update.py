"""Update planning and actions for the Config Center Updates plugin browser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.ace.tui.task_subprocess import TaskReporter
from sase.dev_update.models import DevUpdatePlan
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry, PluginCatalogError
from sase.plugins.operations import (
    NotInstalled,
    NotUvTool,
    UpdateOutcome,
    UpdatePlan,
    UpdateReady,
    UpdateUnknown,
    plan_update,
)
from sase.plugins.render_common import humanize_duration
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.runner import ChangeKind

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
    entry_uses_dev_update,
)
from .plugins_browser_install import missing_plugin_message

if TYPE_CHECKING:
    from textual.worker import Worker


@dataclass(frozen=True)
class UpdatePreview:
    """Off-thread result of planning an update for the confirm-preview modal.

    *plan* is the single :class:`UpdatePlan` outcome — a terminal one
    (:class:`NotUvTool` / :class:`NotInstalled` / :class:`UpdateUnknown`) routed
    to a PatchI-matching toast, or an :class:`UpdateReady` opened in the
    confirm-preview modal. *error* carries a catalog/receipt failure message
    instead of a plan. Unlike install, update offers no source toggle, so there
    is only ever one plan.
    """

    plan: UpdatePlan | None
    error: str | None = None


def plan_update_preview(
    query: str | None, *, all_plugins: bool, offline: bool
) -> UpdatePreview:
    """Plan ``update <query>`` / ``update --all`` for the confirm-preview modal.

    Delegates to :func:`sase.plugins.operations.plan_update` — the single source
    of truth shared with the PatchI — once, cache-first (``refresh=False``). A
    catalog/receipt failure becomes a toast-able error rather than a plan.
    """
    try:
        plan = plan_update(query, all_plugins=all_plugins, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return UpdatePreview(plan=None, error=str(exc))
    return UpdatePreview(plan=plan)


def update_subject(plan: UpdateReady) -> str:
    """The human subject of a selected-plugin update."""
    return ", ".join(plan.targets)


def update_summary(plan: UpdateReady) -> str:
    """The resolved-plugin-set line shown in the confirm-preview modal.

    Mirrors the PatchI's ``update --dry-run`` "Upgrades ... (sase core stays pinned)".
    """
    return f"Upgrades {update_subject(plan)}  (sase core stays pinned)"


def update_success_message(outcome: UpdateOutcome) -> str:
    """A concise, CLI-flavored success toast: count upgraded + elapsed."""
    upgraded = sum(
        1
        for name in outcome.plan.targets
        if (change := outcome.change_set.get(name)) is not None
        and change.kind is ChangeKind.UPGRADED
    )
    if upgraded == 0:
        return "Plugins already up to date."
    plural = "plugin" if upgraded == 1 else "plugins"
    return f"Updated {upgraded} {plural} in {humanize_duration(outcome.elapsed)}"


def not_installed_message(name: str) -> str:
    """The ``update`` not-installed toast, mirroring the PatchI's wording."""
    return f"{name} is not installed. Run `sase plugin install {name}` to add it first."


class PluginUpdateActionsMixin:
    """Update actions for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _loading: bool
        _offline: bool
        _catalog: PluginCatalog | None
        _update_plan_worker: Worker[Any] | None
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _execute_update(
            self, plan: UpdateReady, *, run_fn: Any = None
        ) -> UpdateOutcome: ...

        def _make_update_preview(
            self, query: str | None, *, all_plugins: bool, offline: bool
        ) -> UpdatePreview: ...

        def _make_plugin_dev_update_preview(
            self,
            query: str | None,
            *,
            all_plugins: bool,
            receipt: object | None,
        ) -> DevUpdatePreview: ...

        def _submit_dev_update_task(
            self,
            plan: DevUpdatePlan,
            *,
            subject: str,
            display_name: str,
            dedup_key: str,
            duplicate_message: str,
        ) -> None: ...

        def _handle_code_update_completion(
            self,
            completion: TrackedTaskCompletion[Any],
            *,
            failure_prefix: str,
        ) -> None: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _dev_update_incoming_commits_loader(
            self, plan: DevUpdatePlan
        ) -> Any | None: ...

        def _plugin_update_incoming_commits_loader(
            self, plan: UpdateReady
        ) -> Any | None: ...

    def action_update(self) -> None:
        """Update the highlighted plugin (``U``) via a confirm-preview modal.

        Offered only when the selected installed plugin has an available update.
        Short-circuits with the actionable ``uv tool`` warning when mutation is
        unavailable; otherwise unavailable selections are silent no-ops because
        the hint is hidden for those rows.
        """
        if self._loading or self._update_plan_worker is not None:
            return
        entry = self._current_entry()
        if entry is None:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return
        if not entry.installed.installed or not entry.update_available:
            return
        if entry_uses_dev_update(entry):
            self._begin_plugin_dev_update_plan(entry.name, all_plugins=False)
            return
        self._begin_update_plan(entry.name, all_plugins=False)

    def _begin_update_plan(self, query: str | None, *, all_plugins: bool) -> None:
        offline = self._offline

        def task() -> UpdatePreview:
            return self._make_update_preview(
                query, all_plugins=all_plugins, offline=offline
            )

        self._update_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="plugin-update-plan"
        )

    def _begin_plugin_dev_update_plan(
        self, query: str | None, *, all_plugins: bool
    ) -> None:
        receipt = _load_dev_receipt(self._uv_tool)

        def task() -> DevUpdatePreview:
            return self._make_plugin_dev_update_preview(
                query,
                all_plugins=all_plugins,
                receipt=receipt,
            )

        self._update_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="plugin-update-plan"
        )

    def _on_update_preview(
        self, preview: UpdatePreview | DevUpdatePreview | None
    ) -> None:
        """Route a planned update to a toast (terminal) or the confirm modal."""
        if preview is None:
            return
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        plan = preview.plan
        if isinstance(plan, NotUvTool):
            self._notify(str(plan.error), severity="warning")
        elif isinstance(plan, NotInstalled):
            self._notify(not_installed_message(plan.name), severity="warning")
        elif isinstance(plan, UpdateUnknown):
            self._notify(
                missing_plugin_message(plan.query, plan.suggestions), severity="error"
            )
        elif isinstance(plan, UpdateReady):
            self._open_update_modal(plan)
        elif isinstance(preview, DevUpdatePreview):
            self._on_dev_update_preview(preview)

    def _on_dev_update_preview(self, preview: DevUpdatePreview) -> None:
        """Route a dev-update preview to a toast or confirm modal."""
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        if preview.plan is None:
            self._notify("No editable plugin update is available.")
            return
        blocker = dev_update_blocking_reason(preview.plan)
        if blocker is not None:
            self._notify(blocker, severity="warning")
            return
        self._open_dev_update_modal(preview.plan, subject=preview.subject)

    def _open_dev_update_modal(self, plan: DevUpdatePlan, *, subject: str) -> None:
        title = (
            "Update editable plugins"
            if len(plan.actionable) > 1
            else f"Update {subject}"
        )
        modal = PluginActionConfirmModal(
            title=title,
            intro="Confirm to fetch, fast-forward, and reconcile editable checkout(s).",
            variants=[
                PluginActionVariant(
                    key="dev-update",
                    label="dev update",
                    argv=("sase", "update"),
                    summary=dev_update_preview_summary(plan, subject=subject),
                    details=dev_update_preview_details(plan),
                )
            ],
            panel_title="Confirm dev update",
            icon="↑",
            incoming_commits_loader=self._dev_update_incoming_commits_loader(plan),
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            label = "editable plugins" if len(plan.actionable) > 1 else subject
            self._submit_dev_update_task(
                plan,
                subject=subject,
                display_name=f"update {label}",
                dedup_key=f"plugin-dev-update:{label}",
                duplicate_message=f"An update is already running for {label}.",
            )

        self.app.push_screen(modal, _on_confirmed)

    def _open_update_modal(self, plan: UpdateReady) -> None:
        name = plan.targets[0]
        title = f"Update {name}"
        intro = f"Confirm to upgrade {name} (sase core stays pinned)."
        variants = [
            PluginActionVariant(
                key="update",
                label="update",
                argv=tuple(plan.argv),
                summary=update_summary(plan),
                details=(
                    "ACE restarts after a successful update to load the new plugin code.",
                ),
            )
        ]
        modal = PluginActionConfirmModal(
            title=title,
            intro=intro,
            variants=variants,
            panel_title="Confirm update",
            icon="↑",
            incoming_commits_loader=self._plugin_update_incoming_commits_loader(plan),
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_update_task(plan)

        self.app.push_screen(modal, _on_confirmed)

    def _submit_update_task(self, plan: UpdateReady) -> None:
        """Run ``execute_update`` in a tracked background task (never blocks)."""

        def task(reporter: TaskReporter) -> TrackedTaskResult[UpdateOutcome]:
            try:
                label = plan.targets[0]
                reporter.phase(f"Updating {label}")
                outcome = self._execute_update(plan, run_fn=reporter.uv_runner())
            except UvToolError as exc:
                return TrackedTaskResult(
                    success=False, message=str(exc), error=str(exc)
                )
            message = update_success_message(outcome)
            reporter.log(message, stream="result")
            return TrackedTaskResult(
                success=True,
                message=message,
                payload=outcome,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        label = plan.targets[0]
        submit(
            "plugin-update",
            label,
            "",
            task,
            display_name=f"update {label}",
            dedup_key=f"plugin-update:{label}",
            duplicate_message=f"An update is already running for {label}.",
            on_complete=self._on_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_update_complete(
        self, completion: TrackedTaskCompletion[UpdateOutcome]
    ) -> None:
        """Toast/restart after update; no-op updates refresh in place."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="Update failed",
        )


_UpdatePreview = UpdatePreview
_plan_update_preview = plan_update_preview
_update_subject = update_subject
_update_summary = update_summary
_update_success_message = update_success_message
_not_installed_message = not_installed_message


def _load_dev_receipt(install: object | None) -> object | None:
    from .plugins_browser_sase_update import load_receipt_for_summary

    return load_receipt_for_summary(install)
