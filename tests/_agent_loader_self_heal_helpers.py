"""Helpers for agent-loader self-heal and incomplete-history tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents import _loading
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState


SOURCE_SCAN_STATE = AgentLoadState(
    tier="tier2",
    complete_history=True,
    artifact_source="source_scan",
    used_artifact_index=False,
)
INCOMPLETE_SOURCE_SCAN_STATE = AgentLoadState(
    tier="tier1",
    complete_history=False,
    complete_visible_inbox=False,
    artifact_source="source_scan",
    used_artifact_index=False,
)
INCOMPLETE_INDEX_STATE = AgentLoadState(
    tier="tier1",
    complete_history=False,
    complete_visible_inbox=False,
    artifact_source="artifact_index",
    used_artifact_index=True,
)


def clear_cleaned_artifact_cache() -> None:
    """Clear the module-level artifact cleanup cache between tests."""
    _loading._CLEANED_ARTIFACT_DIRS.clear()


def make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for loader self-heal tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeLoadingApp(AgentLoadingMixin):
    """Minimal app exposing just the attrs touched by loader apply tests."""

    def __init__(self) -> None:
        self.current_tab = "changespecs"  # legacy tab id
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._has_always_visible = False
        self._hidden_count = 0
        self._hideable_agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._agent_search_query = ""
        self._agents_loading = False
        self._agent_load_state: AgentLoadState | None = None
        self._agents_seen_complete_history = False
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
        # Pretend the first async load already happened so _apply_loaded_agents
        # does not try to query widgets that are not mounted in this fake.
        self._agents_first_load_done = True
        # Deferred live-hint scan coalescing state. The apply path schedules a
        # scan once the list is finalized; this fake records the queued worker
        # via ``call_later`` but never runs it.
        self._live_hints_scan_scheduled = False
        self._live_hints_scan_running = False
        self._live_hints_scan_pending = False
        self._live_hints_scan_source = "unknown"
        # Deferred bead-confirmation warmup coalescing state (scheduled by the
        # same apply path; recorded via ``call_later`` but never run here).
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scan_running = False
        self._bead_warmup_scan_pending = False
        self._bead_warmup_scan_source = "unknown"
        # Deferred artifact-index maintenance scheduled by the apply path.
        self._artifact_index_maintenance_running = False
        self._artifact_index_maintenance_pending = False
        self._artifact_index_maintenance_pending_request = None
        self._artifact_index_maintenance_last_mono = 0.0
        self.call_later_calls: list[object] = []

    def set_timer(self, _delay: float, _callback: object) -> None:
        """Stub for apply paths that should not schedule timers here."""

    def call_later(self, callback: object, *args: object, **kwargs: object) -> None:
        """Stub recording the deferred live-hint worker without running it."""
        self.call_later_calls.append(callback)

    def _finalize_agent_list(self, *args: object, **kwargs: object) -> None:
        """Stub: the real finalizer needs tabbar/panel widgets we do not have."""
        if kwargs.get("save_unfiltered"):
            self._agents_with_children = list(self._agents)

    def _persist_dismissed_agent(
        self, identity: tuple[AgentType, str, str | None]
    ) -> None:
        self._dismissed_agents.add(identity)
