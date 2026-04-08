"""Instrumentation tests for beads, VCS/workspace, and notification metrics."""

from __future__ import annotations

from sase.telemetry._stubs import StubCounter
from sase.telemetry import metrics as m
from tests.telemetry.conftest import init_disabled, init_enabled, sample


# ===================================================================
# Beads
# ===================================================================


class TestBeadsEnabled:
    def test_bead_operations_counter(self) -> None:
        reg = init_enabled()
        m.BEAD_OPERATIONS.labels(operation="create").inc()
        m.BEAD_OPERATIONS.labels(operation="update").inc()
        m.BEAD_OPERATIONS.labels(operation="close").inc()
        assert sample(reg, "sase_bead_operations_total", {"operation": "create"}) == 1.0
        assert sample(reg, "sase_bead_operations_total", {"operation": "update"}) == 1.0
        assert sample(reg, "sase_bead_operations_total", {"operation": "close"}) == 1.0

    def test_bead_status_transitions_counter(self) -> None:
        reg = init_enabled()
        m.BEAD_STATUS_TRANSITIONS.labels(
            from_status="open", to_status="in_progress"
        ).inc()
        m.BEAD_STATUS_TRANSITIONS.labels(
            from_status="in_progress", to_status="closed"
        ).inc()
        assert (
            sample(
                reg,
                "sase_bead_status_transitions_total",
                {"from_status": "open", "to_status": "in_progress"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_bead_status_transitions_total",
                {"from_status": "in_progress", "to_status": "closed"},
            )
            == 1.0
        )

    def test_bead_active_gauge(self) -> None:
        reg = init_enabled()
        m.BEAD_ACTIVE.labels(project="myproj", status="open").set(5)
        assert (
            sample(reg, "sase_bead_active", {"project": "myproj", "status": "open"})
            == 5.0
        )
        m.BEAD_ACTIVE.labels(project="myproj", status="open").set(3)
        assert (
            sample(reg, "sase_bead_active", {"project": "myproj", "status": "open"})
            == 3.0
        )


class TestBeadsDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        init_disabled()
        assert isinstance(m.BEAD_OPERATIONS, StubCounter)
        m.BEAD_OPERATIONS.labels(operation="create").inc()
        m.BEAD_STATUS_TRANSITIONS.labels(from_status="open", to_status="closed").inc()
        m.BEAD_ACTIVE.labels(project="p", status="open").set(10)


# ===================================================================
# VCS / Workspace
# ===================================================================


class TestVCSWorkspaceEnabled:
    def test_vcs_commits_counter(self) -> None:
        reg = init_enabled()
        m.VCS_COMMITS.labels(provider="git", type="create").inc()
        m.VCS_COMMITS.labels(provider="git", type="amend").inc()
        assert (
            sample(reg, "sase_vcs_commits_total", {"provider": "git", "type": "create"})
            == 1.0
        )
        assert (
            sample(reg, "sase_vcs_commits_total", {"provider": "git", "type": "amend"})
            == 1.0
        )

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

    def test_workspace_acquisitions_counter(self) -> None:
        reg = init_enabled()
        m.WORKSPACE_ACQUISITIONS.labels(project="myproj").inc()
        assert (
            sample(reg, "sase_workspace_acquisitions_total", {"project": "myproj"})
            == 1.0
        )

    def test_workspace_releases_counter(self) -> None:
        reg = init_enabled()
        m.WORKSPACE_RELEASES.labels(project="myproj").inc()
        assert (
            sample(reg, "sase_workspace_releases_total", {"project": "myproj"}) == 1.0
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
        reg = init_enabled()
        m.NOTIFICATIONS_SENT.labels(type="workflow_complete", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="sync_result", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="error_digest", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="hitl_request", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="user_question", status="ok").inc()
        m.NOTIFICATIONS_SENT.labels(type="plan_approval", status="ok").inc()
        assert (
            sample(
                reg,
                "sase_notifications_sent_total",
                {"type": "workflow_complete", "status": "ok"},
            )
            == 1.0
        )
        assert (
            sample(
                reg,
                "sase_notifications_sent_total",
                {"type": "plan_approval", "status": "ok"},
            )
            == 1.0
        )


class TestNotificationsDisabled:
    def test_stubs_accept_all_operations(self) -> None:
        init_disabled()
        assert isinstance(m.NOTIFICATIONS_SENT, StubCounter)
        m.NOTIFICATIONS_SENT.labels(type="workflow_complete", status="ok").inc()
