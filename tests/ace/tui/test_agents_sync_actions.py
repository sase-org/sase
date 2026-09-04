"""Tracked-task coverage for ACE agents-sidecar publication sync."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions import agents_sync
from sase.ace.tui.actions.agents_sync import AgentsSyncActionsMixin
from sase.agents_sync.models import SyncOutcome
from tests.ace.tui._proc_submit_signature_helpers import (
    assert_session_worker_submit_signature,
)
from tests.ace.tui._session_reporter import session_reporter as _reporter


class _Harness(AgentsSyncActionsMixin):
    def __init__(self) -> None:
        self.submitted: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.refresh_sources: list[str] = []

    def _submit_session_worker(self, *args: Any, **kwargs: Any) -> object:
        assert_session_worker_submit_signature(args, kwargs)
        self.submitted = (args, kwargs)
        return object()

    def _schedule_agents_async_refresh(self, *, source: str) -> None:
        self.refresh_sources.append(source)


def test_manual_sync_uses_tracked_deduplicated_scope_and_refreshes_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = (
        SyncOutcome("alpha", "Alpha", pulled=True),
        SyncOutcome("beta", "Beta", error="push failed"),
    )
    monkeypatch.setattr(agents_sync, "sync_agents", lambda: outcomes)
    app = _Harness()

    app.action_sync_agents()

    assert app.submitted is not None
    args, kwargs = app.submitted
    assert kwargs["display_name"] == "publish and reconcile agent hoods"
    assert kwargs["cl_name"] == "agent hoods"
    assert kwargs["dedup_key"] == "agents-sync"
    assert kwargs["exclusive_scopes"] == ("agents-sync",)
    assert (
        kwargs["duplicate_message"]
        == "An agents-sidecar publication sync is already running."
    )
    task_result = args[1](_reporter())
    assert task_result.success is False
    assert task_result.payload == outcomes
    assert task_result.message == "Agent hoods: 1 current, 1 failed"

    kwargs["on_complete"](None)
    assert app.refresh_sources == ["agents_full_sync"]
