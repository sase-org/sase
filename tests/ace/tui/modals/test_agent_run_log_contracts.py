"""Run-log loading contracts for agent artifact startup work."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.modals.agent_run_log_modal import _load_agents_for_cl
from sase.ace.tui.models.agent import AgentType
from tests.ace.agent_artifact_startup_fixtures import make_agent


def test_run_log_loads_active_dismissed_and_meta_created_agents() -> None:
    target = "target_cl"
    active_direct = make_agent(cl_name=target, raw_suffix="20250101120000")
    active_meta_cl = make_agent(
        cl_name="source_cl",
        raw_suffix="20250101121000",
        step_output={"meta_new_cl": f"{target} (http://cl/123)"},
    )
    active_meta_pr = make_agent(
        cl_name="source_pr",
        raw_suffix="20250101122000",
        step_output={"meta_changespec": target, "meta_new_pr": "http://pr/1"},
    )
    dismissed_direct = make_agent(cl_name=target, raw_suffix="20250101123000")
    dismissed_meta_cl = make_agent(
        cl_name="old_source",
        raw_suffix="20250101124000",
        step_output={"meta_new_cl": target},
    )
    dismissed_child = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=target,
        raw_suffix="20250101125000",
        parent_workflow="wf",
        parent_timestamp="20250101123000",
    )
    dismissed_unrelated = make_agent(cl_name="other", raw_suffix="20250101130000")

    dismissed_ids = {
        dismissed_direct.identity,
        dismissed_meta_cl.identity,
        dismissed_child.identity,
        dismissed_unrelated.identity,
    }

    with (
        patch(
            "sase.ace.tui.modals.agent_run_log_modal.load_all_agents",
            return_value=[active_direct, active_meta_cl, active_meta_pr],
        ),
        patch(
            "sase.ace.tui.modals.agent_run_log_modal.load_dismissed_agents",
            return_value=dismissed_ids,
        ),
        patch(
            "sase.ace.tui.modals.agent_run_log_modal.load_dismissed_bundles",
            return_value=[
                dismissed_direct,
                dismissed_child,
            ],
        ) as mock_load_dismissed_bundles,
    ):
        agents, loaded_dismissed_ids = _load_agents_for_cl(target)

    assert loaded_dismissed_ids == dismissed_ids
    assert agents == [
        active_direct,
        active_meta_cl,
        active_meta_pr,
        dismissed_direct,
    ]
    mock_load_dismissed_bundles.assert_called_once_with(
        suffixes={dismissed_direct.raw_suffix, dismissed_child.raw_suffix}
    )
