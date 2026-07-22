"""Integration of ``AgentPanelIndex`` into refresh paths (Phase 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panel_index import AgentPanelIndex
from sase.ace.tui.models.agent_panels import AgentPanelGroup


def _agent(
    *,
    suffix: str,
    tribe: str | None = None,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    agent_family_parallel: bool = False,
    agent_family: str | None = None,
    agent_family_role: str | None = None,
    plan_chain_root: bool = False,
    clan: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name="alpha",
        tribe=tribe,
        raw_suffix=suffix,
        parent_timestamp=parent_timestamp,
        agent_family_parallel=agent_family_parallel,
        agent_family=agent_family,
        agent_family_role=agent_family_role,
        plan_chain_root=plan_chain_root,
        agent_clan=clan,
        agent_clan_generation="gen-1" if clan else None,
    )


def _parallel_family(
    *,
    suffix: str,
    root_status: str,
    member_statuses: tuple[str, ...],
) -> tuple[Agent, list[Agent]]:
    root = _agent(
        suffix=suffix,
        status=root_status,
        agent_family_parallel=True,
    )
    members = [
        _agent(
            suffix=f"{suffix}-member-{index}",
            status=status,
            parent_timestamp=suffix,
            agent_family_parallel=True,
        )
        for index, status in enumerate(member_statuses)
    ]
    root.runtime_children.extend(members)
    return root, members


def _sequential_family(*, suffix: str, clan: str | None = None) -> tuple[Agent, Agent]:
    root = _agent(
        suffix=suffix,
        status="PLAN APPROVED",
        agent_family=suffix,
        agent_family_role="root",
        plan_chain_root=True,
        clan=clan,
    )
    member = _agent(
        suffix=f"{suffix}-code",
        parent_timestamp=suffix,
        agent_family=suffix,
        agent_family_role="code",
        clan=clan,
    )
    root.followup_agents.append(member)
    root.runtime_children.append(member)
    return root, member


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
        self._agent_search_query = ""
        self._unread_completed_agent_ids = set()
        self._countdown_remaining = 0
        self.refresh_interval = 0

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None


def test_panel_index_is_cached_per_agents_ref() -> None:
    agents = [_agent(suffix="a"), _agent(suffix="b", tribe="x")]
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
        _agent(suffix="b", tribe="alpha"),
        _agent(suffix="c", tribe="alpha", status="FAILED"),
    ]
    bare = _Bare(agents)
    index = bare._agent_panel_index()
    assert isinstance(index, AgentPanelIndex)
    assert index.keys_per_agent == [None, "alpha", "alpha"]
    no_tribe = index.slice_for(None)
    assert no_tribe.global_indices == [0]
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
            project_file="/r/p/p.sase",
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


def test_sync_panel_group_snaps_selection_off_hidden_starting_row() -> None:
    agents = [
        _agent(suffix="starting", status="STARTING"),
        _agent(suffix="running", status="RUNNING"),
    ]
    bare = _Bare(agents)
    bare.current_idx = 0

    bare._sync_panel_group()

    assert bare.current_idx == 1
    assert bare._panel_group.panel_keys == [None]


class _RecordingInfoPanel:
    """Info-panel stub that records the legacy position + count-strip calls."""

    counts: tuple[int, int, int, int, int, int, int, int] | None = None
    position: tuple[int, int] | None = None
    panel_mode_label = ""

    def update_position(self, position: int, total: int) -> None:
        self.position = (position, total)

    def update_agent_counts(
        self,
        unread: int,
        asking: int,
        running: int,
        waiting: int,
        failed: int,
        read: int,
        total: int,
        *,
        starting: int = 0,
    ) -> None:
        self.counts = (
            unread,
            asking,
            starting,
            running,
            waiting,
            failed,
            read,
            total,
        )

    def update_countdown(self, _countdown: int, _interval: int) -> None:
        return

    def update_search_query(self, _query: str) -> None:
        return

    def update_grouping_mode(self, _label: str) -> None:
        return

    def update_view_mode(self, _mode: str) -> None:
        return


def _run_info_panel(bare: _Bare) -> _RecordingInfoPanel:
    """Drive ``_update_agents_info_panel`` against a recording info-panel stub."""
    info_panel = _RecordingInfoPanel()
    bare.query_one = lambda _selector, _type=None: info_panel  # type: ignore[attr-defined]
    bare._update_agents_info_panel()
    return info_panel


def test_info_panel_agent_counts_use_visible_top_level_agents() -> None:
    visible_unread = _agent(suffix="done-unread", status="DONE")
    visible_asking = _agent(suffix="asking", status="PLAN")
    visible_starting = _agent(suffix="starting", status="STARTING")
    visible_running = _agent(suffix="running", status="RUNNING")
    visible_waiting = _agent(suffix="waiting", status="WAITING")
    visible_failed = _agent(suffix="failed", status="FAILED")
    visible_retried_failed = _agent(suffix="retried-failed", status="FAILED (RETRIED)")
    child_unread = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name="child",
        raw_suffix="child",
        parent_timestamp="parent",
    )
    child_asking = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status="QUESTION",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name="child-asking",
        raw_suffix="child-asking",
        parent_timestamp="parent",
    )
    bare = _Bare(
        [
            visible_unread,
            visible_asking,
            visible_starting,
            visible_running,
            visible_waiting,
            visible_failed,
            visible_retried_failed,
            child_unread,
            child_asking,
        ]
    )
    bare.current_idx = -1
    bare._unread_completed_agent_ids = {
        visible_unread.identity,
        child_unread.identity,
    }

    info_panel = _run_info_panel(bare)

    # Position uses the selectable (rendered) top-level total, which excludes
    # the hidden STARTING row.
    assert info_panel.position == (0, 6)
    # The hole headline includes six rendered standalone holes plus the one
    # hidden top-level STARTING hole (still one in the ``starting`` bucket).
    assert info_panel.counts == (1, 1, 1, 1, 1, 2, 0, 7)


def test_info_panel_mixed_family_and_clan_uses_hole_headline() -> None:
    standalone = _agent(suffix="standalone", status="DONE")
    family_root, family_member = _sequential_family(suffix="family")
    clan_family_root, clan_family_member = _sequential_family(
        suffix="clan-family",
        clan="research",
    )
    clan_standalone = _agent(
        suffix="clan-standalone",
        status="WAITING",
        clan="research",
    )
    rows = project_clan_tree(
        [
            standalone,
            family_root,
            family_member,
            clan_family_root,
            clan_family_member,
            clan_standalone,
        ]
    )
    bare = _Bare(rows)

    info_panel = _run_info_panel(bare)

    assert info_panel.position == (1, 3)
    # Four holes: standalone, family, and two direct clan members. The status
    # buckets classify those same four owners.
    assert info_panel.counts == (0, 0, 0, 2, 1, 0, 1, 4)


def test_info_panel_hole_headline_ignores_grouping_and_fold_presentation() -> None:
    family_root, family_member = _sequential_family(suffix="family")
    bare = _Bare([family_root, family_member])

    initial = _run_info_panel(bare)
    bare._grouping_mode = GroupingMode.BY_STATUS
    bare._group_fold_registry.collapse(("Running",))
    grouped_and_folded = _run_info_panel(bare)

    assert initial.counts is not None
    assert grouped_and_folded.counts is not None
    assert initial.counts[-1] == grouped_and_folded.counts[-1] == 1


def test_info_panel_total_counts_lone_hidden_starting_agent() -> None:
    """Regression: one top-level STARTING agent with no rendered rows.

    The user-visible symptom was an impossible ``0 [1 starting]`` headline.
    The displayed total must include the hidden STARTING row (``1``) while the
    selectable position total stays ``0``.
    """
    bare = _Bare([_agent(suffix="starting", status="STARTING")])
    bare.current_idx = -1

    info_panel = _run_info_panel(bare)

    assert info_panel.position == (0, 0)
    # (unread, asking, starting, running, waiting, failed, read, total)
    assert info_panel.counts == (0, 0, 1, 0, 0, 0, 0, 1)


def test_info_panel_projects_parallel_family_member_statuses() -> None:
    family_one_root, family_one_members = _parallel_family(
        suffix="family-one",
        root_status="WAITING",
        member_statuses=(
            "RUNNING",
            "RUNNING",
            "STARTING",
            "WAITING",
            "DONE",
            "DONE",
        ),
    )
    family_two_root, family_two_members = _parallel_family(
        suffix="family-two",
        root_status="DONE",
        member_statuses=(
            "RUNNING",
            "RUNNING",
            "WAITING",
            "WAITING",
            "WAITING",
            "WAITING",
            "WAITING",
        ),
    )
    serial_child = _agent(
        suffix="serial-child",
        status="FAILED",
        parent_timestamp=family_one_root.raw_suffix,
    )
    family_one_root.runtime_children.append(serial_child)
    ordinary_agents = [
        _agent(suffix="ordinary-running-one"),
        _agent(suffix="ordinary-running-two"),
        _agent(suffix="ordinary-waiting", status="WAITING"),
    ]
    bare = _Bare(
        [
            family_one_root,
            *family_one_members,
            serial_child,
            family_two_root,
            *family_two_members,
            *ordinary_agents,
        ]
    )
    bare._unread_completed_agent_ids = {
        family_one_members[4].identity,
        serial_child.identity,
    }

    info_panel = _run_info_panel(bare)

    assert info_panel.position == (1, 5)
    # Family STARTING contributes to running, terminal members split by their
    # own unread identities, and each family's members replace its root in the
    # headline hole total. The serial child is excluded from both projections.
    assert info_panel.counts == (1, 0, 0, 7, 7, 0, 1, 16)


def test_info_panel_parallel_root_without_loaded_members_falls_back_to_root() -> None:
    unloaded_family_root = _agent(
        suffix="unloaded-family",
        status="WAITING",
        agent_family_parallel=True,
    )
    bare = _Bare(
        [
            unloaded_family_root,
            _agent(suffix="ordinary-done", status="DONE"),
            _agent(suffix="ordinary-starting", status="STARTING"),
        ]
    )

    info_panel = _run_info_panel(bare)

    assert info_panel.position == (1, 2)
    assert info_panel.counts == (0, 0, 1, 0, 1, 0, 1, 3)
