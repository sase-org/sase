"""Tests for the external-dismissal merge step in the TUI agent loader.

A long-lived ``sase ace`` TUI loads ``self._dismissed_agents`` once at
startup. External processes (Telegram kill, gchat, ``sase agents kill``)
can append to ``~/.sase/dismissed_agents.json`` while the TUI is running;
without re-merging on each refresh, the TUI would never observe those
external dismissals and would surface the killed agent as FAILED.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult
from sase.ace.tui.actions.agents._loading_disk import _ExternalDismissalMergeResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState


class _MergeApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agents_disk_signature: tuple[int, int] | None = None
        self._dismissed_agents_disk_identities: set[
            tuple[AgentType, str, str | None]
        ] = set()
        self._dismissed_agents_disk_signature_initialized = False


def test_merge_external_dismissals_unions_in_new_entries() -> None:
    app = _MergeApp()
    pre_existing = (AgentType.RUNNING, "memory_only", "20260510100000")
    app._dismissed_agents = {pre_existing}

    external = (AgentType.RUNNING, "telegram_killed", "20260510110000")
    with (
        patch("sase.ace.dismissed_agents.dismissed_agents_file_signature"),
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agents",
            return_value={external},
        ),
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

    with (
        patch("sase.ace.dismissed_agents.dismissed_agents_file_signature"),
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agents",
            return_value={on_disk},
        ),
    ):
        app._merge_external_dismissals()

    assert pending in app._dismissed_agents
    assert on_disk in app._dismissed_agents


def test_merge_external_dismissals_is_noop_when_disk_subset_of_memory() -> None:
    app = _MergeApp()
    shared = (AgentType.RUNNING, "shared", "20260510100000")
    extra = (AgentType.RUNNING, "extra", "20260510110000")
    app._dismissed_agents = {shared, extra}

    with (
        patch("sase.ace.dismissed_agents.dismissed_agents_file_signature"),
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agents",
            return_value={shared},
        ),
    ):
        app._merge_external_dismissals()

    assert app._dismissed_agents == {shared, extra}


def test_merge_external_dismissals_swallows_load_errors() -> None:
    """A corrupt index file must not crash the agents-tab refresh."""
    app = _MergeApp()
    pending = (AgentType.RUNNING, "in_memory", "20260510100000")
    app._dismissed_agents = {pending}

    with (
        patch("sase.ace.dismissed_agents.dismissed_agents_file_signature"),
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agents",
            side_effect=OSError("boom"),
        ),
    ):
        app._merge_external_dismissals()

    assert app._dismissed_agents == {pending}


def test_merge_external_dismissals_cache_hit_skips_disk_load() -> None:
    app = _MergeApp()
    shared = (AgentType.RUNNING, "shared", "20260510100000")
    app._dismissed_agents = {shared}
    app._dismissed_agents_disk_signature = (10, 200)
    app._dismissed_agents_disk_identities = {shared}
    app._dismissed_agents_disk_signature_initialized = True

    with (
        patch(
            "sase.ace.dismissed_agents.dismissed_agents_file_signature",
            return_value=(10, 200),
        ),
        patch("sase.ace.dismissed_agents.load_dismissed_agents") as mock_load,
    ):
        app._merge_external_dismissals()

    mock_load.assert_not_called()
    assert app._dismissed_agents == {shared}


def test_merge_external_dismissals_cache_miss_unions_only_new_disk_entries() -> None:
    app = _MergeApp()
    old_disk = (AgentType.RUNNING, "old_disk", "20260510100000")
    memory_only = (AgentType.RUNNING, "memory_only", "20260510110000")
    new_disk = (AgentType.RUNNING, "new_disk", "20260510120000")
    app._dismissed_agents = {memory_only}
    app._dismissed_agents_disk_signature = (10, 200)
    app._dismissed_agents_disk_identities = {old_disk}
    app._dismissed_agents_disk_signature_initialized = True

    with (
        patch(
            "sase.ace.dismissed_agents.dismissed_agents_file_signature",
            return_value=(11, 240),
        ),
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agents",
            return_value={old_disk, new_disk},
        ) as mock_load,
    ):
        app._merge_external_dismissals()

    mock_load.assert_called_once_with()
    assert app._dismissed_agents == {memory_only, new_disk}
    assert app._dismissed_agents_disk_signature == (11, 240)
    assert app._dismissed_agents_disk_identities == {old_disk, new_disk}


class _AsyncLoadApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents = []
        self._agents_with_children = []
        self._agents_last_identity = None
        self._agent_search_query = ""
        self._agents_seen_complete_history = False
        self._agent_load_state = None
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agents_disk_signature: tuple[int, int] | None = (10, 200)
        self._dismissed_agents_disk_identities: set[
            tuple[AgentType, str, str | None]
        ] = set()
        self._dismissed_agents_disk_signature_initialized = True
        self.applied = False
        self.applied_prep: Any = None
        self.applied_kwargs: dict[str, Any] | None = None

    def _apply_loaded_agents_prepared(self, *args: object, **kwargs: object) -> None:
        self.applied_prep = args[0]
        self.applied_kwargs = kwargs
        self.applied = True


async def test_load_agents_async_merges_external_dismissals_before_snapshot() -> None:
    app = _AsyncLoadApp()
    external = (AgentType.RUNNING, "telegram_killed", "20260510110000")
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    def fake_load_agents(
        dismissed_snapshot: set[tuple[AgentType, str, str | None]], **_: object
    ) -> _AgentDiskLoadResult:
        assert external in dismissed_snapshot
        return _AgentDiskLoadResult(
            all_agents=[],
            dismissed_from_loader=[],
            load_state=load_state,
        )

    with (
        patch(
            "sase.ace.tui.actions.agents._loading_disk._compute_external_dismissal_merge",
            return_value=_ExternalDismissalMergeResult(
                file_signature=(11, 240),
                on_disk_identities={external},
                new_external_identities={external},
            ),
        ) as mock_merge,
        patch(
            "sase.ace.changespec.find_all_changespecs_cached",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            side_effect=fake_load_agents,
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        await app._load_agents_async()

    mock_merge.assert_called_once()
    assert external in app._dismissed_agents
    assert app._dismissed_agents_disk_signature == (11, 240)
    assert app.applied is True


def _make_agent(cl_name: str, raw_suffix: str, status: str = "DONE") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/myproj/myproj.sase",
        status=status,
        start_time=datetime(2024, 1, 1, 12, 0, 0),
        raw_suffix=raw_suffix,
    )


async def test_load_agents_async_merges_post_history_tier1_in_worker() -> None:
    app = _AsyncLoadApp()
    active_cached = _make_agent("active", "20260202120000", status="RUNNING")
    active_updated = _make_agent("active", "20260202120000", status="DONE")
    historical = _make_agent("historical", "20240102120000")
    new_agent = _make_agent("new", "20260303120000", status="RUNNING")
    app._agents = [active_cached, historical]
    app._agents_with_children = list(app._agents)
    app._agents_seen_complete_history = True
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._loading_disk._compute_external_dismissal_merge",
            return_value=None,
        ),
        patch(
            "sase.ace.changespec.find_all_changespecs_cached",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            return_value=_AgentDiskLoadResult(
                all_agents=[new_agent, active_updated],
                dismissed_from_loader=[],
                load_state=load_state,
            ),
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        await app._load_agents_async()

    assert app.applied_kwargs is not None
    assert [agent.raw_suffix for agent in app.applied_prep.filtered_agents] == [
        "20260303120000",
        "20260202120000",
        "20240102120000",
    ]
    assert app.applied_prep.filtered_agents[1] is active_updated
    assert app.applied_kwargs["incomplete_merge_already_applied"] is True
