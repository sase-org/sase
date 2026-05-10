"""Tests for the external-dismissal merge step in the TUI agent loader.

A long-lived ``sase ace`` TUI loads ``self._dismissed_agents`` once at
startup. External processes (Telegram kill, gchat, ``sase agents kill``)
can append to ``~/.sase/dismissed_agents.json`` while the TUI is running;
without re-merging on each refresh, the TUI would never observe those
external dismissals and would surface the killed agent as FAILED.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.models.agent import AgentType


class _MergeApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()


def test_merge_external_dismissals_unions_in_new_entries() -> None:
    app = _MergeApp()
    pre_existing = (AgentType.RUNNING, "memory_only", "20260510100000")
    app._dismissed_agents = {pre_existing}

    external = (AgentType.RUNNING, "telegram_killed", "20260510110000")
    with patch(
        "sase.ace.dismissed_agents.load_dismissed_agents",
        return_value={external},
    ):
        app._merge_external_dismissals()

    assert pre_existing in app._dismissed_agents
    assert external in app._dismissed_agents


def test_merge_external_dismissals_preserves_pending_in_memory_entries() -> None:
    """Optimistic kill flow updates memory before disk; the merge must not stomp."""
    app = _MergeApp()
    pending = (AgentType.RUNNING, "in_memory_only", "20260510100000")
    on_disk = (AgentType.RUNNING, "on_disk_only", "20260510120000")
    app._dismissed_agents = {pending}

    with patch(
        "sase.ace.dismissed_agents.load_dismissed_agents",
        return_value={on_disk},
    ):
        app._merge_external_dismissals()

    assert pending in app._dismissed_agents
    assert on_disk in app._dismissed_agents


def test_merge_external_dismissals_is_noop_when_disk_subset_of_memory() -> None:
    app = _MergeApp()
    shared = (AgentType.RUNNING, "shared", "20260510100000")
    extra = (AgentType.RUNNING, "extra", "20260510110000")
    app._dismissed_agents = {shared, extra}

    with patch(
        "sase.ace.dismissed_agents.load_dismissed_agents",
        return_value={shared},
    ):
        app._merge_external_dismissals()

    assert app._dismissed_agents == {shared, extra}


def test_merge_external_dismissals_swallows_load_errors() -> None:
    """A corrupt index file must not crash the agents-tab refresh."""
    app = _MergeApp()
    pending = (AgentType.RUNNING, "in_memory", "20260510100000")
    app._dismissed_agents = {pending}

    with patch(
        "sase.ace.dismissed_agents.load_dismissed_agents",
        side_effect=OSError("boom"),
    ):
        app._merge_external_dismissals()

    assert app._dismissed_agents == {pending}
