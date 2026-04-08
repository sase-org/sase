"""Integration tests verifying metrics are recorded at each instrumentation point.

Tests both enabled (real prometheus_client) and disabled (stub) paths.
Covers: agent lifecycle, LLM provider, axe orchestrator, hooks/mentors/workflows,
beads, VCS/workspace, and notifications.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from prometheus_client import CollectorRegistry

from sase.telemetry._config import _TelemetryConfig
from sase.telemetry._registry import init_telemetry
from sase.telemetry._stubs import StubCounter
from sase.telemetry import metrics as m
from tests.telemetry.conftest import (
    get_registry,
    reset_registry,
    reset_telemetry_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ENABLED_CFG = _TelemetryConfig(enabled=True)
_DISABLED_CFG = _TelemetryConfig(enabled=False)


@pytest.fixture(autouse=True)
def _reset_telemetry():
    """Reset telemetry state before and after every test."""
    reset_registry()
    reset_telemetry_config()
    yield
    reset_registry()
    reset_telemetry_config()


def _init_enabled() -> CollectorRegistry:
    """Initialize telemetry in enabled mode and return the registry."""
    with patch(
        "sase.telemetry._registry.get_telemetry_config", return_value=_ENABLED_CFG
    ):
        init_telemetry()
    reg = get_registry()
    assert reg is not None
    return reg


def _init_disabled() -> None:
    """Initialize telemetry in disabled mode."""
    with patch(
        "sase.telemetry._registry.get_telemetry_config", return_value=_DISABLED_CFG
    ):
        init_telemetry()


def _sample(
    reg: CollectorRegistry, name: str, labels: dict[str, str] | None = None
) -> float | None:
    """Read a sample value from the registry."""
    return reg.get_sample_value(name, labels or {})


# ===================================================================
# Agent Lifecycle
# ===================================================================


class TestAgentLifecycleEnabled:
    def test_agent_runs_counter(self) -> None:
        reg = _init_enabled()
        m.AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="crs").inc()
        assert (
            _sample(
                reg,
                "sase_agent_runs_total",
                {"llm_provider": "claude", "status": "ok", "workflow": "crs"},
            )
            == 1.0
        )

    def test_agent_run_duration_histogram(self) -> None:
        reg = _init_enabled()
        m.AGENT_RUN_DURATION.labels(llm_provider="claude", workflow="crs").observe(45.0)
        assert (
            _sample(
                reg,
                "sase_agent_run_duration_seconds_count",
                {"llm_provider": "claude", "workflow": "crs"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_agent_run_duration_seconds_sum",
                {"llm_provider": "claude", "workflow": "crs"},
            )
            == 45.0
        )

    def test_agent_active_gauge(self) -> None:
        reg = _init_enabled()
        m.AGENT_ACTIVE.labels(llm_provider="gemini", project="myproj").inc()
        assert (
            _sample(
                reg,
                "sase_agent_active",
                {"llm_provider": "gemini", "project": "myproj"},
            )
            == 1.0
        )
        m.AGENT_ACTIVE.labels(llm_provider="gemini", project="myproj").dec()
        assert (
            _sample(
                reg,
                "sase_agent_active",
                {"llm_provider": "gemini", "project": "myproj"},
            )
            == 0.0
        )

    def test_agent_spawns_counter(self) -> None:
        reg = _init_enabled()
        m.AGENT_SPAWNS.labels(llm_provider="claude", project="proj").inc()
        m.AGENT_SPAWNS.labels(llm_provider="claude", project="proj").inc()
        assert (
            _sample(
                reg,
                "sase_agent_spawns_total",
                {"llm_provider": "claude", "project": "proj"},
            )
            == 2.0
        )

    def test_agent_kills_counter(self) -> None:
        reg = _init_enabled()
        m.AGENT_KILLS.labels(reason="user").inc()
        assert _sample(reg, "sase_agent_kills_total", {"reason": "user"}) == 1.0


class TestAgentLifecycleDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        _init_disabled()
        assert isinstance(m.AGENT_RUNS, StubCounter)
        # All calls succeed as no-ops
        m.AGENT_RUNS.labels(llm_provider="x", status="ok", workflow="w").inc()
        m.AGENT_RUN_DURATION.labels(llm_provider="x", workflow="w").observe(1.0)
        m.AGENT_ACTIVE.labels(llm_provider="x", project="p").inc()
        m.AGENT_ACTIVE.labels(llm_provider="x", project="p").dec()
        m.AGENT_SPAWNS.labels(llm_provider="x", project="p").inc()
        m.AGENT_KILLS.labels(reason="timeout").inc()


# ===================================================================
# LLM Provider
# ===================================================================


class TestLLMProviderEnabled:
    def test_llm_invocations_counter(self) -> None:
        reg = _init_enabled()
        m.LLM_INVOCATIONS.labels(provider="claude", status="ok").inc()
        m.LLM_INVOCATIONS.labels(provider="claude", status="error").inc()
        assert (
            _sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "claude", "status": "ok"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "claude", "status": "error"},
            )
            == 1.0
        )

    def test_llm_invocation_duration_histogram(self) -> None:
        reg = _init_enabled()
        m.LLM_INVOCATION_DURATION.labels(provider="gemini").observe(2.5)
        assert (
            _sample(
                reg,
                "sase_llm_invocation_duration_seconds_count",
                {"provider": "gemini"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg, "sase_llm_invocation_duration_seconds_sum", {"provider": "gemini"}
            )
            == 2.5
        )

    def test_llm_errors_counter(self) -> None:
        reg = _init_enabled()
        m.LLM_ERRORS.labels(provider="claude", error_type="CalledProcessError").inc()
        assert (
            _sample(
                reg,
                "sase_llm_errors_total",
                {"provider": "claude", "error_type": "CalledProcessError"},
            )
            == 1.0
        )

    def test_llm_retries_counter(self) -> None:
        reg = _init_enabled()
        m.LLM_RETRIES.labels(provider="claude").inc()
        assert _sample(reg, "sase_llm_retries_total", {"provider": "claude"}) == 1.0


class TestLLMProviderDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        _init_disabled()
        assert isinstance(m.LLM_INVOCATIONS, StubCounter)
        m.LLM_INVOCATIONS.labels(provider="x", status="ok").inc()
        m.LLM_INVOCATION_DURATION.labels(provider="x").observe(1.0)
        m.LLM_ERRORS.labels(provider="x", error_type="Timeout").inc()
        m.LLM_RETRIES.labels(provider="x").inc()


# ===================================================================
# Axe Orchestrator
# ===================================================================


class TestAxeOrchestratorEnabled:
    def test_axe_cycles_counter(self) -> None:
        reg = _init_enabled()
        m.AXE_CYCLES.labels(cycle_type="tick").inc()
        assert _sample(reg, "sase_axe_cycles_total", {"cycle_type": "tick"}) == 1.0

    def test_axe_cycle_duration_histogram(self) -> None:
        reg = _init_enabled()
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.5)
        assert (
            _sample(
                reg, "sase_axe_cycle_duration_seconds_count", {"cycle_type": "tick"}
            )
            == 1.0
        )
        assert (
            _sample(reg, "sase_axe_cycle_duration_seconds_sum", {"cycle_type": "tick"})
            == 0.5
        )

    def test_axe_lumberjacks_active_gauge(self) -> None:
        reg = _init_enabled()
        m.AXE_LUMBERJACKS_ACTIVE.inc()
        m.AXE_LUMBERJACKS_ACTIVE.inc()
        assert _sample(reg, "sase_axe_lumberjacks_active") == 2.0
        m.AXE_LUMBERJACKS_ACTIVE.dec()
        assert _sample(reg, "sase_axe_lumberjacks_active") == 1.0

    def test_axe_lumberjack_restarts_counter(self) -> None:
        reg = _init_enabled()
        m.AXE_LUMBERJACK_RESTARTS.inc()
        assert _sample(reg, "sase_axe_lumberjack_restarts_total") == 1.0

    def test_axe_errors_counter(self) -> None:
        reg = _init_enabled()
        m.AXE_ERRORS.labels(error_type="crash").inc()
        assert _sample(reg, "sase_axe_errors_total", {"error_type": "crash"}) == 1.0


class TestAxeOrchestratorDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        _init_disabled()
        assert isinstance(m.AXE_CYCLES, StubCounter)
        m.AXE_CYCLES.labels(cycle_type="tick").inc()
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.1)
        m.AXE_LUMBERJACKS_ACTIVE.inc()
        m.AXE_LUMBERJACKS_ACTIVE.dec()
        m.AXE_LUMBERJACK_RESTARTS.inc()
        m.AXE_ERRORS.labels(error_type="crash").inc()


# ===================================================================
# Hooks / Mentors / Workflows
# ===================================================================


class TestHooksMentorsWorkflowsEnabled:
    def test_hook_executions_counter(self) -> None:
        reg = _init_enabled()
        m.HOOK_EXECUTIONS.labels(hook_type="pre-commit", status="started").inc()
        m.HOOK_EXECUTIONS.labels(hook_type="pre-commit", status="passed").inc()
        assert (
            _sample(
                reg,
                "sase_hook_executions_total",
                {"hook_type": "pre-commit", "status": "started"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_hook_executions_total",
                {"hook_type": "pre-commit", "status": "passed"},
            )
            == 1.0
        )

    def test_hook_duration_histogram(self) -> None:
        reg = _init_enabled()
        m.HOOK_DURATION.labels(hook_type="pre-commit").observe(3.2)
        assert (
            _sample(
                reg, "sase_hook_duration_seconds_count", {"hook_type": "pre-commit"}
            )
            == 1.0
        )
        assert (
            _sample(reg, "sase_hook_duration_seconds_sum", {"hook_type": "pre-commit"})
            == 3.2
        )

    def test_hook_retries_counter(self) -> None:
        reg = _init_enabled()
        m.HOOK_RETRIES.labels(hook_type="lint").inc(3)
        assert _sample(reg, "sase_hook_retries_total", {"hook_type": "lint"}) == 3.0

    def test_mentor_executions_counter(self) -> None:
        reg = _init_enabled()
        m.MENTOR_EXECUTIONS.labels(status="ok").inc()
        assert _sample(reg, "sase_mentor_executions_total", {"status": "ok"}) == 1.0

    def test_workflow_executions_counter(self) -> None:
        reg = _init_enabled()
        m.WORKFLOW_EXECUTIONS.labels(workflow="crs", status="ok").inc()
        m.WORKFLOW_EXECUTIONS.labels(workflow="fix-hook", status="error").inc()
        assert (
            _sample(
                reg,
                "sase_workflow_executions_total",
                {"workflow": "crs", "status": "ok"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_workflow_executions_total",
                {"workflow": "fix-hook", "status": "error"},
            )
            == 1.0
        )

    def test_workflow_duration_histogram(self) -> None:
        reg = _init_enabled()
        m.WORKFLOW_DURATION.labels(workflow="summarize-hook").observe(12.0)
        assert (
            _sample(
                reg,
                "sase_workflow_duration_seconds_count",
                {"workflow": "summarize-hook"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_workflow_duration_seconds_sum",
                {"workflow": "summarize-hook"},
            )
            == 12.0
        )

    def test_zombie_detections_counter(self) -> None:
        reg = _init_enabled()
        m.ZOMBIE_DETECTIONS.inc()
        assert _sample(reg, "sase_zombie_detections_total") == 1.0


class TestHooksMentorsWorkflowsDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        _init_disabled()
        assert isinstance(m.HOOK_EXECUTIONS, StubCounter)
        m.HOOK_EXECUTIONS.labels(hook_type="x", status="started").inc()
        m.HOOK_DURATION.labels(hook_type="x").observe(1.0)
        m.HOOK_RETRIES.labels(hook_type="x").inc(2)
        m.MENTOR_EXECUTIONS.labels(status="ok").inc()
        m.WORKFLOW_EXECUTIONS.labels(workflow="w", status="ok").inc()
        m.WORKFLOW_DURATION.labels(workflow="w").observe(1.0)
        m.ZOMBIE_DETECTIONS.inc()


# ===================================================================
# Beads
# ===================================================================


class TestBeadsEnabled:
    def test_bead_operations_counter(self) -> None:
        reg = _init_enabled()
        m.BEAD_OPERATIONS.labels(operation="create").inc()
        m.BEAD_OPERATIONS.labels(operation="update").inc()
        m.BEAD_OPERATIONS.labels(operation="close").inc()
        assert (
            _sample(reg, "sase_bead_operations_total", {"operation": "create"}) == 1.0
        )
        assert (
            _sample(reg, "sase_bead_operations_total", {"operation": "update"}) == 1.0
        )
        assert _sample(reg, "sase_bead_operations_total", {"operation": "close"}) == 1.0

    def test_bead_status_transitions_counter(self) -> None:
        reg = _init_enabled()
        m.BEAD_STATUS_TRANSITIONS.labels(
            from_status="open", to_status="in_progress"
        ).inc()
        m.BEAD_STATUS_TRANSITIONS.labels(
            from_status="in_progress", to_status="closed"
        ).inc()
        assert (
            _sample(
                reg,
                "sase_bead_status_transitions_total",
                {"from_status": "open", "to_status": "in_progress"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_bead_status_transitions_total",
                {"from_status": "in_progress", "to_status": "closed"},
            )
            == 1.0
        )

    def test_bead_active_gauge(self) -> None:
        reg = _init_enabled()
        m.BEAD_ACTIVE.labels(project="myproj", status="open").set(5)
        assert (
            _sample(reg, "sase_bead_active", {"project": "myproj", "status": "open"})
            == 5.0
        )
        m.BEAD_ACTIVE.labels(project="myproj", status="open").set(3)
        assert (
            _sample(reg, "sase_bead_active", {"project": "myproj", "status": "open"})
            == 3.0
        )


class TestBeadsDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        _init_disabled()
        assert isinstance(m.BEAD_OPERATIONS, StubCounter)
        m.BEAD_OPERATIONS.labels(operation="create").inc()
        m.BEAD_STATUS_TRANSITIONS.labels(from_status="open", to_status="closed").inc()
        m.BEAD_ACTIVE.labels(project="p", status="open").set(10)


# ===================================================================
# VCS / Workspace
# ===================================================================


class TestVCSWorkspaceEnabled:
    def test_vcs_commits_counter(self) -> None:
        reg = _init_enabled()
        m.VCS_COMMITS.labels(provider="git", type="create").inc()
        m.VCS_COMMITS.labels(provider="git", type="amend").inc()
        assert (
            _sample(
                reg, "sase_vcs_commits_total", {"provider": "git", "type": "create"}
            )
            == 1.0
        )
        assert (
            _sample(reg, "sase_vcs_commits_total", {"provider": "git", "type": "amend"})
            == 1.0
        )

    def test_vcs_operations_counter(self) -> None:
        reg = _init_enabled()
        m.VCS_OPERATIONS.labels(provider="git", operation="commit", status="ok").inc()
        m.VCS_OPERATIONS.labels(
            provider="git", operation="commit", status="error"
        ).inc()
        assert (
            _sample(
                reg,
                "sase_vcs_operations_total",
                {"provider": "git", "operation": "commit", "status": "ok"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_vcs_operations_total",
                {"provider": "git", "operation": "commit", "status": "error"},
            )
            == 1.0
        )

    def test_workspace_acquisitions_counter(self) -> None:
        reg = _init_enabled()
        m.WORKSPACE_ACQUISITIONS.labels(project="myproj").inc()
        assert (
            _sample(reg, "sase_workspace_acquisitions_total", {"project": "myproj"})
            == 1.0
        )

    def test_workspace_releases_counter(self) -> None:
        reg = _init_enabled()
        m.WORKSPACE_RELEASES.labels(project="myproj").inc()
        assert (
            _sample(reg, "sase_workspace_releases_total", {"project": "myproj"}) == 1.0
        )

    def test_workspace_active_gauge(self) -> None:
        reg = _init_enabled()
        m.WORKSPACE_ACTIVE.labels(project="myproj").inc()
        assert _sample(reg, "sase_workspace_active", {"project": "myproj"}) == 1.0
        m.WORKSPACE_ACTIVE.labels(project="myproj").dec()
        assert _sample(reg, "sase_workspace_active", {"project": "myproj"}) == 0.0


class TestVCSWorkspaceDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        _init_disabled()
        assert isinstance(m.VCS_COMMITS, StubCounter)
        m.VCS_COMMITS.labels(provider="git", type="create").inc()
        m.VCS_OPERATIONS.labels(provider="git", operation="commit", status="ok").inc()
        m.WORKSPACE_ACQUISITIONS.labels(project="p").inc()
        m.WORKSPACE_RELEASES.labels(project="p").inc()
        m.WORKSPACE_ACTIVE.labels(project="p").inc()
        m.WORKSPACE_ACTIVE.labels(project="p").dec()


# ===================================================================
# Notifications
# ===================================================================


class TestNotificationsEnabled:
    def test_notifications_sent_counter(self) -> None:
        reg = _init_enabled()
        m.NOTIFICATIONS_SENT.labels(type="workflow_complete", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="sync_result", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="error_digest", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="hitl_request", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="user_question", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="plan_approval", status="ok").inc()
        assert (
            _sample(
                reg,
                "sase_notifications_sent_total",
                {"type": "workflow_complete", "status": "ok"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_notifications_sent_total",
                {"type": "plan_approval", "status": "ok"},
            )
            == 1.0
        )


class TestNotificationsDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        _init_disabled()
        assert isinstance(m.NOTIFICATIONS_SENT, StubCounter)
        m.NOTIFICATIONS_SENT.labels(type="workflow_complete", status="ok").inc()


# ===================================================================
# Cross-cutting: multiple increments and label combinations
# ===================================================================


class TestCrossCutting:
    def test_counter_accumulates_across_multiple_inc(self) -> None:
        reg = _init_enabled()
        m.AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="").inc()
        m.AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="").inc()
        m.AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="").inc()
        assert (
            _sample(
                reg,
                "sase_agent_runs_total",
                {"llm_provider": "claude", "status": "ok", "workflow": ""},
            )
            == 3.0
        )

    def test_histogram_accumulates_observations(self) -> None:
        reg = _init_enabled()
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.1)
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.2)
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.3)
        assert (
            _sample(
                reg, "sase_axe_cycle_duration_seconds_count", {"cycle_type": "tick"}
            )
            == 3.0
        )
        assert _sample(
            reg, "sase_axe_cycle_duration_seconds_sum", {"cycle_type": "tick"}
        ) == pytest.approx(0.6)

    def test_distinct_label_values_tracked_independently(self) -> None:
        reg = _init_enabled()
        m.LLM_INVOCATIONS.labels(provider="claude", status="ok").inc()
        m.LLM_INVOCATIONS.labels(provider="gemini", status="ok").inc()
        m.LLM_INVOCATIONS.labels(provider="claude", status="error").inc()
        assert (
            _sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "claude", "status": "ok"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "gemini", "status": "ok"},
            )
            == 1.0
        )
        assert (
            _sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "claude", "status": "error"},
            )
            == 1.0
        )

    def test_gauge_set_overwrites_previous(self) -> None:
        reg = _init_enabled()
        m.BEAD_ACTIVE.labels(project="p", status="open").set(10)
        m.BEAD_ACTIVE.labels(project="p", status="open").set(7)
        assert (
            _sample(reg, "sase_bead_active", {"project": "p", "status": "open"}) == 7.0
        )

    def test_histogram_time_context_manager(self) -> None:
        reg = _init_enabled()
        with m.HOOK_DURATION.labels(hook_type="test").time():
            pass  # near-zero duration
        assert (
            _sample(reg, "sase_hook_duration_seconds_count", {"hook_type": "test"})
            == 1.0
        )
        total = _sample(reg, "sase_hook_duration_seconds_sum", {"hook_type": "test"})
        assert total is not None and total >= 0.0

    def test_all_metrics_recordable_after_init(self) -> None:
        """Every metric in METRIC_DEFS can be called after init without error."""
        from sase.telemetry.metrics import METRIC_DEFS

        _init_enabled()
        for attr, kind, _, _, labelnames, _ in METRIC_DEFS:
            metric = getattr(m, attr)
            labels = dict.fromkeys(labelnames, "test")
            labeled = metric.labels(**labels) if labelnames else metric
            if kind == "counter":
                labeled.inc()
            elif kind == "gauge":
                labeled.set(1)
            elif kind == "histogram":
                labeled.observe(0.1)

    def test_all_stubs_callable_when_disabled(self) -> None:
        """Every metric in METRIC_DEFS can be called as a stub without error."""
        from sase.telemetry.metrics import METRIC_DEFS

        _init_disabled()
        for attr, kind, _, _, labelnames, _ in METRIC_DEFS:
            metric = getattr(m, attr)
            labeled = (
                metric.labels(**dict.fromkeys(labelnames, "test"))
                if labelnames
                else metric
            )
            if kind == "counter":
                labeled.inc()
            elif kind == "gauge":
                labeled.set(1)
            elif kind == "histogram":
                labeled.observe(0.1)
