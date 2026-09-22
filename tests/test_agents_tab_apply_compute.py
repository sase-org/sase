"""Integration tests for the agents-tab apply compute/projection boundary."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase import project_display_names as pdn
from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    compute_apply_loaded_agents,
    prepare_loaded_agents_apply_boundary,
)
from sase.ace.tui.models.agent import AgentType
from sase.feature_flags import override_flags

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


@pytest.fixture(autouse=True)
def _pin_legacy_agent_query_dialect() -> Iterator[None]:
    """sase-zf.2: these tests exercise the legacy agent_query dialect explicitly."""
    with override_flags(agents_unified_query=False):
        yield


def test_compute_apply_attaches_project_display_names_to_dismissed_loader_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismissed = _make_agent(
        cl_name="gh_acme__widgets",
        project_file="/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase",
        raw_suffix="20260706120000",
        status="DONE",
    )
    monkeypatch.setattr(
        pdn,
        "_project_display_name_map_cached",
        lambda *_args, **_kwargs: {"gh_acme__widgets": "widgets"},
    )

    prep = compute_apply_loaded_agents(
        all_agents=[],
        dismissed_from_loader=[dismissed],
        dismissed_snapshot={dismissed.identity},
        hide_non_run_agents=False,
    )

    assert prep.dismissed_agent_objects == [dismissed]
    assert dismissed.project_display_name == "widgets"
    assert dismissed.display_name == "widgets"


def test_compute_apply_keeps_verified_live_retry_over_stale_dismissal() -> None:
    """A previously dismissed terminal identity cannot hide its live retry."""
    root = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retry-family",
        status="RETRYING",
        raw_suffix="20260706115800",
    )
    root.runner_is_live = True
    root.retry_status = "retrying"

    prep = compute_apply_loaded_agents(
        all_agents=[root],
        dismissed_from_loader=[],
        dismissed_snapshot={root.identity},
        hide_non_run_agents=False,
    )

    assert prep.filtered_agents == [root]
    assert prep.dismissed_agent_objects == []


def test_prepared_apply_boundary_matches_apply_projection_for_folded_data() -> None:
    """The apply path should install the prepared unfiltered/folded payload."""
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent",
        status="RUNNING",
        raw_suffix="ts1",
    )
    child = _make_agent(
        cl_name="child",
        status="DONE",
        parent_workflow="workflow",
        parent_timestamp="ts1",
        raw_suffix="ts1",
    )
    hidden_child = _make_agent(
        cl_name="hidden_child",
        status="DONE",
        parent_workflow="workflow",
        parent_timestamp="ts1",
        raw_suffix="ts1",
        is_hidden_step=True,
    )
    agents = [parent, child, hidden_child]

    app = FakeAgentApp()
    app._fold_manager.expand("ts1")
    prep = PreparedApplyData(
        filtered_agents=list(agents),
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        app._make_prepared_apply_snapshot(
            on_agents_tab=False,
            selected_identity=None,
            load_state=None,
        ),
    )

    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=list(agents),
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
        persist_dismissed_changes=False,
    )

    assert app._agents_with_children == boundary.fold.unfiltered_agents
    assert app._agents == boundary.fold.visible_agents
    assert app._fold_counts == boundary.fold.fold_counts
