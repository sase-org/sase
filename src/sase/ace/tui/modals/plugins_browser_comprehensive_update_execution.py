"""Execution helpers for comprehensive SASE, CLI, and agents-repo updates."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.update_scope import UpdateLeg, UpdateScope
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    UpdateResultStatus,
    UpdateTrigger,
)
from sase.agents_sync import integrate_cached_agent_updates
from sase.agents_sync.models import CachedIntegrationResult
from sase.ace.tui.agents_sync_format import summarize_cached_agents_results
from sase.dev_update.journal import append_dev_update_journal
from sase.main.update_types import CombinedUpdateResult

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

if TYPE_CHECKING:
    from sase.dev_update.models import DevUpdatePlan, DevUpdateResult

_SCOPED_UPDATE_NAMES: dict[UpdateScope, tuple[str, str]] = {
    UpdateScope.EVERYTHING: (
        "comprehensive update",
        "sase + agent CLIs + cached hoods",
    ),
    UpdateScope.SASE: ("update SASE, core & plugins", "sase"),
    UpdateScope.PROVIDERS: ("update providers", "agent CLIs"),
    UpdateScope.AGENTS: ("import published agents", "cached hoods"),
}

_PREVIEW_CL_NAMES: dict[UpdateScope, str] = {
    UpdateScope.EVERYTHING: "everything",
    UpdateScope.SASE: "sase",
    UpdateScope.PROVIDERS: "providers",
    UpdateScope.AGENTS: "agents",
}

_UNSELECTED_SASE = ComprehensiveSaseUpdateResult(
    SaseUpdateResultStatus.SKIPPED,
    "not selected",
)


def scoped_update_proc_names(scope: UpdateScope) -> tuple[str, str]:
    """Return ``(display_name, cl_name)`` for the mutation proc."""
    return _SCOPED_UPDATE_NAMES[scope]


def scoped_preview_cl_name(scope: UpdateScope) -> str:
    """Return the planning-proc ``cl_name`` for *scope*."""
    return _PREVIEW_CL_NAMES[scope]


def _execute_provider_leg(
    preview: ComprehensiveUpdatePreview,
) -> tuple[tuple[AgentCliUpdateResult, ...], str | None]:
    """Execute provider commands first, preserving skips and drops."""
    plan = preview.provider_plan
    results: tuple[AgentCliUpdateResult, ...] = ()
    error: str | None = None
    if isinstance(plan, (AgentCliUpdatesReady, AgentCliNothingToUpdate)):
        try:
            from . import plugins_browser_pane as pane_module

            results = pane_module._execute_agent_cli_updates(
                plan,
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
    return ordered, error


def _execute_sase_leg(
    preview: ComprehensiveUpdatePreview,
    uv_tool: object | None,
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
            from . import plugins_browser_pane as pane_module

            summary, elapsed = pane_module._run_sase_update_summary(uv_tool)
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
        from . import plugins_browser_pane as pane_module

        dev_result = pane_module._execute_tui_dev_update(plan)
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
            from . import plugins_browser_pane as pane_module

            managed_summary, _ = pane_module._run_planned_sase_update_summary(
                sase_preview.managed_argv,
                sase_preview.managed_packages,
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
    preview: ComprehensiveUpdatePreview,
) -> tuple[tuple[CachedIntegrationResult, ...], str | None]:
    """Import only the cached agent hoods captured by the preview."""
    if not preview.agents_runnable:
        return (), None
    try:
        outcomes = tuple(integrate_cached_agent_updates(preview.agents_updates))
    except Exception as exc:  # noqa: BLE001 - retain successful prior legs.
        return (), error_text(exc)

    return outcomes, None


def run_scoped_update(
    preview: ComprehensiveUpdatePreview,
    uv_tool: object | None,
) -> ComprehensiveUpdateResult:
    """Execute only the selected legs and record unselected SASE as skipped."""
    start = time.monotonic()
    selected = preview.selected_legs
    if UpdateLeg.PROVIDERS in selected:
        provider_results, provider_error = _execute_provider_leg(preview)
        provider_error = provider_error or preview.provider_error
    else:
        provider_results, provider_error = (), None
    if UpdateLeg.SASE in selected:
        sase_result = _execute_sase_leg(preview, uv_tool)
    else:
        sase_result = _UNSELECTED_SASE
    if UpdateLeg.AGENTS in selected:
        agents_outcomes, agents_error = _execute_agents_leg(preview)
        agents_error = agents_error or preview.agents_error
    else:
        agents_outcomes, agents_error = (), None
    return ComprehensiveUpdateResult(
        sase=sase_result,
        provider_results=provider_results,
        provider_error=provider_error,
        agents_outcomes=agents_outcomes,
        agents_error=agents_error,
        elapsed=max(0.0, time.monotonic() - start),
        selected_legs=selected,
    )


class ComprehensiveUpdateExecutionMixin:
    """Thin wrappers so pane tests can still override per-leg execution."""

    if TYPE_CHECKING:
        _uv_tool: object | None

        def _execute_dev_update(
            self, plan: DevUpdatePlan, *, run: Any = None
        ) -> DevUpdateResult: ...

    def _execute_provider_leg(
        self,
        preview: ComprehensiveUpdatePreview,
    ) -> tuple[tuple[AgentCliUpdateResult, ...], str | None]:
        return _execute_provider_leg(preview)

    def _execute_comprehensive_sase_leg(
        self,
        preview: ComprehensiveUpdatePreview,
    ) -> ComprehensiveSaseUpdateResult:
        return _execute_sase_leg(preview, getattr(self, "_uv_tool", None))

    def _execute_agents_leg(
        self,
        preview: ComprehensiveUpdatePreview,
    ) -> tuple[tuple[CachedIntegrationResult, ...], str | None]:
        return _execute_agents_leg(preview)


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
    lines: list[str] = []
    selected = result.selected_legs
    if UpdateLeg.SASE in selected:
        lines.append(f"SASE, core & plugins: {result.sase.message}")
    if UpdateLeg.PROVIDERS in selected:
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
        provider_parts = [
            f"{count} {label}" for label, count in counts.items() if count
        ]
        lines.append(
            "Agent CLIs: "
            + (", ".join(provider_parts) if provider_parts else "no captured work")
        )
    if UpdateLeg.AGENTS in selected:
        agents_line = "Cached agents: " + summarize_cached_agents_results(
            result.agents_outcomes
        )
        if result.agents_error:
            agents_line = f"Cached agents: failed — {result.agents_error}"
        lines.append(agents_line)
    return "; ".join(lines)


__all__ = [
    "ComprehensiveUpdateExecutionMixin",
    "comprehensive_update_summary",
    "order_provider_results",
    "run_scoped_update",
    "scoped_preview_cl_name",
    "scoped_update_proc_names",
]
