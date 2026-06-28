"""Install planning and actions for the Config Center Updates plugin browser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.ace.tui.task_subprocess import TaskReporter
from sase.plugins.catalog import PluginCatalogEntry, PluginCatalogError
from sase.plugins.operations import (
    AlreadyInstalled,
    InstallNotFound,
    InstallOutcome,
    InstallPlan,
    InstallReady,
    NotUvTool,
    plan_install,
)
from sase.plugins.render_common import humanize_duration
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)

if TYPE_CHECKING:
    from textual.worker import Worker


@dataclass(frozen=True)
class InstallPreview:
    """Off-thread result of planning an install for the confirm-preview modal.

    *index_plan* is the primary plan (install from the index, ``git=False``):
    either a terminal outcome (:class:`NotUvTool` / :class:`InstallNotFound` /
    :class:`AlreadyInstalled`) or an :class:`InstallReady`. *git_plan* is the
    optional git-source variant (present only when the index plan is ready and
    the git plan also resolves), so the modal's toggle stays pure presentation.
    *error* carries a catalog/receipt failure message instead of a plan.
    """

    index_plan: InstallPlan | None
    git_plan: InstallReady | None = None
    error: str | None = None


def plan_install_preview(name: str, *, offline: bool) -> InstallPreview:
    """Plan ``install <name>`` (index, then git) for the confirm-preview modal.

    Delegates to :func:`sase.plugins.operations.plan_install` — the single
    source of truth shared with the CLI — once per source. Cache-first
    (``refresh=False``); the optional git variant is only resolved when the
    index plan is ready, so a terminal outcome short-circuits the second load.
    """
    try:
        index_plan = plan_install(name, git=False, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return InstallPreview(index_plan=None, error=str(exc))

    git_plan: InstallReady | None = None
    if isinstance(index_plan, InstallReady):
        try:
            candidate = plan_install(name, git=True, offline=offline)
        except (PluginCatalogError, ReceiptError):
            candidate = None
        if isinstance(candidate, InstallReady):
            git_plan = candidate
    return InstallPreview(index_plan=index_plan, git_plan=git_plan)


def install_summary(plan: InstallReady) -> str:
    """The resolved-plugin-set line shown in the confirm-preview modal."""
    return f"Installs {plan.spec.display_name}  (from {plan.spec.source})"


def install_success_message(outcome: InstallOutcome) -> str:
    """A concise, CLI-flavored success toast: name + new version + elapsed."""
    spec = outcome.plan.spec
    change = outcome.change_set.get(spec.requirement.name)
    version = change.new_version if change is not None else None
    suffix = f" v{version}" if version else ""
    return (
        f"Installed {spec.display_name}{suffix} in {humanize_duration(outcome.elapsed)}"
    )


def missing_plugin_message(
    query: str, suggestions: tuple[PluginCatalogEntry, ...]
) -> str:
    """The not-found toast, mirroring the CLI's ranked-suggestions wording."""
    if suggestions:
        names = ", ".join(entry.name for entry in suggestions)
        return f"No plugin named '{query}' in the catalog. Did you mean: {names}?"
    return f"No plugin named '{query}' in the catalog."


def install_not_found_message(plan: InstallNotFound) -> str:
    """The install not-found toast (shared wording with ``update``)."""
    return missing_plugin_message(plan.query, plan.suggestions)


class PluginInstallActionsMixin:
    """Install actions for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _loading: bool
        _offline: bool
        _plan_worker: Worker[Any] | None
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _execute_install(
            self, plan: InstallReady, *, run_fn: Any = None
        ) -> InstallOutcome: ...

        def _make_install_preview(
            self, name: str, *, offline: bool
        ) -> InstallPreview: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

    def action_install(self) -> None:
        """Install the highlighted plugin (``i``) via a confirm-preview modal.

        Offered only for a *not-installed* plugin. Short-circuits with the CLI's
        actionable message when sase is not a managed ``uv tool`` install, then
        plans the install off-thread (so a cache read never blocks the UI) and
        opens the confirm-preview modal; the actual ``uv`` run happens later, in
        a tracked background task, only if the user confirms.
        """
        if self._loading or self._plan_worker is not None:
            return
        entry = self._current_entry()
        if entry is None:
            return
        if entry.installed.installed:
            self._notify(f"{entry.name} is already installed.")
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return
        self._begin_install_plan(entry.name)

    def _begin_install_plan(self, name: str) -> None:
        offline = self._offline

        def task() -> InstallPreview:
            return self._make_install_preview(name, offline=offline)

        self._plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="plugin-plan"
        )

    def _on_install_preview(self, preview: InstallPreview | None) -> None:
        """Route a planned install to a toast (terminal) or the confirm modal."""
        if preview is None:
            return
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        plan = preview.index_plan
        if isinstance(plan, NotUvTool):
            self._notify(str(plan.error), severity="warning")
        elif isinstance(plan, InstallNotFound):
            self._notify(install_not_found_message(plan), severity="error")
        elif isinstance(plan, AlreadyInstalled):
            self._notify(f"{plan.spec.display_name} is already installed.")
        elif isinstance(plan, InstallReady):
            self._open_install_modal(plan, preview.git_plan)

    def _open_install_modal(
        self, index_plan: InstallReady, git_plan: InstallReady | None
    ) -> None:
        plans: dict[str, InstallReady] = {"index": index_plan}
        variants = [
            PluginActionVariant(
                key="index",
                label="from index",
                argv=tuple(index_plan.argv),
                summary=install_summary(index_plan),
            )
        ]
        if git_plan is not None:
            plans["git"] = git_plan
            variants.append(
                PluginActionVariant(
                    key="git",
                    label="from git",
                    argv=tuple(git_plan.argv),
                    summary=install_summary(git_plan),
                )
            )
        name = index_plan.spec.display_name
        modal = PluginActionConfirmModal(
            title=f"Install {name}",
            intro=f"Confirm to install {name} into sase's uv tool environment.",
            variants=variants,
            panel_title="Confirm install",
            icon="↓",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_install_task(name, plans.get(result.variant_key, index_plan))

        self.app.push_screen(modal, _on_confirmed)

    def _submit_install_task(self, name: str, plan: InstallReady) -> None:
        """Run ``execute_install`` in a tracked background task (never blocks)."""

        def task(reporter: TaskReporter) -> TrackedTaskResult[InstallOutcome]:
            try:
                reporter.phase(f"Installing {name}")
                outcome = self._execute_install(plan, run_fn=reporter.uv_runner())
            except UvToolError as exc:
                return TrackedTaskResult(
                    success=False, message=str(exc), error=str(exc)
                )
            message = install_success_message(outcome)
            reporter.log(message, stream="result")
            return TrackedTaskResult(
                success=True,
                message=message,
                payload=outcome,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        submit(
            "plugin-install",
            name,
            "",
            task,
            display_name=f"install {name}",
            dedup_key=f"plugin-install:{name}",
            duplicate_message=f"An install is already running for {name}.",
            on_complete=self._on_install_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_install_complete(
        self, completion: TrackedTaskCompletion[InstallOutcome]
    ) -> None:
        """Toast the CLI-matching outcome and refresh the row in place."""
        if completion.success:
            self._notify(completion.message)
            # Re-merge installed state so the freshly-installed row flips to *.
            if self.is_mounted and not self._loading:
                self._start_load(force=False)
        else:
            detail = completion.error or completion.message
            self._notify(f"Install failed: {detail}", severity="error")


_InstallPreview = InstallPreview
_plan_install_preview = plan_install_preview
_install_summary = install_summary
_install_success_message = install_success_message
_missing_plugin_message = missing_plugin_message
_not_found_message = install_not_found_message
