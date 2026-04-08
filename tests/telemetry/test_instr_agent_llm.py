"""Instrumentation tests for agent lifecycle and LLM provider metrics."""

from __future__ import annotations

from sase.telemetry._stubs import StubCounter
from sase.telemetry import metrics as m
from tests.telemetry.conftest import init_disabled, init_enabled, sample


# ===================================================================
# Agent Lifecycle
# ===================================================================


class TestAgentLifecycleEnabled:
    def test_agent_runs_counter(self) -> None:
        reg = init_enabled()
        m.AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="crs").inc()
        assert (
            sample(
                reg,
                "sase_agent_runs_total",
                {"llm_provider": "claude", "status": "ok", "workflow": "crs"},
            )
            == 1.0
        )

    def test_agent_run_duration_histogram(self) -> None:
        reg = init_enabled()
        m.AGENT_RUN_DURATION.labels(llm_provider="claude", workflow="crs").observe(45.0)
        assert (
            sample(
                reg,
                "sase_agent_run_duration_seconds_count",
                {"llm_provider": "claude", "workflow": "crs"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_agent_run_duration_seconds_sum",
                {"llm_provider": "claude", "workflow": "crs"},
            )
            == 45.0
        )

    def test_agent_active_gauge(self) -> None:
        reg = init_enabled()
        m.AGENT_ACTIVE.labels(llm_provider="gemini", project="myproj").inc()
        assert (
            sample(
                reg,
                "sase_agent_active",
                {"llm_provider": "gemini", "project": "myproj"},
            )
            == 1.0
        )
        m.AGENT_ACTIVE.labels(llm_provider="gemini", project="myproj").dec()
        assert (
            sample(
                reg,
                "sase_agent_active",
                {"llm_provider": "gemini", "project": "myproj"},
            )
            == 0.0
        )

    def test_agent_spawns_counter(self) -> None:
        reg = init_enabled()
        m.AGENT_SPAWNS.labels(llm_provider="claude", project="proj").inc()
        m.AGENT_SPAWNS.labels(llm_provider="claude", project="proj").inc()
        assert (
            sample(
                reg,
                "sase_agent_spawns_total",
                {"llm_provider": "claude", "project": "proj"},
            )
            == 2.0
        )

    def test_agent_kills_counter(self) -> None:
        reg = init_enabled()
        m.AGENT_KILLS.labels(reason="user").inc()
        assert sample(reg, "sase_agent_kills_total", {"reason": "user"}) == 1.0


class TestAgentLifecycleDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        init_disabled()
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
        reg = init_enabled()
        m.LLM_INVOCATIONS.labels(provider="claude", status="ok").inc()
        m.LLM_INVOCATIONS.labels(provider="claude", status="error").inc()
        assert (
            sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "claude", "status": "ok"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_llm_invocations_total",
                {"provider": "claude", "status": "error"},
            )
            == 1.0
        )

    def test_llm_invocation_duration_histogram(self) -> None:
        reg = init_enabled()
        m.LLM_INVOCATION_DURATION.labels(provider="gemini").observe(2.5)
        assert (
            sample(
                reg,
                "sase_llm_invocation_duration_seconds_count",
                {"provider": "gemini"},
            )
            == 1.0
        )
        assert (
            sample(
                reg, "sase_llm_invocation_duration_seconds_sum", {"provider": "gemini"}
            )
            == 2.5
        )

    def test_llm_errors_counter(self) -> None:
        reg = init_enabled()
        m.LLM_ERRORS.labels(provider="claude", error_type="CalledProcessError").inc()
        assert (
            sample(
                reg,
                "sase_llm_errors_total",
                {"provider": "claude", "error_type": "CalledProcessError"},
            )
            == 1.0
        )

    def test_llm_retries_counter(self) -> None:
        reg = init_enabled()
        m.LLM_RETRIES.labels(provider="claude").inc()
        assert sample(reg, "sase_llm_retries_total", {"provider": "claude"}) == 1.0


class TestLLMProviderDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        init_disabled()
        assert isinstance(m.LLM_INVOCATIONS, StubCounter)
        m.LLM_INVOCATIONS.labels(provider="x", status="ok").inc()
        m.LLM_INVOCATION_DURATION.labels(provider="x").observe(1.0)
        m.LLM_ERRORS.labels(provider="x", error_type="Timeout").inc()
        m.LLM_RETRIES.labels(provider="x").inc()
