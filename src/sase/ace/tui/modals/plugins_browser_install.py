"""Install planning and actions for the Config Center Updates plugin browser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.session_proc_reporter import SessionProcReporter
from sase.ops.names import PLUGIN_INSTALL
from sase.plugins.catalog import PluginCatalogEntry, PluginCatalogError
from sase.plugins.operations import (
    AlreadyInstalled,
    InstallManyNothing,
    InstallManyOutcome,
    InstallManyPlan,
    InstallManyReady,
    InstallNotFound,
    InstallOutcome,
    InstallPlan,
    InstallReady,
    InstallSkipped,
    NotUvTool,
    plan_install,
    plan_install_many,
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


@dataclass(frozen=True)
class InstallManyPreview:
    """Off-thread result of planning a batch install preview."""

    plan: InstallManyPlan | None
    error: str | None = None


def plan_install_preview(name: str, *, offline: bool) -> InstallPreview:
    """Plan ``install <name>`` (default source, then git) for the confirm modal.

    Delegates to :func:`sase.plugins.operations.plan_install` — the single
    source of truth shared with the PatchI — once per source. Cache-first
    (``refresh=False``). The default-source plan is no longer guaranteed to
    resolve from the index: a definitive public-PyPI 404 makes it fall back to
    git automatically. The explicit forced-git variant is only resolved when
    the default plan is ready *and* did not already fall back, so a terminal
    outcome or an already-git default short-circuits the second load instead
    of offering a redundant duplicate variant.
    """
    try:
        index_plan = plan_install(name, git=False, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return InstallPreview(index_plan=None, error=str(exc))

    git_plan: InstallReady | None = None
    if isinstance(index_plan, InstallReady) and index_plan.spec.source != "git":
        try:
            candidate = plan_install(name, git=True, offline=offline)
        except (PluginCatalogError, ReceiptError):
            candidate = None
        if isinstance(candidate, InstallReady):
            git_plan = candidate
    return InstallPreview(index_plan=index_plan, git_plan=git_plan)


def plan_install_many_preview(
    names: tuple[str, ...], *, offline: bool
) -> InstallManyPreview:
    """Plan a marked-set install for the confirm-preview modal."""
    try:
        plan = plan_install_many(names, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return InstallManyPreview(plan=None, error=str(exc))
    return InstallManyPreview(plan=plan)


def install_summary(plan: InstallReady) -> str:
    """The resolved-plugin-set line shown in the confirm-preview modal."""
    return f"Installs {plan.spec.display_name}  (from {plan.spec.source})"


def install_many_summary(plan: InstallManyReady) -> str:
    """The resolved-plugin-set line shown for a batch install."""
    count = len(plan.specs)
    noun = "plugin" if count == 1 else "plugins"
    return f"Installs {count} {noun}"


def install_success_message(outcome: InstallOutcome) -> str:
    """A concise, CLI-flavored success toast: name + new version + elapsed."""
    spec = outcome.plan.spec
    change = outcome.change_set.get(spec.requirement.name)
    version = change.new_version if change is not None else None
    suffix = f" v{version}" if version else ""
    return (
        f"Installed {spec.display_name}{suffix} in {humanize_duration(outcome.elapsed)}"
    )


def install_many_success_message(outcome: InstallManyOutcome) -> str:
    """A concise success toast for a combined marked-set install."""
    count = len(outcome.plan.specs)
    noun = "plugin" if count == 1 else "plugins"
    return f"Installed {count} {noun} in {humanize_duration(outcome.elapsed)}"


def missing_plugin_message(
    query: str, suggestions: tuple[PluginCatalogEntry, ...]
) -> str:
    """The not-found toast, mirroring the PatchI's ranked-suggestions wording."""
    if suggestions:
        names = ", ".join(entry.name for entry in suggestions)
        return f"No plugin named '{query}' in the catalog. Did you mean: {names}?"
    return f"No plugin named '{query}' in the catalog."


def install_not_found_message(plan: InstallNotFound) -> str:
    """The install not-found toast (shared wording with ``update``)."""
    return missing_plugin_message(plan.query, plan.suggestions)


_SOURCE_VARIANT_LABELS: dict[str, str] = {
    "catalog": "from index",
    "git": "from git",
    "passthrough": "from source",
}


def _source_variant_label(source: str) -> str:
    """The confirm-modal variant label for a resolved :class:`ResolvedSpec` source."""
    return _SOURCE_VARIANT_LABELS.get(source, f"from {source}")


def _install_many_skipped_message(skipped: InstallSkipped) -> str:
    """Human-readable skipped entry for batch-install previews/toasts."""
    if skipped.reason == "not found" and skipped.suggestions:
        names = ", ".join(entry.name for entry in skipped.suggestions)
        return f"{skipped.query}: not found; did you mean {names}?"
    return f"{skipped.query}: {skipped.reason}"


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

        def _execute_install_many(
            self, plan: InstallManyReady, *, run_fn: Any = None
        ) -> InstallManyOutcome: ...

        def _make_install_preview(
            self, name: str, *, offline: bool
        ) -> InstallPreview: ...

        def _make_install_many_preview(
            self, names: tuple[str, ...], *, offline: bool
        ) -> InstallManyPreview: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def action_toggle_mark(self) -> None: ...

        def _clear_marks(self, keys: object = None) -> None: ...

        def _marked_keys_with(self, capability: str) -> tuple[str, ...]: ...

        def _marked_plugin_names(self) -> tuple[str, ...]: ...

        def _handle_code_update_completion(
            self,
            completion: TrackedProcCompletion[Any],
            *,
            failure_prefix: str,
        ) -> None: ...

    def action_install(self) -> None:
        """Install marked plugins, or the highlighted plugin when none are marked.

        The marked-set path resolves every marked plugin into one combined
        ``uv`` argv, so a successful install causes exactly one ACE restart.
        With no marks, this preserves the historical single-highlight behavior.
        """
        if self._loading or self._plan_worker is not None:
            return
        marked_names = self._marked_plugin_names()
        if marked_names:
            if isinstance(self._uv_tool, NotUvToolInstall):
                self._notify(
                    str(NotAUvToolInstallError(self._uv_tool)), severity="warning"
                )
                return
            self._begin_install_many_plan(marked_names)
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

    def action_toggle_install_mark(self) -> None:
        """Toggle the mark on the highlighted installable plugin or updatable CLI."""
        self.action_toggle_mark()

    def _begin_install_plan(self, name: str) -> None:
        offline = self._offline

        def task() -> InstallPreview:
            return self._make_install_preview(name, offline=offline)

        self._plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="plugin-plan"
        )

    def _begin_install_many_plan(self, names: tuple[str, ...]) -> None:
        offline = self._offline

        def task() -> InstallManyPreview:
            return self._make_install_many_preview(names, offline=offline)

        self._plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="plugin-plan"
        )

    def _on_install_preview(
        self, preview: InstallPreview | InstallManyPreview | None
    ) -> None:
        """Route a planned install to a toast (terminal) or the confirm modal."""
        if preview is None:
            return
        if isinstance(preview, InstallManyPreview):
            self._on_install_many_preview(preview)
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

    def _on_install_many_preview(self, preview: InstallManyPreview) -> None:
        """Route a marked-set install preview to a toast or confirm modal."""
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        plan = preview.plan
        if plan is None:
            return
        if isinstance(plan, NotUvTool):
            self._notify(str(plan.error), severity="warning")
        elif isinstance(plan, InstallManyNothing):
            skipped = "; ".join(
                _install_many_skipped_message(item) for item in plan.skipped
            )
            suffix = f": {skipped}" if skipped else "."
            self._notify(
                f"No marked plugins can be installed{suffix}", severity="warning"
            )
        elif isinstance(plan, InstallManyReady):
            self._open_install_many_modal(plan)

    def _open_install_modal(
        self, index_plan: InstallReady, git_plan: InstallReady | None
    ) -> None:
        plans: dict[str, InstallReady] = {"index": index_plan}
        variants = [
            PluginActionVariant(
                key="index",
                label=_source_variant_label(index_plan.spec.source),
                argv=tuple(index_plan.argv),
                summary=install_summary(index_plan),
                details=(
                    "ACE restarts after a successful install to load the new plugin.",
                ),
            )
        ]
        if git_plan is not None:
            plans["git"] = git_plan
            variants.append(
                PluginActionVariant(
                    key="git",
                    label=_source_variant_label(git_plan.spec.source),
                    argv=tuple(git_plan.argv),
                    summary=install_summary(git_plan),
                    details=(
                        "ACE restarts after a successful install to load the new plugin.",
                    ),
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

    def _open_install_many_modal(self, plan: InstallManyReady) -> None:
        names = tuple(spec.display_name for spec in plan.specs)
        count = len(names)
        noun = "plugin" if count == 1 else "plugins"
        skipped = tuple(_install_many_skipped_message(item) for item in plan.skipped)
        modal = PluginActionConfirmModal(
            title=f"Install {count} {noun}",
            intro=(
                f"Confirm to install {count} marked {noun} into "
                "sase's uv tool environment."
            ),
            variants=[
                PluginActionVariant(
                    key="batch",
                    label="marked set",
                    argv=tuple(plan.argv),
                    summary=install_many_summary(plan),
                    items=tuple(
                        f"{spec.display_name}  (from {spec.source})"
                        for spec in plan.specs
                    ),
                    skipped=skipped,
                    details=(
                        "ACE restarts after a successful install to load the plugins.",
                    ),
                )
            ],
            panel_title="Confirm install",
            icon="↓",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_install_many_task(names, plan)

        self.app.push_screen(modal, _on_confirmed)

    def _submit_install_task(self, name: str, plan: InstallReady) -> None:
        """Run ``sase plugin install`` in a durable proc (never blocks)."""
        submit = getattr(self.app, "_submit_durable_proc", None)
        if submit is None:
            return
        argv = ["plugin", "install", name, "--json"]
        if plan.spec.source == "git":
            argv.append("--git")
        submit(
            sase_argv(*argv),
            operation=PLUGIN_INSTALL,
            request=durable_request_payload(plugin=name, source=plan.spec.source),
            request_fingerprint=durable_fingerprint(
                PLUGIN_INSTALL,
                name,
                plan.spec.source,
            ),
            concurrency_keys=(f"plugin-install:{name}",),
            label=f"install {name}",
            display_name=f"install {name}",
            cl_name=name,
            project_file="",
            on_complete=self._on_install_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _submit_install_many_task(
        self, names: tuple[str, ...], plan: InstallManyReady
    ) -> None:
        """Run one combined marked-set install in a tracked proc."""

        count = len(names)

        def task(
            reporter: SessionProcReporter,
        ) -> TrackedProcResult[InstallManyOutcome]:
            try:
                reporter.phase(f"Installing {count} marked plugin(s)")
                outcome = self._execute_install_many(plan, run_fn=reporter.uv_runner())
            except UvToolError as exc:
                return TrackedProcResult(
                    success=False, message=str(exc), error=str(exc)
                )
            message = install_many_success_message(outcome)
            reporter.log(message, stream="result")
            return TrackedProcResult(
                success=True,
                message=message,
                payload=outcome,
            )

        submit = getattr(self.app, "_submit_session_worker", None)
        if submit is None:
            return
        submit(
            "plugin-install",
            task,
            display_name=f"install {count} marked plugins",
            cl_name=", ".join(names),
            on_complete=self._on_install_many_complete,
        )
        self._clear_marks(self._marked_keys_with("install"))

    def _on_install_complete(
        self, completion: TrackedProcCompletion[InstallOutcome]
    ) -> None:
        """Toast/restart after install; no-op installs refresh in place."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="Install failed",
        )

    def _on_install_many_complete(
        self, completion: TrackedProcCompletion[InstallManyOutcome]
    ) -> None:
        """Toast/restart after a marked-set install."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="Install failed",
        )


_InstallPreview = InstallPreview
_InstallManyPreview = InstallManyPreview
_plan_install_preview = plan_install_preview
_plan_install_many_preview = plan_install_many_preview
_install_summary = install_summary
_install_many_summary = install_many_summary
_install_success_message = install_success_message
_install_many_success_message = install_many_success_message
_missing_plugin_message = missing_plugin_message
_not_found_message = install_not_found_message
