"""Tests for incomplete agent-loader history preservation."""

from __future__ import annotations

import pytest

from tests._agent_loader_self_heal_helpers import (
    INCOMPLETE_INDEX_STATE,
    INCOMPLETE_SOURCE_SCAN_STATE,
    SOURCE_SCAN_STATE,
    FakeLoadingApp,
    clear_cleaned_artifact_cache,
    make_agent,
)


@pytest.fixture(autouse=True)
def _clear_cleaned_artifact_cache() -> None:
    clear_cleaned_artifact_cache()


def test_incomplete_load_preserves_visible_revived_agent() -> None:
    """Tier 1 source scans should not drop same-session revived history."""
    app = FakeLoadingApp()
    revived = make_agent(cl_name="old", raw_suffix="20240102120000")
    current = make_agent(cl_name="new", raw_suffix="20260202120000")
    app._agents_with_children = [revived]
    app._agents = [revived]
    app._revived_agent_raw_suffixes = {"20240102120000"}

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_SOURCE_SCAN_STATE,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260202120000",
        "20240102120000",
    ]
    assert app._revived_agent_raw_suffixes == {"20240102120000"}


def test_incomplete_load_preserves_revived_agent_from_dismissed_objects() -> None:
    """Surface revived agents from dismissed-bundle cache on first paint."""
    app = FakeLoadingApp()
    revived = make_agent(cl_name="old", raw_suffix="20240102120000")
    current = make_agent(cl_name="new", raw_suffix="20260202120000")
    # _agents_with_children is empty because the revived agent was
    # long-dismissed and never appeared in a prior in-memory snapshot.
    app._agents_with_children = []
    app._agents = []
    app._dismissed_agent_objects = [revived]
    app._revived_agent_raw_suffixes = {"20240102120000"}

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260202120000",
        "20240102120000",
    ]
    assert app._revived_agent_raw_suffixes == {"20240102120000"}


def test_complete_load_clears_revived_agent_preservation() -> None:
    """Once Tier 2 sees the revived row, future loads no longer pin it."""
    app = FakeLoadingApp()
    revived = make_agent(cl_name="old", raw_suffix="20240102120000")
    app._agents_with_children = [revived]
    app._agents = [revived]
    app._revived_agent_raw_suffixes = {"20240102120000"}

    app._apply_loaded_agents(
        [revived],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=SOURCE_SCAN_STATE,
    )

    assert app._agents == [revived]
    assert app._revived_agent_raw_suffixes == set()


def test_incomplete_load_after_complete_history_patches_cached_rows() -> None:
    """Tier 1 refreshes after Tier 2 should not shrink the row universe."""
    app = FakeLoadingApp()
    active_cached = make_agent(
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120000",
    )
    active_updated = make_agent(
        cl_name="active",
        status="DONE",
        raw_suffix="20260202120000",
    )
    historical = make_agent(cl_name="historical", raw_suffix="20240102120000")
    dismissed = make_agent(cl_name="dismissed", raw_suffix="20240103120000")
    new_agent = make_agent(cl_name="new", raw_suffix="20260303120000")

    app._agent_load_state = SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [active_cached, historical, dismissed]
    app._agents = list(app._agents_with_children)
    app._dismissed_agents = {dismissed.identity}

    app._apply_loaded_agents(
        [new_agent, active_updated],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260303120000",
        "20260202120000",
        "20240102120000",
    ]
    assert app._agents[1] is active_updated


def test_repeated_incomplete_load_after_complete_history_keeps_cached_rows() -> None:
    """The complete-history watermark survives multiple Tier 1 patches."""
    app = FakeLoadingApp()
    active_cached = make_agent(
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120000",
    )
    historical = make_agent(cl_name="historical", raw_suffix="20240102120000")
    launched = make_agent(
        cl_name="launched",
        status="RUNNING",
        raw_suffix="20260303120000",
    )
    launched_updated = make_agent(
        cl_name="launched",
        status="DONE",
        raw_suffix="20260303120000",
    )

    app._apply_loaded_agents(
        [active_cached, historical],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=SOURCE_SCAN_STATE,
    )
    assert app._agents_seen_complete_history is True

    app._apply_loaded_agents(
        [launched],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    app._apply_loaded_agents(
        [launched_updated],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260303120000",
        "20260202120000",
        "20240102120000",
    ]
    assert app._agents[0] is launched_updated


def test_incomplete_load_before_complete_history_still_replaces_list() -> None:
    """First-paint Tier 1 behavior stays capped until Tier 2 reconciles."""
    app = FakeLoadingApp()
    historical = make_agent(cl_name="historical", raw_suffix="20240102120000")
    current = make_agent(cl_name="current", raw_suffix="20260303120000")
    app._agents_with_children = [historical]
    app._agents = [historical]

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [current]
