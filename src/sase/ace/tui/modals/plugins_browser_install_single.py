"""Single and batch install actions for the plugin browser."""

from __future__ import annotations

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
from sase.agent_clis.models import AgentCliStatus
from sase.ops.names import PLUGIN_INSTALL
from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.operations import (
    AlreadyInstalled,
    InstallManyNothing,
    InstallManyOutcome,
    InstallManyReady,
    InstallNotFound,
    InstallReady,
    NotUvTool,
)
from sase.uv_tool.errors import UvToolError

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from .plugins_browser_install_messages import (
    _install_many_skipped_message,
    _source_variant_label,
    install_many_summary,
    install_many_success_message,
    install_not_found_message,
    install_summary,
)
from .plugins_browser_install_previews import InstallManyPreview, InstallPreview

if TYPE_CHECKING:
    from textual.app import App
    from textual.worker import Worker

    from .plugins_browser_rows import UpdateRow


class PluginSingleInstallActionsMixin:
    """Single and marked-set install actions for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _agent_cli_install_plan_worker: Worker[Any] | None
        _loading: bool
        _offline: bool
        _plan_worker: Worker[Any] | None
        _uv_tool: object | None
        app: App[Any]
        is_mounted: bool

        def _begin_agent_cli_install_plan(self, names: tuple[str, ...]) -> None: ...

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _highlighted_row(self) -> UpdateRow | None: ...

        def _make_install_preview(
            self, name: str, *, offline: bool
        ) -> InstallPreview: ...

        def _make_install_many_preview(
            self, names: tuple[str, ...], *, offline: bool
        ) -> InstallManyPreview: ...

        def _execute_install_many(
            self, plan: InstallManyReady, *, run_fn: Any = None
        ) -> InstallManyOutcome: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def action_toggle_mark(self) -> None: ...

        def _clear_marks(self, keys: object = None) -> None: ...

        def _marked_keys_with(self, capability: str) -> tuple[str, ...]: ...

        def _handle_code_update_completion(
            self,
            completion: TrackedProcCompletion[Any],
            *,
            failure_prefix: str,
        ) -> None: ...

    def _install_highlighted_cli_row(self, row: UpdateRow) -> None:
        """Start the CLI install flow (or toast) for a highlighted CLI row."""
        from sase.agent_clis.install import describe_agent_cli_install

        payload = row.payload
        if not isinstance(payload, AgentCliStatus):
            return
        if payload.installed:
            self._notify(f"{payload.display_name} is already installed.")
            return
        option = describe_agent_cli_install(payload)
        if not option.installable:
            self._notify(
                option.reason or f"{payload.display_name} can't be installed by SASE.",
                severity="warning",
            )
            return
        self._begin_agent_cli_install_plan((payload.name,))

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

    def _on_single_install_preview(self, preview: InstallPreview | None) -> None:
        """Route a single-install preview to a toast or the confirm modal."""
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
                    "sase's TUI restarts after a successful install to load the new plugin.",
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
                        "sase's TUI restarts after a successful install to load the new plugin.",
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
                        "sase's TUI restarts after a successful install to load the plugins.",
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

    def _on_install_complete(self, completion: TrackedProcCompletion[Any]) -> None:
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
