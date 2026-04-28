"""Tests for kill agent functionality."""

from __future__ import annotations

from unittest.mock import patch

# --- Kill Agent Tests ---


def test_kill_process_group_process_already_dead() -> None:
    """Test _kill_process_group handles ProcessLookupError."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    with patch(
        "sase.ace.tui.actions.agents._killing.os.killpg", side_effect=ProcessLookupError
    ):
        result = app._kill_process_group(12345)
        assert result is True  # Still considered success


def test_kill_process_group_permission_error() -> None:
    """Test _kill_process_group handles PermissionError."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

    app = MockApp()

    with patch(
        "sase.ace.tui.actions.agents._killing.os.killpg", side_effect=PermissionError
    ):
        result = app._kill_process_group(12345)
        assert result is False  # Permission error is a failure
        assert len(app._notifications) == 1
        assert "Permission denied" in app._notifications[0][0]
        assert app._notifications[0][1] == "error"


def test_no_legacy_sync_kill_handlers_referenced() -> None:
    """Removed per-type kill methods are unreachable from AgentKillingMixin's MRO."""
    from sase.ace.tui.actions.agents._killing import AgentKillingMixin

    removed_names = {
        "_kill_running_agent",
        "_kill_hook_agent",
        "_kill_mentor_agent",
        "_kill_crs_agent",
        "_kill_workflow_agent",
    }

    mro_attrs: set[str] = set()
    for cls in AgentKillingMixin.mro():
        mro_attrs.update(vars(cls).keys())

    leaked = removed_names & mro_attrs
    assert not leaked, f"Legacy synchronous kill handlers still reachable: {leaked}"
