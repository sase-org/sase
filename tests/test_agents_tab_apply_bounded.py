"""Integration tests for the agents-tab bounded-prefix/history apply boundary."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.ace.tui.actions.agents._loading_compute import PreparedApplyData
from sase.ace.tui.models.agent_live_query_engine import agents_history_query_key
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.models.agent_panels import panel_keys_for
from sase.feature_flags import override_flags

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


@pytest.fixture(autouse=True)
def _pin_legacy_agent_query_dialect() -> Iterator[None]:
    """sase-zf.2: these tests exercise the legacy agent_query dialect explicitly."""
    with override_flags(agents_unified_query=False):
        yield


def test_bounded_prefix_apply_patches_over_cached_history() -> None:
    """A ``has_more`` viewport prefix must never shrink the visible universe."""
    cached_old = _make_agent(
        cl_name="cached-old",
        status="DONE",
        raw_suffix="old",
    )
    fresh = _make_agent(
        cl_name="fresh",
        status="RUNNING",
        raw_suffix="fresh",
    )
    app = FakeAgentApp()
    app._agents_seen_complete_history = True
    app._agents_with_children = [cached_old]
    prep = PreparedApplyData(
        filtered_agents=[fresh],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )

    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=True,
            requested_limit=1,
            returned_count=1,
            has_more=True,
        ),
        persist_dismissed_changes=False,
    )

    assert app._agents_with_children == [fresh, cached_old]
    assert app._agents == [fresh, cached_old]


def test_same_query_bounded_prefix_preserves_visible_roster_and_panels() -> None:
    """After Tier 2, a same-query bounded prefix patches without rearming."""
    query = "cl:focus"
    query_key = agents_history_query_key(query, use_unified_query=False)
    broad = [
        _make_agent(
            cl_name="focus-chop",
            status="RUNNING",
            raw_suffix="20260917090100",
            tribe="chop",
        ),
        _make_agent(
            cl_name="focus-epic",
            status="RUNNING",
            raw_suffix="20260917090200",
            tribe="epic",
        ),
        _make_agent(
            cl_name="focus-tale",
            status="RUNNING",
            raw_suffix="20260917090300",
            tribe="tale",
        ),
    ]
    refreshed_epic = _make_agent(
        cl_name="focus-epic",
        status="RUNNING",
        raw_suffix="20260917090200",
        tribe="epic",
    )
    app = FakeAgentApp(query=query)

    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=list(broad),
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier2",
            complete_history=True,
            artifact_source="artifact_index",
            used_artifact_index=True,
            history_query_key=query_key,
        ),
        persist_dismissed_changes=False,
    )

    expected_identities = [agent.identity for agent in app._agents]
    expected_panel_keys = panel_keys_for(app._agents)
    assert expected_panel_keys == ["chop", "epic", "tale"]

    app._agents_history_reconcile_pending = False
    app._agents_history_reconcile_armed_mono = 0.0
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[refreshed_epic],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=True,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=True,
            requested_limit=1,
            returned_count=1,
            has_more=True,
            query_incomplete=True,
            history_query_key=query_key,
        ),
        persist_dismissed_changes=False,
    )

    assert [agent.identity for agent in app._agents] == expected_identities
    assert panel_keys_for(app._agents) == expected_panel_keys
    assert app._agents_complete_history_query_key == query_key
    assert app._agents_seen_complete_history is True
    assert app._agents_history_reconcile_pending is False
    assert app._agents_history_reconcile_armed_mono == 0.0


def _apply_bounded_prefix_over_cache(
    *,
    seen_complete_history: bool,
    has_more: bool,
) -> FakeAgentApp:
    """Apply a bounded-prefix load holding one fresh row over one cached row."""
    cached_old = _make_agent(
        cl_name="cached-old",
        status="DONE",
        raw_suffix="old",
    )
    fresh = _make_agent(
        cl_name="fresh",
        status="RUNNING",
        raw_suffix="fresh",
    )
    app = FakeAgentApp()
    app._agents_seen_complete_history = seen_complete_history
    app._agents_with_children = [cached_old]
    prep = PreparedApplyData(
        filtered_agents=[fresh],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )

    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=True,
            requested_limit=1,
            returned_count=1,
            has_more=has_more,
        ),
        persist_dismissed_changes=False,
    )
    return app


def test_bounded_prefix_patches_cache_before_any_complete_history() -> None:
    """A viewport prefix is a subset even without a complete-history watermark."""
    app = _apply_bounded_prefix_over_cache(
        seen_complete_history=False,
        has_more=True,
    )

    assert [agent.cl_name for agent in app._agents] == ["fresh", "cached-old"]


def test_bounded_window_without_has_more_still_patches_cache() -> None:
    """``has_more=False`` is a pagination fact, not removal authority."""
    app = _apply_bounded_prefix_over_cache(
        seen_complete_history=False,
        has_more=False,
    )

    assert [agent.cl_name for agent in app._agents] == ["fresh", "cached-old"]


def _bounded_zero_load_state(query_key: tuple[str, str] | None) -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=10,
        returned_count=0,
        has_more=False,
        history_query_key=query_key,
    )


def _apply_empty(app: FakeAgentApp, load_state: AgentLoadState) -> None:
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[],
            has_always_visible=False,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=load_state,
        persist_dismissed_changes=False,
    )


def _seed_two_tribe_complete_history(
    query: str,
) -> tuple[FakeAgentApp, tuple[str, str]]:
    query_key = agents_history_query_key(query, use_unified_query=False)
    app = FakeAgentApp(query=query)
    app._schedule_agents_async_refresh = lambda **kw: None  # type: ignore[attr-defined]
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[
                _make_agent(
                    cl_name="focus-epic",
                    status="RUNNING",
                    raw_suffix="20260917090200",
                    tribe="epic",
                ),
                _make_agent(
                    cl_name="focus-tale",
                    status="RUNNING",
                    raw_suffix="20260917090300",
                    tribe="tale",
                ),
            ],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier2",
            complete_history=True,
            artifact_source="artifact_index",
            used_artifact_index=True,
            history_query_key=query_key,
        ),
        persist_dismissed_changes=False,
    )
    return app, query_key


def test_same_query_bounded_zero_keeps_cache_and_latch() -> None:
    app, query_key = _seed_two_tribe_complete_history("cl:focus")
    identities = [agent.identity for agent in app._agents]
    assert panel_keys_for(app._agents) == ["epic", "tale"]

    _apply_empty(app, _bounded_zero_load_state(query_key))

    assert [agent.identity for agent in app._agents] == identities
    assert panel_keys_for(app._agents) == ["epic", "tale"]
    assert app._agents_seen_complete_history is True
    assert app._agents_complete_history_query_key == query_key


def test_bounded_zero_without_latch_keeps_cache_and_revalidates_once() -> None:
    app, query_key = _seed_two_tribe_complete_history("cl:focus")
    app._agents_seen_complete_history = False
    app._agents_complete_history_query_key = None
    identities = [agent.identity for agent in app._agents]
    scheduled: list[dict[str, object]] = []
    app._schedule_agents_async_refresh = lambda **kw: scheduled.append(kw)  # type: ignore[attr-defined]

    _apply_empty(app, _bounded_zero_load_state(query_key))
    _apply_empty(app, _bounded_zero_load_state(query_key))

    assert [agent.identity for agent in app._agents] == identities
    assert len(scheduled) == 1
    assert scheduled[0]["revalidate_index"] is True


def test_mismatched_incomplete_key_does_not_reset_latch() -> None:
    app, query_key = _seed_two_tribe_complete_history("cl:focus")
    other_key = agents_history_query_key("cl:other", use_unified_query=False)
    assert other_key != query_key
    app._agent_search_query = "cl:focus"

    _apply_empty(app, _bounded_zero_load_state(None))

    assert app._agents_seen_complete_history is True
    assert app._agents_complete_history_query_key == query_key


def test_changed_query_bounded_zero_may_empty_the_tab() -> None:
    app, _ = _seed_two_tribe_complete_history("cl:focus")
    new_key = agents_history_query_key("cl:nothing", use_unified_query=False)
    app._agent_search_query = "cl:nothing"

    _apply_empty(app, _bounded_zero_load_state(new_key))

    assert app._agents == []
    assert app._agents_seen_complete_history is False
    assert app._agents_complete_history_query_key is None


def test_revalidate_shaped_load_keeps_larger_cache_identity_and_panels() -> None:
    """A small tier1_index_revalidate result cannot shrink a large cache."""
    query_key = agents_history_query_key("", use_unified_query=False)
    app = FakeAgentApp()
    app._schedule_agents_async_refresh = lambda **kw: None  # type: ignore[attr-defined]
    cached = [
        _make_agent(
            cl_name=f"c{i}",
            status="DONE",
            raw_suffix=f"2026091709{i:04d}",
            tribe="epic" if i % 2 else "tale",
        )
        for i in range(60)
    ]
    app._agents_with_children = list(cached)
    app._agents_applied_query_key = query_key
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=list(cached[:5]),
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=True,
            requested_limit=5,
            returned_count=5,
            has_more=False,
            history_query_key=query_key,
        ),
        persist_dismissed_changes=False,
    )

    assert {a.identity for a in app._agents} == {a.identity for a in cached}
    assert panel_keys_for(app._agents) == ["epic", "tale"]
