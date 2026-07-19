"""Instrumentation tests for retained VCS and workspace health metrics."""

from __future__ import annotations

from sase.telemetry import metrics as m
from sase.telemetry._stubs import StubCounter
from tests.telemetry.conftest import init_disabled, init_enabled, sample


class TestVCSWorkspaceEnabled:
    def test_vcs_operations_counter(self) -> None:
        reg = init_enabled()
        m.VCS_OPERATIONS.labels(provider="git", operation="commit", status="ok").inc()
        m.VCS_OPERATIONS.labels(
            provider="git", operation="commit", status="error"
        ).inc()
        assert (
            sample(
                reg,
                "sase_vcs_operations_total",
                {"provider": "git", "operation": "commit", "status": "ok"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_vcs_operations_total",
                {"provider": "git", "operation": "commit", "status": "error"},
            )
            == 1.0
        )

    def test_workspace_active_gauge(self) -> None:
        reg = init_enabled()
        m.WORKSPACE_ACTIVE.labels(project="myproj").inc()
        assert sample(reg, "sase_workspace_active", {"project": "myproj"}) == 1.0
        m.WORKSPACE_ACTIVE.labels(project="myproj").dec()
        assert sample(reg, "sase_workspace_active", {"project": "myproj"}) == 0.0


class TestVCSWorkspaceDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        init_disabled()
        assert isinstance(m.VCS_OPERATIONS, StubCounter)
        m.VCS_OPERATIONS.labels(provider="git", operation="commit", status="ok").inc()
        m.WORKSPACE_ACTIVE.labels(project="p").inc()
        m.WORKSPACE_ACTIVE.labels(project="p").dec()
