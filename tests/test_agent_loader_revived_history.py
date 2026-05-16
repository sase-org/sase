"""Tests for preserving revived agent rows across partial loader refreshes."""

from __future__ import annotations

import pytest

from sase.ace.tui.models.agent_loader import AgentLoadState
from tests._agent_loader_self_heal_helpers import (
    SOURCE_SCAN_STATE,
    FakeLoadingApp,
    clear_cleaned_artifact_cache,
    make_agent,
)


pytestmark = pytest.mark.usefixtures(clear_cleaned_artifact_cache.__name__)


def test_incomplete_load_preserves_visible_revived_agent() -> None:
    """Tier 1 source scans should not drop same-session revived history."""
    app = FakeLoadingApp()
    revived = make_agent(cl_name="old", raw_suffix="20240102120000")
    current = make_agent(cl_name="new", raw_suffix="20260202120000")
    app._agents_with_children = [revived]
    app._agents = [revived]
    app._revived_agent_raw_suffixes = {"20240102120000"}
    incomplete_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=incomplete_state,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260202120000",
        "20240102120000",
    ]
    assert app._revived_agent_raw_suffixes == {"20240102120000"}


def test_incomplete_load_preserves_revived_agent_from_dismissed_objects() -> None:
    """First paint falls back to dismissed bundles for revived agents."""
    app = FakeLoadingApp()
    revived = make_agent(cl_name="old", raw_suffix="20240102120000")
    current = make_agent(cl_name="new", raw_suffix="20260202120000")
    # ``_agents_with_children`` is empty because the revived agent was
    # long-dismissed and never appeared in a prior in-memory snapshot.
    app._agents_with_children = []
    app._agents = []
    app._dismissed_agent_objects = [revived]
    app._revived_agent_raw_suffixes = {"20240102120000"}
    incomplete_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=incomplete_state,
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
