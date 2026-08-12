"""Shared fixtures for the Phase-3 agents-tab query integration tests.

Hosts the synthetic :class:`Agent` factory and the ``FakeAgentApp`` stub used
to drive :meth:`AgentLoadingMixin._finalize_agent_list` without mounting any
Textual widgets.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.fold_state import FoldStateManager


_NOW = datetime(2026, 4, 26, 12, 0, 0)


def _make_agent(**overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "my_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "RUNNING",
        "start_time": _NOW,
    }
    defaults.update(overrides)
    return Agent(**defaults)


class _FakeContentCache:
    """Empty content cache stub — metadata-only matching."""

    def get_haystack(self, _agent: Agent) -> str:
        return ""

    def prune(self, _agents: Any) -> None:
        pass


class _FakeFoldRegistry:
    def clear_unknown(self, _keys: Any) -> None:
        pass


class FakeAgentApp(AgentLoadingMixin):
    """Minimal app exposing just the attributes ``_finalize_agent_list`` needs."""

    def __init__(self, query: str = "") -> None:
        self.current_tab = "changespecs"  # avoid widget queries  # legacy tab id
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
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._agent_search_query = query
        self._agent_content_search_cache = _FakeContentCache()  # type: ignore[assignment]
        self._agent_content_search_index = None
        self._agent_content_search_source_generation = 0
        self._agent_content_search_refresh_generation = 0
        self._agent_query_cache = None
        self._agent_query_parse_error = None
        self._fold_manager = FoldStateManager()
        self._fold_counts = {}
        self._group_fold_registry = _FakeFoldRegistry()  # type: ignore[assignment]
        self._grouping_mode = GroupingMode.STANDARD
        self._agents_loading = False
        self._agents_first_load_done = True
        # Deferred live-hint scan coalescing state (the apply path schedules a
        # scan once the list is finalized). These fakes stay on the patches
        # tab, so the scheduled worker is recorded but never runs.
        self._live_hints_scan_scheduled = False
        self._live_hints_scan_running = False
        self._live_hints_scan_pending = False
        self._live_hints_scan_source = "unknown"
        # Deferred bead-confirmation warmup coalescing state (same apply path).
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scan_running = False
        self._bead_warmup_scan_pending = False
        self._bead_warmup_scan_source = "unknown"
        # Deferred persisted diff-badge classification coalescing state (same
        # apply path).
        self._diff_badge_scan_scheduled = False
        self._diff_badge_scan_running = False
        self._diff_badge_scan_pending = False
        self._diff_badge_scan_source = "unknown"
        self.timer_calls: list[tuple[float, Callable[[], Any]]] = []
        self.call_later_calls: list[Callable[..., Any]] = []
        self.notify = MagicMock()  # type: ignore[assignment]

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> Any:
        self.timer_calls.append((delay, callback))
        return None

    def call_later(
        self, callback: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        self.call_later_calls.append(callback)
        return None

    # Stubs for methods the finalizer calls when on agents tab — not
    # exercised because our fake stays on patches tab.
    def _refresh_agents_display(self, **_kwargs: Any) -> None:
        pass

    def _get_selected_agent(self) -> Agent | None:
        return None

    def _restore_focus_after_removal(self, _prior_pos: int) -> None:
        pass

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("widgets not mounted")
