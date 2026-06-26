"""Update planning and actions for the Config Center Plugins browser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.plugins.catalog import PluginCatalogEntry, PluginCatalogError
from sase.plugins.operations import (
    NoPlugins,
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
from .plugins_browser_install import missing_plugin_message

if TYPE_CHECKING:
    from textual.worker import Worker


@dataclass(frozen=True)
class UpdatePreview:
    """Off-thread result of planning an update for the confirm-preview modal.

    *plan* is the single :class:`UpdatePlan` outcome — a terminal one
    (:class:`NotUvTool` / :class:`NoPlugins` / :class:`NotInstalled` /
    :class:`UpdateUnknown`) routed to a CLI-matching toast, or an
    :class:`UpdateReady` opened in the confirm-preview modal. *error* carries a
    catalog/receipt failure message instead of a plan. Unlike install, update
    offers no source toggle, so there is only ever one plan.
    """

    plan: UpdatePlan | None
    error: str | None = None


def plan_update_preview(
    query: str | None, *, all_plugins: bool, offline: bool
) -> UpdatePreview:
    """Plan ``update <query>`` / ``update --all`` for the confirm-preview modal.

    Delegates to :func:`sase.plugins.operations.plan_update` — the single source
    of truth shared with the CLI — once, cache-first (``refresh=False``). A
    catalog/receipt failure becomes a toast-able error rather than a plan.
    """
    try:
        plan = plan_update(query, all_plugins=all_plugins, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return UpdatePreview(plan=None, error=str(exc))
    return UpdatePreview(plan=plan)


def update_subject(plan: UpdateReady) -> str:
    """The human subject of an update: 'every installed plugin' or the names."""
    if plan.all_plugins:
        return "every installed plugin"
    return ", ".join(plan.targets)


def update_summary(plan: UpdateReady) -> str:
    """The resolved-plugin-set line shown in the confirm-preview modal.

    Mirrors the CLI's ``update --dry-run`` "Upgrades ... (sase core stays pinned)".
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
    """The ``update`` not-installed toast, mirroring the CLI's wording."""
    return f"{name} is not installed. Run `sase plugin install {name}` to add it first."


def no_plugins_message() -> str:
    """The ``update --all`` no-plugins toast, mirroring the CLI's wording."""
    return "No plugins are installed. Run `sase plugin list` to discover plugins."


class PluginUpdateActionsMixin:
    """Update actions for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _loading: bool
        _offline: bool
        _update_plan_worker: Worker[Any] | None
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _execute_update(self, plan: UpdateReady) -> UpdateOutcome: ...

        def _make_update_preview(
            self, query: str | None, *, all_plugins: bool, offline: bool
        ) -> UpdatePreview: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

    def action_update(self) -> None:
        """Update the highlighted plugin (``u``) via a confirm-preview modal.

        Offered only for an *installed* plugin. Short-circuits with the CLI's
        actionable message when sase is not a managed ``uv tool`` install or the
        highlighted plugin is not installed, then plans the update off-thread and
        opens the confirm-preview modal; the ``uv`` upgrade runs later, in a
        tracked background task, only if the user confirms.
        """
        if self._loading or self._update_plan_worker is not None:
            return
        entry = self._current_entry()
        if entry is None:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return
        if not entry.installed.installed:
            self._notify(not_installed_message(entry.name), severity="warning")
            return
        self._begin_update_plan(entry.name, all_plugins=False)

    def action_update_all(self) -> None:
        """Update every installed plugin (``U``) via a confirm-preview modal.

        Short-circuits with the CLI's actionable message when sase is not a
        managed ``uv tool`` install; the no-plugins case is reported from the
        plan (the receipt, not the catalog, is the source of truth).
        """
        if self._loading or self._update_plan_worker is not None:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return
        self._begin_update_plan(None, all_plugins=True)

    def _begin_update_plan(self, query: str | None, *, all_plugins: bool) -> None:
        offline = self._offline

        def task() -> UpdatePreview:
            return self._make_update_preview(
                query, all_plugins=all_plugins, offline=offline
            )

        self._update_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="plugin-update-plan"
        )

    def _on_update_preview(self, preview: UpdatePreview | None) -> None:
        """Route a planned update to a toast (terminal) or the confirm modal."""
        if preview is None:
            return
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        plan = preview.plan
        if isinstance(plan, NotUvTool):
            self._notify(str(plan.error), severity="warning")
        elif isinstance(plan, NoPlugins):
            self._notify(no_plugins_message())
        elif isinstance(plan, NotInstalled):
            self._notify(not_installed_message(plan.name), severity="warning")
        elif isinstance(plan, UpdateUnknown):
            self._notify(
                missing_plugin_message(plan.query, plan.suggestions), severity="error"
            )
        elif isinstance(plan, UpdateReady):
            self._open_update_modal(plan)

    def _open_update_modal(self, plan: UpdateReady) -> None:
        if plan.all_plugins:
            title = "Update all plugins"
            intro = (
                "Confirm to upgrade every installed plugin (sase core stays pinned)."
            )
        else:
            name = plan.targets[0]
            title = f"Update {name}"
            intro = f"Confirm to upgrade {name} (sase core stays pinned)."
        variants = [
            PluginActionVariant(
                key="update",
                label="update",
                argv=tuple(plan.argv),
                summary=update_summary(plan),
            )
        ]
        modal = PluginActionConfirmModal(
            title=title,
            intro=intro,
            variants=variants,
            panel_title="Confirm update",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_update_task(plan)

        self.app.push_screen(modal, _on_confirmed)

    def _submit_update_task(self, plan: UpdateReady) -> None:
        """Run ``execute_update`` in a tracked background task (never blocks)."""

        def task() -> TrackedTaskResult[UpdateOutcome]:
            try:
                outcome = self._execute_update(plan)
            except UvToolError as exc:
                return TrackedTaskResult(
                    success=False, message=str(exc), error=str(exc)
                )
            return TrackedTaskResult(
                success=True,
                message=update_success_message(outcome),
                payload=outcome,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        label = "all plugins" if plan.all_plugins else plan.targets[0]
        dedup = "plugin-update:all" if plan.all_plugins else f"plugin-update:{label}"
        submit(
            "plugin-update",
            label,
            "",
            task,
            display_name=f"update {label}",
            dedup_key=dedup,
            duplicate_message=f"An update is already running for {label}.",
            on_complete=self._on_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_update_complete(
        self, completion: TrackedTaskCompletion[UpdateOutcome]
    ) -> None:
        """Toast the CLI-matching outcome and refresh the row(s) in place."""
        if completion.success:
            self._notify(completion.message)
            # Re-merge installed state so upgraded rows reflect the new version.
            if self.is_mounted and not self._loading:
                self._start_load(force=False)
        else:
            detail = completion.error or completion.message
            self._notify(f"Update failed: {detail}", severity="error")


_UpdatePreview = UpdatePreview
_plan_update_preview = plan_update_preview
_update_subject = update_subject
_update_summary = update_summary
_update_success_message = update_success_message
_not_installed_message = not_installed_message
_no_plugins_message = no_plugins_message
