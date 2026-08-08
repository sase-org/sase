"""Execution helpers for comprehensive SASE, CLI, and agents-repo updates."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.tui.task_subprocess import TaskReporter
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    UpdateResultStatus,
    UpdateTrigger,
)
from sase.agent_clis.runner import CommandResult, run_command
from sase.agents_sync import integrate_cached_agent_updates
from sase.agents_sync.models import CachedIntegrationResult
from sase.ace.tui.agents_sync_format import (
    cached_agents_result_line,
    summarize_cached_agents_results,
)
from sase.dev_update.journal import append_dev_update_journal
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.main.update_types import CombinedUpdateResult

from .plugins_browser_agent_clis import agent_cli_result_line
from .plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    error_text,
)
from .plugins_browser_dev_update import (
    dev_update_failed,
    dev_update_failure_message,
    dev_update_success_message,
)
from .plugins_browser_sase_update_summary import (
    combined_sase_update_success_message,
    sase_update_success_message,
)
from .plugins_browser_sase_update_tasks import dev_update_reporter_runner


class ComprehensiveUpdateExecutionMixin:
    """Execute all legs of a previously confirmed comprehensive update."""

    if TYPE_CHECKING:
        _uv_tool: object | None

        def _execute_dev_update(
            self, plan: DevUpdatePlan, *, run: Any = None
        ) -> DevUpdateResult: ...

    def _execute_provider_leg(
        self,
        preview: ComprehensiveUpdatePreview,
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
                    argv: tuple[str, ...],
                    *,
                    timeout: float = 300.0,
                    env_overlay: Mapping[str, str] | None = None,
                ) -> CommandResult:
                    return run_command(
                        argv,
                        timeout=timeout,
                        env_overlay=env_overlay,
                        run_fn=reporter.subprocess_run_fn(),
                    )

                from . import plugins_browser_pane as pane_module

                results = pane_module._execute_agent_cli_updates(
                    plan,
                    run_fn=task_runner,
                    trigger=UpdateTrigger.COMPREHENSIVE,
                )
            except Exception as exc:  # noqa: BLE001 - SASE must still run.
                error = error_text(exc)

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
        ordered = order_provider_results(
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
        preview: ComprehensiveUpdatePreview,
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
                    error_text(exc),
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
                error_text(exc),
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
                    error_text(exc),
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

    def _execute_agents_leg(
        self,
        preview: ComprehensiveUpdatePreview,
        reporter: TaskReporter,
    ) -> tuple[tuple[CachedIntegrationResult, ...], str | None]:
        """Import only the cached agent hoods captured by the preview."""
        if not preview.agents_runnable:
            return (), None
        try:
            reporter.phase("Importing cached incoming agent hoods")
            outcomes = tuple(integrate_cached_agent_updates(preview.agents_updates))
        except Exception as exc:  # noqa: BLE001 - retain successful prior legs.
            error = error_text(exc)
            reporter.section("Cached incoming hood results")
            reporter.log(
                f"Cached incoming hood import failed: {error}", stream="result"
            )
            return (), error

        reporter.section("Cached incoming hood results")
        for outcome in outcomes:
            reporter.log(cached_agents_result_line(outcome), stream="result")
        return outcomes, None


def order_provider_results(
    results: Sequence[AgentCliUpdateResult],
    captured_names: tuple[str, ...] | None,
) -> tuple[AgentCliUpdateResult, ...]:
    """Restore captured provider ordering after execution."""
    if not captured_names:
        return tuple(results)
    order = {name: index for index, name in enumerate(captured_names)}
    return tuple(sorted(results, key=lambda result: order.get(result.name, len(order))))


def comprehensive_update_summary(result: ComprehensiveUpdateResult) -> str:
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
    agents_line = "Cached agents: " + summarize_cached_agents_results(
        result.agents_outcomes
    )
    if result.agents_error:
        agents_line = f"Cached agents: failed — {result.agents_error}"
    return f"{sase_line}; {provider_line}; {agents_line}"
