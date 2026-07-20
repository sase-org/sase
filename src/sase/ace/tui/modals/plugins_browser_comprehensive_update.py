"""Snapshot-gated comprehensive update planning and execution for ACE."""

from __future__ import annotations

import shlex
import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.ace.tui.task_subprocess import TaskReporter
from sase.ace.update_receipt import build_update_receipt, write_pending_update_toast
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUpdatePlan,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    UpdateResultStatus,
    UpdateStrategy,
)
from sase.agent_clis.runner import CommandResult, run_command
from sase.dev_update.journal import append_dev_update_journal
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.main.update_types import CombinedUpdateResult
from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError
from sase.version._git import GitUpstreamStatus, git_fetch_upstream_args

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionPreviewSection,
    PluginActionVariant,
)
from .plugins_browser_agent_clis import agent_cli_result_line
from .plugins_browser_dev_update import (
    DevUpdatePreview,
    dev_update_blocking_reason,
    dev_update_failed,
    dev_update_failure_message,
    dev_update_preview_summary,
    dev_update_success_message,
)
from .plugins_browser_sase_update_summary import (
    combined_sase_update_success_message,
    load_receipt_for_summary,
    sase_update_success_message,
)
from .plugins_browser_sase_update_tasks import dev_update_reporter_runner


@dataclass(frozen=True)
class ComprehensiveUpdateRequest:
    """One immutable provider projection captured by ``,U`` dispatch."""

    provider_names: tuple[str, ...] | None


@dataclass(frozen=True)
class _DroppedProviderCandidate:
    """Captured provider identity that no longer exists in live inventory."""

    name: str
    reason: str = "no longer present in the live provider inventory"


@dataclass(frozen=True)
class _ComprehensiveUpdatePreview:
    """Independent SASE and provider plans for one confirmation."""

    request: ComprehensiveUpdateRequest
    sase_preview: DevUpdatePreview | None
    sase_current: bool = False
    sase_blocker: str | None = None
    provider_plan: AgentCliUpdatePlan | None = None
    provider_dropped: tuple[_DroppedProviderCandidate, ...] = ()
    provider_error: str | None = None

    @property
    def provider_runnable(self) -> bool:
        return isinstance(self.provider_plan, AgentCliUpdatesReady) and bool(
            self.provider_plan.runnable_entries
        )

    @property
    def sase_runnable(self) -> bool:
        return bool(
            not self.sase_current
            and self.sase_blocker is None
            and self.sase_preview is not None
        )

    @property
    def runnable(self) -> bool:
        return self.sase_runnable or self.provider_runnable

    @property
    def manual_provider_entries(self) -> tuple[Any, ...]:
        entries = getattr(self.provider_plan, "entries", ())
        return tuple(
            entry
            for entry in entries
            if entry.strategy is UpdateStrategy.MANUAL or entry.manual_argv is not None
        )


class ComprehensiveUpdateActionsMixin:
    """Plan, confirm, execute, and hand off the global ``,U`` flow."""

    if TYPE_CHECKING:
        _agent_cli_statuses: tuple[AgentCliStatus, ...]
        _agent_cli_error: str | None
        _comprehensive_update_plan_worker: Any | None
        _loading: bool
        _offline: bool
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _all_up_to_date(self) -> bool: ...

        def _close_admin_center_after_sase_update(self) -> None: ...

        def _execute_dev_update(
            self, plan: DevUpdatePlan, *, run: Any = None
        ) -> DevUpdateResult: ...

        def _make_sase_update_preview(
            self,
            receipt: object | None,
            *,
            already_refreshed_roots: Collection[str] = (),
        ) -> DevUpdatePreview: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _restart_after_update(self, message: str) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

    def _start_comprehensive_update_preview(
        self,
        request: ComprehensiveUpdateRequest,
        *,
        already_refreshed_roots: Collection[str] = (),
    ) -> None:
        """Build both preview legs off-thread from captured and loaded state."""
        if self._loading or self._comprehensive_update_plan_worker is not None:
            return

        statuses = tuple(self._agent_cli_statuses)
        agent_cli_error = self._agent_cli_error
        offline = self._offline
        install = self._uv_tool
        fresh_roots = frozenset(already_refreshed_roots)
        sase_current = self._all_up_to_date()

        def task() -> _ComprehensiveUpdatePreview:
            provider_plan, dropped, provider_error = _plan_captured_providers(
                request.provider_names,
                statuses,
                offline=offline,
                source_error=agent_cli_error,
            )
            if sase_current:
                return _ComprehensiveUpdatePreview(
                    request=request,
                    sase_preview=None,
                    sase_current=True,
                    provider_plan=provider_plan,
                    provider_dropped=dropped,
                    provider_error=provider_error,
                )
            if isinstance(install, NotUvToolInstall):
                return _ComprehensiveUpdatePreview(
                    request=request,
                    sase_preview=None,
                    sase_blocker=str(NotAUvToolInstallError(install)),
                    provider_plan=provider_plan,
                    provider_dropped=dropped,
                    provider_error=provider_error,
                )
            try:
                receipt = load_receipt_for_summary(install)
                sase_preview = self._make_sase_update_preview(
                    receipt,
                    already_refreshed_roots=fresh_roots,
                )
                blocker = sase_preview.error
                if blocker is None and sase_preview.plan is not None:
                    plan_blocker = dev_update_blocking_reason(sase_preview.plan)
                    managed_can_proceed = bool(
                        sase_preview.managed_argv
                        and not sase_preview.plan.actionable_roots
                    )
                    if plan_blocker is not None and not managed_can_proceed:
                        blocker = plan_blocker
            except Exception as exc:  # noqa: BLE001 - preserve provider leg.
                sase_preview = None
                blocker = _error_text(exc)
            return _ComprehensiveUpdatePreview(
                request=request,
                sase_preview=sase_preview,
                sase_blocker=blocker,
                provider_plan=provider_plan,
                provider_dropped=dropped,
                provider_error=provider_error,
            )

        self._comprehensive_update_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="comprehensive-update-plan",
            exit_on_error=False,
        )

    def _on_comprehensive_update_preview(
        self, preview: _ComprehensiveUpdatePreview | None
    ) -> None:
        if preview is None:
            return
        if not preview.runnable:
            self._handle_comprehensive_noop(preview)
            return

        modal = PluginActionConfirmModal(
            title="Comprehensive update",
            intro=(
                "Confirm the snapshot-gated SASE and provider work below. "
                "Provider commands run first and sequentially."
            ),
            variants=(
                PluginActionVariant(
                    key="comprehensive-update",
                    label="comprehensive update",
                    argv=(),
                    summary="Runs one tracked comprehensive update.",
                    sections=(
                        _sase_preview_section(preview),
                        _provider_preview_section(preview),
                    ),
                ),
            ),
            panel_title="Confirm comprehensive update",
            icon="↑",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            if self._submit_comprehensive_update_task(preview):
                self._close_admin_center_after_sase_update()

        self.app.push_screen(modal, _on_confirmed)

    def _handle_comprehensive_noop(self, preview: _ComprehensiveUpdatePreview) -> None:
        if preview.manual_provider_entries:
            switch_to_subtab = getattr(self, "_switch_to_subtab", None)
            if callable(switch_to_subtab):
                switch_to_subtab("agent-clis")
            self._notify(
                "No safe automatic Agent CLI command is available. Review the "
                "manual command and vendor documentation in Agent CLIs.",
                severity="warning",
            )
            return
        errors = tuple(
            item for item in (preview.sase_blocker, preview.provider_error) if item
        )
        if errors:
            self._notify("; ".join(errors), severity="error")
            return
        if preview.provider_dropped:
            names = ", ".join(item.name for item in preview.provider_dropped)
            self._notify(
                "No captured updates remain: available components are current; "
                f"no longer present: {names}.",
                severity="information",
            )
            return
        self._notify(
            "Everything in the captured comprehensive update is already current.",
            severity="information",
        )

    def _submit_comprehensive_update_task(
        self, preview: _ComprehensiveUpdatePreview
    ) -> bool:
        """Submit exactly one task claiming both update mutation scopes."""

        def task(
            reporter: TaskReporter,
        ) -> TrackedTaskResult[ComprehensiveUpdateResult]:
            start = time.monotonic()
            provider_results, provider_error = self._execute_provider_leg(
                preview, reporter
            )
            sase_result = self._execute_comprehensive_sase_leg(preview, reporter)
            result = ComprehensiveUpdateResult(
                sase=sase_result,
                provider_results=provider_results,
                provider_error=provider_error or preview.provider_error,
                elapsed=max(0.0, time.monotonic() - start),
            )
            message = _comprehensive_update_summary(result)
            reporter.section("Summary")
            reporter.log(message, stream="result")
            return TrackedTaskResult(
                success=not result.has_failures,
                message=message,
                payload=result,
                error=message if result.has_failures else None,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return False
        task_info = submit(
            "comprehensive-update",
            "sase + agent CLIs",
            "",
            task,
            display_name="comprehensive update",
            dedup_key="comprehensive-update",
            exclusive_scopes=("sase-update", "agent-cli-update"),
            duplicate_message="A SASE or agent CLI update is already running.",
            on_complete=self._on_comprehensive_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        return task_info is not None

    def _execute_provider_leg(
        self,
        preview: _ComprehensiveUpdatePreview,
        reporter: TaskReporter,
    ) -> tuple[tuple[AgentCliUpdateResult, ...], str | None]:
        """Execute provider commands first, preserving skips and drops."""
        plan = preview.provider_plan
        results: tuple[AgentCliUpdateResult, ...] = ()
        error: str | None = None
        if isinstance(plan, (AgentCliUpdatesReady, AgentCliNothingToUpdate)):
            try:
                reporter.phase("Updating agent CLIs")

                def task_runner(
                    argv: tuple[str, ...], *, timeout: float = 300.0
                ) -> CommandResult:
                    return run_command(
                        argv,
                        timeout=timeout,
                        run_fn=reporter.subprocess_run_fn(),
                    )

                from . import plugins_browser_pane as pane_module

                results = pane_module._execute_agent_cli_updates(
                    plan,
                    run_fn=task_runner,
                )
            except Exception as exc:  # noqa: BLE001 - SASE must still run.
                error = _error_text(exc)

        dropped_results = tuple(
            AgentCliUpdateResult(
                name=item.name,
                display_name=item.name,
                status=UpdateResultStatus.SKIPPED,
                old_version=None,
                new_version=None,
                command=None,
                docs_url=None,
                reason=item.reason,
            )
            for item in preview.provider_dropped
        )
        ordered = _order_provider_results(
            (*results, *dropped_results),
            preview.request.provider_names,
        )
        if ordered or error:
            reporter.section("Agent CLI results")
            for result in ordered:
                reporter.log(agent_cli_result_line(result), stream="result")
            if error:
                reporter.log(
                    f"Agent CLI planning/execution failed: {error}", stream="result"
                )
        return ordered, error

    def _execute_comprehensive_sase_leg(
        self,
        preview: _ComprehensiveUpdatePreview,
        reporter: TaskReporter,
    ) -> ComprehensiveSaseUpdateResult:
        """Attempt the selected SASE leg after all provider commands finish."""
        if preview.sase_current:
            return ComprehensiveSaseUpdateResult(
                SaseUpdateResultStatus.ALREADY_CURRENT,
                "already current",
            )
        if preview.sase_blocker is not None or preview.sase_preview is None:
            return ComprehensiveSaseUpdateResult(
                SaseUpdateResultStatus.SKIPPED,
                preview.sase_blocker or "SASE update unavailable",
            )

        sase_preview = preview.sase_preview
        if sase_preview.plan is None:
            try:
                reporter.phase("Resolving sase update")
                run_sase_update = cast(Any, self)._run_sase_update_summary
                summary, elapsed = run_sase_update(
                    self._uv_tool,
                    run_fn=reporter.uv_runner(),
                )
            except Exception as exc:  # noqa: BLE001 - typed aggregate failure.
                return ComprehensiveSaseUpdateResult(
                    SaseUpdateResultStatus.FAILED,
                    _error_text(exc),
                )
            return ComprehensiveSaseUpdateResult(
                (
                    SaseUpdateResultStatus.UPDATED
                    if summary.changed
                    else SaseUpdateResultStatus.ALREADY_CURRENT
                ),
                sase_update_success_message(summary, elapsed),
                summary,
            )

        plan = sase_preview.plan
        started = time.monotonic()
        try:
            reporter.phase("Updating editable SASE checkouts")
            dev_result = self._execute_dev_update(
                plan,
                run=dev_update_reporter_runner(reporter),
            )
            append_dev_update_journal(plan, dev_result)
        except Exception as exc:  # noqa: BLE001 - terminal failure is aggregate data.
            return ComprehensiveSaseUpdateResult(
                SaseUpdateResultStatus.FAILED,
                _error_text(exc),
            )
        if dev_update_failed(dev_result):
            return ComprehensiveSaseUpdateResult(
                SaseUpdateResultStatus.FAILED,
                dev_update_failure_message(dev_result),
                dev_result,
            )

        if sase_preview.managed_argv:
            try:
                reporter.phase("Resolving managed SASE packages")
                run_planned_update = cast(Any, self)._run_planned_sase_update_summary
                managed_summary, _ = run_planned_update(
                    sase_preview.managed_argv,
                    sase_preview.managed_packages,
                    run_fn=reporter.uv_runner(),
                )
            except Exception as exc:  # noqa: BLE001 - retain successful dev leg.
                combined = CombinedUpdateResult(
                    dev_result=dev_result,
                    managed_summary=None,
                    elapsed=max(0.0, time.monotonic() - started),
                )
                return ComprehensiveSaseUpdateResult(
                    SaseUpdateResultStatus.FAILED,
                    _error_text(exc),
                    combined,
                )
            combined = CombinedUpdateResult(
                dev_result=dev_result,
                managed_summary=managed_summary,
                elapsed=max(0.0, time.monotonic() - started),
            )
            return ComprehensiveSaseUpdateResult(
                (
                    SaseUpdateResultStatus.UPDATED
                    if combined.changed
                    else SaseUpdateResultStatus.ALREADY_CURRENT
                ),
                combined_sase_update_success_message(combined),
                combined,
            )

        elapsed = max(0.0, time.monotonic() - started)
        return ComprehensiveSaseUpdateResult(
            (
                SaseUpdateResultStatus.UPDATED
                if dev_result.changed
                else SaseUpdateResultStatus.ALREADY_CURRENT
            ),
            dev_update_success_message(dev_result, subject="sase", elapsed=elapsed),
            dev_result,
        )

    def _on_comprehensive_update_complete(
        self,
        completion: TrackedTaskCompletion[ComprehensiveUpdateResult],
    ) -> None:
        # Even an unexpected task-wrapper failure should promptly reconcile
        # the shared snapshot and badge from local state.
        refresh = getattr(self.app, "_schedule_updates_indicator_revalidation", None)
        if callable(refresh):
            refresh()

        result = completion.payload
        if result is None:
            self._notify(
                f"comprehensive update failed: {completion.error or completion.message}",
                severity="error",
            )
            return

        for provider_result in result.provider_results:
            self._agent_cli_results[provider_result.name] = provider_result  # type: ignore[attr-defined]

        # Revalidate and rewrite the shared composite snapshot in a worker;
        # this updates the badge promptly without broadening captured authority.
        message = _comprehensive_update_summary(result)
        if result.code_changed:
            receipt = build_update_receipt(result)
            if receipt is not None:
                write_pending_update_toast(receipt)
            self._restart_after_update(message)
            return

        severity: Literal["information", "warning", "error"] = "information"
        if result.fully_failed:
            severity = "error"
        elif result.has_failures:
            severity = "warning"
        self._notify(message, severity=severity)
        if self.is_mounted and not self._loading:
            self._start_load(force=False)


def _plan_captured_providers(
    captured_names: tuple[str, ...] | None,
    statuses: Sequence[AgentCliStatus],
    *,
    offline: bool,
    source_error: str | None = None,
) -> tuple[
    AgentCliUpdatePlan | None,
    tuple[_DroppedProviderCandidate, ...],
    str | None,
]:
    """Intersect captured identities with live status; never broaden scope."""
    if not captured_names:
        return AgentCliNothingToUpdate(entries=(), all_clis=False), (), None

    unique_names = tuple(dict.fromkeys(captured_names))
    live_by_name = {status.name: status for status in statuses}
    selected_names = tuple(name for name in unique_names if name in live_by_name)
    missing_names = tuple(name for name in unique_names if name not in live_by_name)
    dropped = (
        ()
        if source_error
        else tuple(_DroppedProviderCandidate(name) for name in missing_names)
    )
    selected_statuses = tuple(live_by_name[name] for name in selected_names)
    try:
        from . import plugins_browser_pane as pane_module

        plan = pane_module._plan_agent_cli_updates(
            selected_names,
            all_clis=False,
            refresh=False,
            offline=offline,
            status_fn=lambda **_kwargs: selected_statuses,
        )
    except Exception as exc:  # noqa: BLE001 - preserve independently valid SASE.
        return None, dropped, _error_text(exc)
    provider_error = (
        f"provider inventory unavailable: {source_error}" if source_error else None
    )
    return plan, dropped, provider_error


def _sase_preview_section(
    preview: _ComprehensiveUpdatePreview,
) -> PluginActionPreviewSection:
    title = "SASE, core & plugins"
    if preview.sase_current:
        return PluginActionPreviewSection(
            title=title,
            summary="Already current in the live Updates inventory.",
        )
    if preview.sase_blocker is not None or preview.sase_preview is None:
        return PluginActionPreviewSection(
            title=title,
            summary="This leg will not run.",
            skipped=(preview.sase_blocker or "SASE update unavailable",),
        )
    sase = preview.sase_preview
    if sase.plan is None:
        return PluginActionPreviewSection(
            title=title,
            summary="Upgrades SASE core and every installed plugin.",
            commands=(shlex.join(tuple(build_upgrade_all(color="never"))),),
        )

    plan = sase.plan
    skipped = tuple(
        f"{package.record.name}: {package.reason}" for package in plan.skipped
    )
    return PluginActionPreviewSection(
        title=title,
        summary=dev_update_preview_summary(plan, subject="sase"),
        commands=_dev_update_commands(plan, managed_argv=sase.managed_argv),
        skipped=skipped,
    )


def _provider_preview_section(
    preview: _ComprehensiveUpdatePreview,
) -> PluginActionPreviewSection:
    title = "Agent CLIs"
    names = preview.request.provider_names
    if names is None:
        return PluginActionPreviewSection(
            title=title,
            summary="No completed automatic provider snapshot was available.",
        )
    if not names:
        return PluginActionPreviewSection(
            title=title,
            summary="The completed automatic snapshot had no provider candidates.",
        )

    entries = getattr(preview.provider_plan, "entries", ())
    runnable = tuple(entry for entry in entries if entry.argv is not None)
    commands = tuple(
        f"{entry.status.display_name}: {shlex.join(entry.argv or ())}"
        for entry in runnable
    )
    details = tuple(
        f"{entry.status.display_name} documentation: {entry.status.docs_url}"
        for entry in runnable
        if entry.status.docs_url
    )
    skipped = [
        f"{entry.status.display_name}: {entry.skip_reason or 'skipped'}"
        for entry in entries
        if entry.argv is None
    ]
    skipped.extend(f"{item.name}: {item.reason}" for item in preview.provider_dropped)
    if preview.provider_error:
        skipped.append(f"Provider planning failed: {preview.provider_error}")
    return PluginActionPreviewSection(
        title=title,
        summary=(
            f"{len(runnable)} safe provider command"
            f"{'s' if len(runnable) != 1 else ''} from the captured snapshot."
        ),
        commands=commands,
        details=details,
        skipped=tuple(skipped),
    )


def _dev_update_commands(
    plan: DevUpdatePlan,
    *,
    managed_argv: tuple[str, ...],
) -> tuple[str, ...]:
    commands: list[str] = []
    for root in plan.actionable_roots:
        status = GitUpstreamStatus(
            root=root.git_root,
            upstream=root.upstream,
            remote=root.remote,
            remote_branch=root.remote_branch,
            detached=False,
            dirty=False,
            ahead=root.ahead,
            behind=root.behind,
        )
        commands.append(
            shlex.join(
                (
                    "git",
                    "-C",
                    root.git_root,
                    *git_fetch_upstream_args(status),
                )
            )
        )
        if root.upstream:
            commands.append(
                shlex.join(
                    ("git", "-C", root.git_root, "merge", "--ff-only", root.upstream)
                )
            )
    for step in plan.reconcile_steps:
        if step.command:
            commands.append(shlex.join(step.command))
        if step.repair_command:
            commands.append("fallback: " + shlex.join(step.repair_command))
    if managed_argv:
        commands.append(shlex.join(managed_argv))
    return tuple(commands)


def _order_provider_results(
    results: Sequence[AgentCliUpdateResult],
    captured_names: tuple[str, ...] | None,
) -> tuple[AgentCliUpdateResult, ...]:
    if not captured_names:
        return tuple(results)
    order = {name: index for index, name in enumerate(captured_names)}
    return tuple(sorted(results, key=lambda result: order.get(result.name, len(order))))


def _comprehensive_update_summary(result: ComprehensiveUpdateResult) -> str:
    """Return a concise but truthful aggregate completion summary."""
    sase_line = f"SASE, core & plugins: {result.sase.message}"
    counts = {
        "updated": 0,
        "current": 0,
        "manual": 0,
        "skipped": 0,
        "failed": 0,
    }
    for provider in result.provider_results:
        if provider.status is UpdateResultStatus.UPDATED:
            counts["updated"] += 1
        elif provider.status is UpdateResultStatus.ALREADY_CURRENT:
            counts["current"] += 1
        elif provider.status is UpdateResultStatus.FAILED:
            counts["failed"] += 1
        elif provider.suggested_command:
            counts["manual"] += 1
        else:
            counts["skipped"] += 1
    if result.provider_error:
        counts["failed"] += 1
    provider_parts = [f"{count} {label}" for label, count in counts.items() if count]
    provider_line = "Agent CLIs: " + (
        ", ".join(provider_parts) if provider_parts else "no captured work"
    )
    return f"{sase_line}; {provider_line}"


def _error_text(error: Exception) -> str:
    return str(error).strip() or type(error).__name__


__all__ = [
    "ComprehensiveUpdateActionsMixin",
    "ComprehensiveUpdateRequest",
]
