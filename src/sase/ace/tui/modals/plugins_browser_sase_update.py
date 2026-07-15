"""SASE self-update actions for the Config Center Updates tab."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import time
from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.update_receipt import build_update_receipt, write_pending_update_toast
from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.ace.tui.task_subprocess import TaskReporter
from sase.dev_update.journal import append_dev_update_journal
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.main.update_types import CombinedUpdateResult
from sase.plugins.render_common import humanize_duration
from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import NotUvToolInstall, UvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.receipt import ToolReceipt, load_receipt
from sase.uv_tool.render import (
    PlannedPackage,
    UpdateSummary,
    summarize_planned_update,
    summarize_update,
)
from sase.uv_tool.runner import ChangeKind, run_uv
from sase.version._utils import normalize_distribution_name

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from .plugins_browser_dev_update import (
    DevUpdatePreview,
    dev_update_blocking_reason,
    dev_update_failed,
    dev_update_failure_message,
    dev_update_preview_details,
    dev_update_preview_summary,
    dev_update_success_message,
)

_CORE_DIST_KEYS = {
    normalize_distribution_name("sase"),
    normalize_distribution_name("sase-core-rs"),
}
_SASE_UPDATE_NOOP_MESSAGE = "Nothing to update: sase, core, and plugins are current."


def installed_version(name: str) -> str | None:
    """Return the installed version of distribution *name*, or ``None``."""
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - version display must never fail the task.
        return None


def load_receipt_for_summary(install: object | None) -> ToolReceipt | None:
    """Load the uv-tool receipt when available, tolerating parse failures."""
    if not isinstance(install, UvToolInstall):
        return None
    try:
        return load_receipt(install.receipt_path)
    except ReceiptError:
        return None


def run_sase_update_summary(
    install: object | None, *, run_fn: Any = run_uv
) -> tuple[UpdateSummary, float]:
    """Run ``uv tool upgrade sase`` and summarize the changed package set."""
    argv = build_upgrade_all(color="never")
    start = time.monotonic()
    change_set = run_fn(argv)
    elapsed = max(0.0, time.monotonic() - start)
    return (
        summarize_update(
            change_set,
            load_receipt_for_summary(install),
            current_version=installed_version,
        ),
        elapsed,
    )


def run_planned_sase_update_summary(
    argv: tuple[str, ...],
    packages: tuple[PlannedPackage, ...],
    *,
    run_fn: Any = run_uv,
) -> tuple[UpdateSummary, float]:
    """Run and summarize an explicit managed leg from a combined preview."""
    start = time.monotonic()
    change_set = run_fn(list(argv))
    elapsed = max(0.0, time.monotonic() - start)
    return summarize_planned_update(change_set, packages), elapsed


def sase_update_success_message(summary: UpdateSummary, elapsed: float) -> str:
    """Concise toast for a successful ``sase update`` run."""
    if not summary.changed:
        return "Already up to date."

    core_updated = any(
        outcome.is_update
        and normalize_distribution_name(outcome.name) in _CORE_DIST_KEYS
        for outcome in summary.outcomes
    )
    plugin_count = len(summary.updated_plugins)
    dependency_count = sum(
        1
        for outcome in summary.updated_dependencies
        if normalize_distribution_name(outcome.name) not in _CORE_DIST_KEYS
    )

    subjects: list[str] = []
    if core_updated:
        subjects.append("sase")
    if plugin_count:
        subjects.append(f"{plugin_count} {_plural(plugin_count, 'plugin')}")
    if not subjects and dependency_count:
        subjects.append(f"{dependency_count} {_plural(dependency_count, 'dependency')}")
    if not subjects:
        subjects.append("packages")

    return f"Updated {' + '.join(subjects)} in {humanize_duration(elapsed)}"


def _managed_update_changed(outcome: Any) -> bool:
    """Whether a managed update result changed any installed package."""
    changed = getattr(outcome, "changed", None)
    if isinstance(changed, bool):
        return changed
    change_set = getattr(outcome, "change_set", None)
    changes = getattr(change_set, "changes", ())
    return any(
        getattr(change, "kind", None) is not ChangeKind.UNCHANGED for change in changes
    )


def _combined_sase_update_success_message(result: CombinedUpdateResult) -> str:
    """Concise success message for a comprehensive mixed update."""
    if not result.changed:
        return "Already up to date."
    if result.managed_summary is None or not result.managed_summary.changed:
        assert result.dev_result is not None
        return dev_update_success_message(
            result.dev_result,
            subject="sase",
            elapsed=result.elapsed,
        )
    if result.dev_result is None or not result.dev_result.changed:
        return sase_update_success_message(result.managed_summary, result.elapsed)

    dev_count = sum(
        1 for outcome in result.dev_result.outcomes if outcome.status == "updated"
    )
    managed_message = sase_update_success_message(
        result.managed_summary, result.elapsed
    ).removeprefix("Updated ")
    managed_subject = managed_message.rsplit(" in ", maxsplit=1)[0]
    return (
        f"Updated {dev_count} editable {_plural(dev_count, 'checkout')} + "
        f"{managed_subject} in {humanize_duration(result.elapsed)}"
    )


def _plural(count: int, singular: str) -> str:
    if count == 1:
        return singular
    if singular.endswith("y"):
        return f"{singular[:-1]}ies"
    return f"{singular}s"


class SaseUpdateActionsMixin:
    """Run ``sase update`` from the Updates tab."""

    if TYPE_CHECKING:
        _loading: bool
        _sase_update_plan_worker: Any | None
        _uv_tool: object | None
        app: Any
        is_mounted: bool
        screen: Any

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _run_sase_update_summary(
            self, install: object | None, *, run_fn: Any = run_uv
        ) -> tuple[UpdateSummary, float]: ...

        def _run_planned_sase_update_summary(
            self,
            argv: tuple[str, ...],
            packages: tuple[PlannedPackage, ...],
            *,
            run_fn: Any = run_uv,
        ) -> tuple[UpdateSummary, float]: ...

        def _make_sase_update_preview(
            self,
            receipt: object | None,
            *,
            already_refreshed_roots: Collection[str] = (),
        ) -> DevUpdatePreview: ...

        def _execute_dev_update(
            self, plan: DevUpdatePlan, *, run: Any = None
        ) -> DevUpdateResult: ...

        def _start_load(self, *, force: bool) -> None: ...

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

    def _submit_sase_update_task(self) -> None:
        """Run the self-update engine in the shared tracked-task system."""
        install = self._uv_tool

        def task(reporter: TaskReporter) -> TrackedTaskResult[UpdateSummary]:
            try:
                reporter.phase("Resolving sase update")
                summary, elapsed = self._run_sase_update_summary(
                    install,
                    run_fn=reporter.uv_runner(),
                )
            except UvToolError as exc:
                return TrackedTaskResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            message = sase_update_success_message(summary, elapsed)
            _log_update_summary(reporter, summary, message)
            return TrackedTaskResult(
                success=True,
                message=message,
                payload=summary,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        submit(
            "sase-update",
            "sase",
            "",
            task,
            display_name="sase update",
            dedup_key="sase-update",
            duplicate_message="A sase update is already running.",
            on_complete=self._on_sase_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_sase_update_complete(
        self, completion: TrackedTaskCompletion[UpdateSummary]
    ) -> None:
        """Toast the outcome and refresh installed/latest versions in place."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="sase update failed",
            unchanged_message=_SASE_UPDATE_NOOP_MESSAGE,
            unchanged_severity="error",
        )

    def _submit_dev_update_task(
        self,
        plan: DevUpdatePlan,
        *,
        subject: str,
        display_name: str,
        dedup_key: str,
        duplicate_message: str,
    ) -> None:
        """Run a dev-update plan in the shared tracked-task system."""

        def task(reporter: TaskReporter) -> TrackedTaskResult[DevUpdateResult]:
            start = time.monotonic()
            reporter.phase("Fetching editable checkouts")
            result = self._execute_dev_update(
                plan,
                run=_dev_update_reporter_runner(reporter),
            )
            append_dev_update_journal(plan, result)
            elapsed = max(0.0, time.monotonic() - start)
            if dev_update_failed(result):
                reason = dev_update_failure_message(result)
                return TrackedTaskResult(
                    success=False,
                    message=reason,
                    error=reason,
                    payload=result,
                )
            message = dev_update_success_message(
                result, subject=subject, elapsed=elapsed
            )
            reporter.log(message, stream="result")
            return TrackedTaskResult(
                success=True,
                message=message,
                payload=result,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        submit(
            "dev-update",
            subject,
            "",
            task,
            display_name=display_name,
            dedup_key=dedup_key,
            duplicate_message=duplicate_message,
            on_complete=self._on_dev_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _submit_combined_update_task(self, preview: DevUpdatePreview) -> None:
        """Run editable and managed legs as one tracked comprehensive task."""
        assert preview.plan is not None
        plan = preview.plan

        def task(reporter: TaskReporter) -> TrackedTaskResult[CombinedUpdateResult]:
            start = time.monotonic()
            reporter.phase("Checking editable SASE checkouts")
            dev_result = self._execute_dev_update(
                plan,
                run=_dev_update_reporter_runner(reporter),
            )
            append_dev_update_journal(plan, dev_result)
            if dev_update_failed(dev_result):
                reason = dev_update_failure_message(dev_result)
                return TrackedTaskResult(
                    success=False,
                    message=reason,
                    error=reason,
                    payload=CombinedUpdateResult(
                        dev_result=dev_result,
                        managed_summary=None,
                        elapsed=max(0.0, time.monotonic() - start),
                    ),
                )

            try:
                reporter.phase("Resolving managed SASE packages")
                managed_summary, _managed_elapsed = (
                    self._run_planned_sase_update_summary(
                        preview.managed_argv,
                        preview.managed_packages,
                        run_fn=reporter.uv_runner(),
                    )
                )
            except UvToolError as exc:
                return TrackedTaskResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                    payload=CombinedUpdateResult(
                        dev_result=dev_result,
                        managed_summary=None,
                        elapsed=max(0.0, time.monotonic() - start),
                    ),
                )

            result = CombinedUpdateResult(
                dev_result=dev_result,
                managed_summary=managed_summary,
                elapsed=max(0.0, time.monotonic() - start),
            )
            message = _combined_sase_update_success_message(result)
            _log_combined_update_result(reporter, result, message)
            return TrackedTaskResult(success=True, message=message, payload=result)

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        submit(
            "sase-update",
            "sase",
            "",
            task,
            display_name="sase update",
            dedup_key="sase-update",
            duplicate_message="A sase update is already running.",
            on_complete=self._on_combined_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_dev_update_complete(
        self, completion: TrackedTaskCompletion[DevUpdateResult]
    ) -> None:
        """Toast/restart after an editable-checkout update task."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="dev update failed",
        )

    def _on_combined_update_complete(
        self, completion: TrackedTaskCompletion[CombinedUpdateResult]
    ) -> None:
        """Toast, receipt, and restart once for a comprehensive mixed update."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="sase update failed",
            unchanged_message=_SASE_UPDATE_NOOP_MESSAGE,
            unchanged_severity="error",
        )

    def _handle_code_update_completion(
        self,
        completion: TrackedTaskCompletion[Any],
        *,
        failure_prefix: str,
        unchanged_message: str | None = None,
        unchanged_severity: Literal["information", "warning", "error"] = "information",
    ) -> None:
        """Common update completion handling: restart only after real changes."""
        if completion.success:
            if completion.payload is not None and _managed_update_changed(
                completion.payload
            ):
                receipt = build_update_receipt(completion.payload)
                if receipt is not None:
                    write_pending_update_toast(receipt)
                self._restart_after_update(completion.message)
                return
            self._notify(
                unchanged_message or completion.message,
                severity=unchanged_severity,
            )
            if self.is_mounted and not self._loading:
                self._start_load(force=False)
        else:
            detail = completion.error or completion.message
            self._notify(f"{failure_prefix}: {detail}", severity="error")

    def _restart_after_update(self, message: str) -> None:
        """Notify briefly, then reuse the TUI + axe restart machinery."""
        self._restart_after_update_when_ready(message, deferred=False)

    def _restart_after_update_when_ready(self, message: str, *, deferred: bool) -> None:
        """Restart after tracked background tasks have finished."""
        running_tasks = _running_background_tasks(self.app)
        if running_tasks:
            if not deferred:
                count = len(running_tasks)
                noun = "task" if count == 1 else "tasks"
                verb = "finishes" if count == 1 else "finish"
                self._notify(
                    f"{message} - restart queued until {count} background "
                    f"{noun} {verb}."
                )
            set_timer = getattr(self.app, "set_timer", None)
            if callable(set_timer):
                set_timer(
                    1.0,
                    lambda: self._restart_after_update_when_ready(
                        message, deferred=True
                    ),
                )
            return

        self._notify(f"{message} — restarting ACE to load new code.")
        restart = getattr(self.app, "_restart_tui", None)
        if callable(restart):
            restart(restart_axe=True)


_installed_version = installed_version
_load_receipt_for_summary = load_receipt_for_summary
_run_sase_update_summary = run_sase_update_summary
_run_planned_sase_update_summary = run_planned_sase_update_summary
_sase_update_success_message = sase_update_success_message


def _log_update_summary(
    reporter: TaskReporter, summary: UpdateSummary, message: str
) -> None:
    reporter.section("Summary")
    reporter.log(message, stream="result")
    for outcome in summary.outcomes:
        old = getattr(outcome, "old_version", None)
        new = getattr(outcome, "new_version", None)
        name = getattr(outcome, "name", "package")
        if old and new:
            reporter.log(f"{name}: {old} -> {new}", stream="result")
        elif new:
            reporter.log(f"{name}: installed {new}", stream="result")
        elif old:
            reporter.log(f"{name}: removed {old}", stream="result")


def _log_combined_update_result(
    reporter: TaskReporter,
    result: CombinedUpdateResult,
    message: str,
) -> None:
    reporter.section("Summary")
    reporter.log(message, stream="result")
    if result.dev_result is not None:
        for outcome in result.dev_result.outcomes:
            if outcome.status != "updated":
                continue
            reporter.log(
                f"{outcome.record.name}: {outcome.old_version} -> "
                f"{outcome.new_version}",
                stream="result",
            )
    if result.managed_summary is not None:
        for managed_outcome in result.managed_summary.updated:
            reporter.log(
                f"{managed_outcome.name}: {managed_outcome.old_version} -> "
                f"{managed_outcome.new_version}",
                stream="result",
            )


def _dev_update_reporter_runner(reporter: TaskReporter) -> Any:
    from sase.dev_update.models import DevCommandResult

    def _run(argv: Any, *, cwd: Any = None) -> DevCommandResult:
        reporter.phase("Running " + " ".join(str(part) for part in argv[:2]))
        completed = reporter.run(argv, cwd=cwd)
        return DevCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    return _run


def _running_background_tasks(app: Any) -> list[Any]:
    task_queue = getattr(app, "_task_queue", None)
    get_all = getattr(task_queue, "get_all", None)
    if not callable(get_all):
        return []
    try:
        tasks = get_all()
    except Exception:  # noqa: BLE001 - restart checks must not break update flow.
        return []
    return [task for task in tasks if getattr(task, "status", None) == "running"]
