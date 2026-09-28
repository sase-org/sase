"""Active-tab scope stage tests (phase sase-1bc.6.1.2, scope-stage).

Covers the tab-independent query-result cache, the scope applied in the
worker finalize path, the stale-token invalidation on tab switch, per-tab
fold survival across re-scopes, dismiss-then-rescope resurrection, fold
persistence v4 migration, and the tab-keyed panel-index memo — in both flag
states.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents import _loading_finalize as loading_finalize
from sase.ace.tui.actions.agents._loading_compute_finalize import (
    PreparedStatusOverridePlan,
    _compute_finalize_plan,
    make_finalize_stale_token,
)
from sase.ace.tui.actions.agents._loading_compute_types import (
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
)
from sase.ace.tui.actions.agents._tab_scope import (
    current_agent_tab_scope,
    current_agent_tab_scope_token,
    refresh_agent_tab_index,
    remove_agents_from_views,
    _rescope_agents_to_active_tab,
    scoped_selection_get,
    scoped_selection_set,
)
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.models import agent_tab_index as index_mod
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import (
    AgentGroupFoldRegistry,
    AgentPanelFoldScope,
)
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_tab_index import (
    ALL_AGENT_TABS,
    AgentTabScope,
    agent_tab_scope_token,
    build_agent_tab_index,
    _index_cache,
    scope_agents_to_tab,
)
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabKey


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Iterator[None]:
    _index_cache.clear()
    yield
    _index_cache.clear()


def _view(token: Any = ("scope-test",)) -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=False,
        machine_order=(),
        pinned_by_alias={},
        named_order={},
        token=token,
    )


def _row(
    suffix: str,
    *,
    tab: str | None = None,
    status: str = "RUNNING",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/proj/project.yml",
        status=status,
        start_time=None,
        raw_suffix=suffix,
        agent_tab=tab,
    )


def _snapshot(
    *,
    scope_key: AgentTabKey | None = None,
    scope_token: str = "default",
    view: AgentTabsViewConfig | None = None,
) -> PreparedApplySnapshot:
    return PreparedApplySnapshot(
        cached_agents_with_children=[],
        dismissed_agents=set(),
        agents_seen_complete_history=False,
        hide_non_run_agents=False,
        load_state=None,
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=True,
            selected_identity=None,
            prior_visual_row=0,
        ),
        grouping_mode=GroupingMode.STANDARD,
        agent_tab_scope_token=scope_token,
        agent_tab_scope_key=scope_key,
        agent_tabs_view_config=view,
    )


class _StubOwner:
    """Minimal owner driving the scope helpers without the full app."""

    def __init__(self, agents: list[Agent]) -> None:
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._agents_query_result: list[Agent] = []
        self._active_agent_tab: AgentTabScope = DEFAULT_AGENT_TAB_KEY
        self._agent_tab_index = None
        self._agent_search_query = ""
        self._agent_panels_grouped = False
        self._grouping_mode = GroupingMode.STANDARD
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._panel_selection_memory: dict[Any, Any] = {}
        self._session_mounted_panel_identities: dict[Any, set[Any]] = {}
        self._session_sticky_query = ""
        self._agent_panel_index_cache = None
        self._panel_keys_cache = None
        self.current_tab = "agents"
        self.current_idx = 0
        self.synced = 0
        self.refreshed = 0

    def _invalidate_agent_panel_cache(self) -> None:
        self._agent_panel_index_cache = None

    def _sync_panel_group(self) -> set[Any]:
        self.synced += 1
        return set()

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        self.refreshed += 1


def test_two_tabs_scope_filters() -> None:
    rows = [_row("a"), _row("b", tab="sase"), _row("c", tab="sase")]
    index = build_agent_tab_index(rows, _view())
    main = scope_agents_to_tab(rows, index, DEFAULT_AGENT_TAB_KEY)
    assert [r.raw_suffix for r in main] == ["a"]
    named = scope_agents_to_tab(rows, index, AgentTabKey.named("sase"))
    assert [r.raw_suffix for r in named] == ["b", "c"]
    assert scope_agents_to_tab(rows, index, ALL_AGENT_TABS) is rows
    assert agent_tab_scope_token(ALL_AGENT_TABS) == "all"
    assert agent_tab_scope_token(DEFAULT_AGENT_TAB_KEY) == "default"
    assert agent_tab_scope_token(AgentTabKey.named("sase")) == "named:sase"


def test_refresh_agent_tab_index_memo_hits_and_tracks_in_place_roster_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.agent_tabs_settings as settings

    rows = [_row("a")]
    owner = _StubOwner(rows)
    monkeypatch.setattr(settings, "agent_tabs_view_config", lambda: _view())
    first = refresh_agent_tab_index(owner)
    assert refresh_agent_tab_index(owner) is first
    owner._agents_with_children.append(_row("b", tab="sase"))
    second = refresh_agent_tab_index(owner)
    assert second is not first
    assert second.root_count(AgentTabKey.named("sase")) == 1


def test_starting_roots_count_toward_catalog() -> None:
    rows = [_row("a", status="STARTING"), _row("b", tab="sase", status="STARTING")]
    index = build_agent_tab_index(rows, _view())
    assert {entry.key: entry.root_count for entry in index.catalog} == {
        DEFAULT_AGENT_TAB_KEY: 1,
        AgentTabKey.named("sase"): 1,
    }


def test_empty_query_leaves_index_catalog_unchanged() -> None:
    rows = [_row("a"), _row("b", tab="sase")]
    index = build_agent_tab_index(rows, _view())
    scoped = scope_agents_to_tab([], index, DEFAULT_AGENT_TAB_KEY)
    assert scoped == []
    assert {entry.key for entry in index.catalog} == {
        DEFAULT_AGENT_TAB_KEY,
        AgentTabKey.named("sase"),
    }


def test_stale_token_rejects_plan_after_scope_change() -> None:
    before = _snapshot(
        scope_key=DEFAULT_AGENT_TAB_KEY,
        scope_token="default",
        view=_view(),
    )
    after = _snapshot(
        scope_key=AgentTabKey.named("sase"),
        scope_token="named:sase",
        view=_view(),
    )
    assert make_finalize_stale_token(before) != make_finalize_stale_token(after)


def test_worker_plan_carries_both_lists_and_index() -> None:
    rows = [_row("a"), _row("b", tab="sase")]
    snapshot = _snapshot(
        scope_key=DEFAULT_AGENT_TAB_KEY,
        scope_token="default",
        view=_view(),
    )
    plan = _compute_finalize_plan(list(rows), snapshot, unfiltered_agents=list(rows))
    assert [r.raw_suffix for r in plan.agents_query_result] == ["a", "b"]
    assert [r.raw_suffix for r in plan.scoped_agents] == ["a"]
    assert plan.tab_index is not None
    assert {entry.key for entry in plan.tab_index.catalog} == {
        DEFAULT_AGENT_TAB_KEY,
        AgentTabKey.named("sase"),
    }
    assert plan.tab_scope_token == "default"
    assert all(scope.tab_scope == "default" for scope in plan.panel_group_keys)
    # Selection math runs over the scoped roster.
    assert plan.selection.restored_idx == 0


def test_worker_plan_without_view_config_skips_scope() -> None:
    rows = [_row("a"), _row("b", tab="sase")]
    plan = _compute_finalize_plan(list(rows), _snapshot())
    assert [r.raw_suffix for r in plan.scoped_agents] == ["a", "b"]
    assert plan.tab_index is None
    assert [r.raw_suffix for r in plan.agents_query_result] == ["a", "b"]


def test_worker_apply_keeps_off_tab_status_overrides_and_cache_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_row("a"), _row("b", tab="sase")]
    snapshot = _snapshot(
        scope_key=AgentTabKey.named("sase"),
        scope_token="named:sase",
        view=_view(),
    )
    plan = _compute_finalize_plan(rows, snapshot, unfiltered_agents=rows)
    plan = replace(
        plan,
        overrides=PreparedStatusOverridePlan(
            overrides_to_apply=[(rows[0].identity, "FAILED")],
            cleared_identities=[],
        ),
    )

    class _ContentCache:
        def __init__(self) -> None:
            self.pruned: list[Agent] | None = None

        def prune(self, agents: list[Agent]) -> None:
            self.pruned = list(agents)

    cache = _ContentCache()
    app = SimpleNamespace(
        _agents_query_result=[],
        _agent_tab_index=None,
        _active_agent_tab=AgentTabKey.named("sase"),
        _agent_status_overrides={rows[0].identity: "FAILED"},
        _agent_content_search_cache=cache,
    )
    monkeypatch.setattr(
        loading_finalize, "_sync_unread_completed_agents", lambda *_args: None
    )
    monkeypatch.setattr(
        loading_finalize, "reconcile_panel_fold_registries", lambda *_args: None
    )

    loading_finalize._apply_finalize_plan(
        app,
        on_agents_tab=False,
        selected_identity=None,
        plan=plan,
        prior_pos=None,
        previous_agents=None,
        refresh_display=False,
    )

    assert [row.raw_suffix for row in app._agents] == ["b"]
    assert app._agents_query_result[0].status == "FAILED"
    assert cache.pruned == rows
    active_a = scope_agents_to_tab(
        app._agents_query_result,
        app._agent_tab_index,
        DEFAULT_AGENT_TAB_KEY,
    )
    assert [(row.raw_suffix, row.status) for row in active_a] == [("a", "FAILED")]


def test_folds_survive_rescope_to_other_tab_and_back() -> None:
    registry = AgentGroupFoldRegistry()
    scope_a = AgentPanelFoldScope(None, merged=False, tab_scope="default")
    scope_b = AgentPanelFoldScope(None, merged=False, tab_scope="named:sase")
    registry.for_panel(None, tab_scope="default").collapse(("sase",))
    registry.for_panel(None, tab_scope="named:sase").collapse(("other",))
    # Pruning tab A's layout must not touch tab B's folds.
    assert ("sase",) in registry.for_panel(None, tab_scope="default").collapsed
    changed = registry.reconcile_layout(
        {scope_a: []}, merged=False, tab_scope="default"
    )
    assert ("other",) in registry.for_panel(None, tab_scope="named:sase").collapsed
    assert ("sase",) not in registry.for_panel(None, tab_scope="default").collapsed
    assert changed
    # Unknown scopes for the other tab are left entirely alone.
    assert scope_b in registry._registries


def test_dismiss_then_rescope_does_not_resurrect() -> None:
    rows = [_row("a"), _row("b", tab="sase")]
    owner = _StubOwner(rows)
    refresh_agent_tab_index(owner)
    owner._agents_query_result = list(rows)
    owner._agents = [rows[0]]
    remove_agents_from_views(owner, {rows[1].identity})
    assert owner._agents_query_result == [rows[0]]
    assert owner._agents == [rows[0]]
    # A later tab switch re-scopes the pruned cache: no resurrection.
    owner._active_agent_tab = AgentTabKey.named("sase")
    _rescope_agents_to_active_tab(owner)
    assert owner._agents == []
    assert owner._agents_query_result == [rows[0]]
    assert owner.synced == 1
    assert owner.refreshed == 1


def test_selection_memory_is_per_scope() -> None:
    owner = _StubOwner([])
    scoped_selection_set(owner, None, ("agent", 0))
    assert scoped_selection_get(owner, None) == ("agent", 0)
    owner._active_agent_tab = AgentTabKey.named("sase")
    assert scoped_selection_get(owner, None) is None
    scoped_selection_set(owner, None, ("agent", 2))
    owner._active_agent_tab = DEFAULT_AGENT_TAB_KEY
    assert scoped_selection_get(owner, None) == ("agent", 0)


def test_panel_index_memo_is_keyed_by_scope() -> None:
    rows = [_row("a"), _row("b", tab="sase")]
    owner = _StubOwner(rows)
    first = AgentDisplayMixin._agent_panel_index(owner)  # type: ignore[arg-type]
    again = AgentDisplayMixin._agent_panel_index(owner)  # type: ignore[arg-type]
    assert again is first
    owner._active_agent_tab = AgentTabKey.named("sase")
    switched = AgentDisplayMixin._agent_panel_index(owner)  # type: ignore[arg-type]
    assert switched is not first


def test_fold_persistence_v3_decodes_with_default_tab(tmp_path: Path) -> None:
    from sase.ace.tui.models.agent_fold_persistence import load_agents_fold_state

    path = tmp_path / "folds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "group_folds": [
                    {
                        "mode": "standard",
                        "scopes": [
                            {
                                "panel": {"kind": "no_tribe"},
                                "merged": False,
                                "collapsed": [["sase"]],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_fold_state(path)
    (group_snapshot,) = loaded.group_folds
    (scope_snapshot,) = group_snapshot.scopes
    assert scope_snapshot.scope.tab_scope == "default"


def test_fold_persistence_v4_round_trip_per_tab(tmp_path: Path) -> None:
    from sase.ace.tui.models.agent_fold_persistence import (
        AgentGroupingFoldSnapshot,
        AgentsFoldStateSnapshot,
        load_agents_fold_state,
        save_agents_fold_state,
    )
    from sase.ace.tui.models.agent_group_fold import AgentPanelFoldSnapshot

    snapshot = AgentsFoldStateSnapshot(
        group_folds=(
            AgentGroupingFoldSnapshot(
                GroupingMode.STANDARD,
                (
                    AgentPanelFoldSnapshot(
                        AgentPanelFoldScope(None, tab_scope="default"),
                        frozenset({("sase",)}),
                    ),
                    AgentPanelFoldSnapshot(
                        AgentPanelFoldScope(None, tab_scope="named:sase"),
                        frozenset({("other",)}),
                    ),
                ),
            ),
        ),
    )
    path = tmp_path / "folds.json"
    save_agents_fold_state(snapshot, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 4
    tabs = {scope["tab"] for mode in payload["group_folds"] for scope in mode["scopes"]}
    assert tabs == {"default", "named:sase"}
    assert load_agents_fold_state(path) == snapshot


def test_fold_persistence_v4_skips_unresolved_machine_scopes(tmp_path: Path) -> None:
    from sase.ace.tui.models.agent_fold_persistence import (
        AgentGroupingFoldSnapshot,
        AgentsFoldStateSnapshot,
        load_agents_fold_state,
        save_agents_fold_state,
    )
    from sase.ace.tui.models.agent_group_fold import AgentPanelFoldSnapshot

    snapshot = AgentsFoldStateSnapshot(
        group_folds=(
            AgentGroupingFoldSnapshot(
                GroupingMode.STANDARD,
                (
                    AgentPanelFoldSnapshot(
                        AgentPanelFoldScope(None, tab_scope="unresolved:apollo"),
                        frozenset({("sase",)}),
                    ),
                ),
            ),
        ),
    )
    path = tmp_path / "folds.json"
    save_agents_fold_state(snapshot, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "group_folds" not in payload
    assert load_agents_fold_state(path) == AgentsFoldStateSnapshot()


@pytest.mark.parametrize("schema_version", [1, 2])
def test_fold_persistence_v1_v2_decode_with_default_tab(
    tmp_path: Path, schema_version: int
) -> None:
    from sase.ace.tui.models.agent_fold_persistence import load_agents_fold_state

    panel_key = {"kind": "untagged"} if schema_version == 1 else {"kind": "no_tribe"}
    path = tmp_path / "folds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "group_folds": [
                    {
                        "mode": "standard",
                        "scopes": [
                            {
                                "panel": panel_key,
                                "merged": False,
                                "collapsed": [["Done"]],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_fold_state(path)
    assert loaded.group_folds[0].scopes[0].scope.tab_scope == "default"


def test_index_module_exports_scope_helpers() -> None:
    assert set(index_mod.__all__) >= {
        "ALL_AGENT_TABS",
        "AgentTabScope",
        "agent_tab_scope_token",
        "scope_agents_to_tab",
    }
