"""Integration of ``AgentPanelIndex`` into refresh paths (Phase 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panel_index import AgentPanelIndex
from sase.ace.tui.models.agent_panels import AgentPanelGroup


def _agent(*, suffix: str, tag: str | None = None, status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.gp",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name="alpha",
        tag=tag,
        raw_suffix=suffix,
    )


class _Bare(AgentDisplayMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._panel_keys_cache = None
        self._agent_panel_index_cache = None
        self._panel_group = AgentPanelGroup.from_agents(agents)
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._marked_agents = set()
        self._fold_counts = {}
        self.current_idx = 0
        self.current_attempt_number = None
        self._current_group_key = None


def test_panel_index_is_cached_per_agents_ref() -> None:
    agents = [_agent(suffix="a"), _agent(suffix="b", tag="x")]
    bare = _Bare(agents)
    index1 = bare._agent_panel_index()
    index2 = bare._agent_panel_index()
    assert index1 is index2
    # Replacing the agents list invalidates the cache.
    bare._agents = list(agents)
    index3 = bare._agent_panel_index()
    assert index3 is not index1


def test_panel_index_exposes_per_panel_slices_and_counts() -> None:
    agents = [
        _agent(suffix="a", status="DONE"),
        _agent(suffix="b", tag="alpha"),
        _agent(suffix="c", tag="alpha", status="FAILED"),
    ]
    bare = _Bare(agents)
    index = bare._agent_panel_index()
    assert isinstance(index, AgentPanelIndex)
    assert index.keys_per_agent == [None, "alpha", "alpha"]
    untagged = index.slice_for(None)
    assert untagged.global_indices == [0]
    alpha = index.slice_for("alpha")
    assert alpha.global_indices == [1, 2]
    assert alpha.global_to_local == {1: 0, 2: 1}
    assert index.completed_count == 2  # DONE + FAILED


def test_refresh_panel_highlights_does_not_rebuild_global_indices(
    monkeypatch: Any,
) -> None:
    """The highlight refresh must read from the cached panel index, not rebuild."""

    agents = [_agent(suffix=f"t{i}") for i in range(50)]
    bare = _Bare(agents)
    bare.current_idx = 17

    captured: list[int] = []

    class _Widget:
        def update_highlight(self, local_idx: int, *_a: Any, **_k: Any) -> None:
            captured.append(local_idx)

        def add_class(self, _name: str) -> None:
            return

        def remove_class(self, _name: str) -> None:
            return

    def _query_one(_selector: str, _type: Any = None) -> Any:
        return _Widget()

    def _query(_selector: str) -> Any:
        class _Result:
            def results(self, _t: Any) -> list[Any]:
                return []

        return _Result()

    bare.query_one = _query_one  # type: ignore[attr-defined]
    bare.query = _query  # type: ignore[attr-defined]

    # Sentinel: panel_key_per_agent must not be re-called inside the refresh
    # path — the cached index already holds it.
    from sase.ace.tui.models import agent_panels as panels_mod

    calls = {"n": 0}

    def _spy(*_a: Any, **_k: Any) -> Any:
        calls["n"] += 1
        return panels_mod.panel_key_per_agent(*_a, **_k)

    # Warm the cache first.
    bare._agent_panel_index()
    monkeypatch.setattr(panels_mod, "panel_key_per_agent", _spy)

    for _ in range(100):
        bare._refresh_panel_highlights()

    assert calls["n"] == 0, "cached panel index should serve all 100 j/k refreshes"
    assert captured and all(idx == 17 for idx in captured)


def test_completed_count_precomputed_for_footer() -> None:
    agents = [
        _agent(suffix="a", status="RUNNING"),
        _agent(suffix="b", status="DONE"),
        _agent(suffix="c", status="FAILED"),
        _agent(suffix="d", status="WAIT"),
    ]
    bare = _Bare(agents)
    assert bare._agent_panel_index().completed_count == 2


def test_non_child_position_is_o1_lookup() -> None:
    agents = [
        _agent(suffix="parent"),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="cl",
            project_file="/r/p/p.gp",
            status="RUNNING",
            start_time=datetime(2026, 4, 25, 12, 0, 0),
            agent_name="child",
            raw_suffix=None,
            parent_timestamp="parent",
        ),
        _agent(suffix="next"),
    ]
    bare = _Bare(agents)
    index = bare._agent_panel_index()
    assert index.non_child_indices == [0, 2]
    assert index.non_child_total == 2
    assert index.non_child_position(0) == 1
    assert index.non_child_position(2) == 2
