"""Instrumentation tests for axe orchestrator, hooks, mentors, and workflows."""

from __future__ import annotations

from sase.telemetry._stubs import StubCounter
from sase.telemetry import metrics as m
from tests.telemetry.conftest import init_disabled, init_enabled, sample


# ===================================================================
# Axe Orchestrator
# ===================================================================


class TestAxeOrchestratorEnabled:
    def test_axe_cycles_counter(self) -> None:
        reg = init_enabled()
        m.AXE_CYCLES.labels(cycle_type="tick").inc()
        assert sample(reg, "sase_axe_cycles_total", {"cycle_type": "tick"}) == 1.0

    def test_axe_cycle_duration_histogram(self) -> None:
        reg = init_enabled()
        m.AXE_CYCLE_DURATION.labels(cycle_type="tick").observe(0.5)
        assert (
            sample(reg, "sase_axe_cycle_duration_seconds_count", {"cycle_type": "tick"})
            == 1.0
        )
        assert (
            sample(reg, "sase_axe_cycle_duration_seconds_sum", {"cycle_type": "tick"})
            == 0.5
        )

    def test_axe_lumberjacks_active_gauge(self) -> None:
        reg = init_enabled()
        m.AXE_LUMBERJACKS_ACTIVE.inc()
        m.AXE_LUMBERJACKS_ACTIVE.inc()
        assert sample(reg, "sase_axe_lumberjacks_active") == 2.0
        m.AXE_LUMBERJACKS_ACTIVE.dec()
        assert sample(reg, "sase_axe_lumberjacks_active") == 1.0

    def test_axe_lumberjack_restarts_counter(self) -> None:
        reg = init_enabled()
        m.AXE_LUMBERJACK_RESTARTS.inc()
        assert sample(reg, "sase_axe_lumberjack_restarts_total") == 1.0

    def test_axe_errors_counter(self) -> None:
        reg = init_enabled()
        m.AXE_ERRORS.labels(error_type="crash").inc()
        assert sample(reg, "sase_axe_errors_total", {"error_type": "crash"}) == 1.0


class TestAxeOrchestratorDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        init_disabled()
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
        reg = init_enabled()
        m.HOOK_EXECUTIONS.labels(hook_type="pre-commit", status="started").inc()
        m.HOOK_EXECUTIONS.labels(hook_type="pre-commit", status="passed").inc()
        assert (
            sample(
                reg,
                "sase_hook_executions_total",
                {"hook_type": "pre-commit", "status": "started"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_hook_executions_total",
                {"hook_type": "pre-commit", "status": "passed"},
            )
            == 1.0
        )

    def test_hook_duration_histogram(self) -> None:
        reg = init_enabled()
        m.HOOK_DURATION.labels(hook_type="pre-commit").observe(3.2)
        assert (
            sample(reg, "sase_hook_duration_seconds_count", {"hook_type": "pre-commit"})
            == 1.0
        )
        assert (
            sample(reg, "sase_hook_duration_seconds_sum", {"hook_type": "pre-commit"})
            == 3.2
        )

    def test_hook_retries_counter(self) -> None:
        reg = init_enabled()
        m.HOOK_RETRIES.labels(hook_type="lint").inc(3)
        assert sample(reg, "sase_hook_retries_total", {"hook_type": "lint"}) == 3.0

    def test_mentor_executions_counter(self) -> None:
        reg = init_enabled()
        m.MENTOR_EXECUTIONS.labels(status="ok").inc()
        assert sample(reg, "sase_mentor_executions_total", {"status": "ok"}) == 1.0

    def test_workflow_executions_counter(self) -> None:
        reg = init_enabled()
        m.WORKFLOW_EXECUTIONS.labels(workflow="crs", status="ok").inc()
        m.WORKFLOW_EXECUTIONS.labels(workflow="fix-hook", status="error").inc()
        assert (
            sample(
                reg,
                "sase_workflow_executions_total",
                {"workflow": "crs", "status": "ok"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_workflow_executions_total",
                {"workflow": "fix-hook", "status": "error"},
            )
            == 1.0
        )

    def test_workflow_duration_histogram(self) -> None:
        reg = init_enabled()
        m.WORKFLOW_DURATION.labels(workflow="summarize-hook").observe(12.0)
        assert (
            sample(
                reg,
                "sase_workflow_duration_seconds_count",
                {"workflow": "summarize-hook"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_workflow_duration_seconds_sum",
                {"workflow": "summarize-hook"},
            )
            == 12.0
        )

    def test_zombie_detections_counter(self) -> None:
        reg = init_enabled()
        m.ZOMBIE_DETECTIONS.inc()
        assert sample(reg, "sase_zombie_detections_total") == 1.0


class TestHooksMentorsWorkflowsDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        init_disabled()
        assert isinstance(m.HOOK_EXECUTIONS, StubCounter)
        m.HOOK_EXECUTIONS.labels(hook_type="x", status="started").inc()
        m.HOOK_DURATION.labels(hook_type="x").observe(1.0)
        m.HOOK_RETRIES.labels(hook_type="x").inc(2)
        m.MENTOR_EXECUTIONS.labels(status="ok").inc()
        m.WORKFLOW_EXECUTIONS.labels(workflow="w", status="ok").inc()
        m.WORKFLOW_DURATION.labels(workflow="w").observe(1.0)
        m.ZOMBIE_DETECTIONS.inc()
