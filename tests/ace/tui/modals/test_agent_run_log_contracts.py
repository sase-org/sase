"""Run-log loading contracts for agent artifact startup work."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import sase.ace.tui.modals.agent_run_log_modal as agent_run_log_modal
from sase.ace.tui.modals.agent_run_log_modal import (
    AgentRunLogModal,
    _load_agents_for_cl,
)
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
        step_output={"meta_patch": target, "meta_new_pr": "http://pr/1"},
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
            "sase.ace.tui.modals.agent_run_log_modal.load_dismissed_bundle_summaries",
            return_value=[],
        ) as mock_load_dismissed_bundle_summaries,
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
    mock_load_dismissed_bundle_summaries.assert_called_once_with(
        cl_name=target,
        top_level_only=True,
    )
    mock_load_dismissed_bundles.assert_called_once_with(
        suffixes={dismissed_direct.raw_suffix, dismissed_child.raw_suffix}
    )


def test_run_log_detail_humanizes_xprompt_and_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStatic:
        def __init__(self) -> None:
            self.value: Any = None

        def update(self, value: object) -> None:
            self.value = value

    agent = make_agent(cl_name="target_cl", raw_suffix="20250101120000")
    monkeypatch.setattr(
        agent,
        "get_raw_xprompt_content",
        lambda: "#gh:gh_acme__widgets inspect",
    )
    monkeypatch.setattr(
        agent,
        "get_response_content",
        lambda: "## Prompt\n#gh:gh_acme__widgets fix\n",
    )
    monkeypatch.setattr(
        agent_run_log_modal,
        "humanize_vcs_refs_in_text",
        lambda text: text.replace("gh_acme__widgets", "widgets"),
    )
    detail = FakeStatic()
    modal = object.__new__(AgentRunLogModal)
    modal._dismissed_identities = set()
    modal._dismissed_suffixes = set()
    monkeypatch.setattr(modal, "query_one", lambda *_args: detail)

    modal._update_detail(agent)

    assert detail.value is not None
    plain = detail.value.plain
    assert "#gh:widgets inspect" in plain
    assert "#gh:widgets fix" in plain
    assert "gh_acme__widgets" not in plain
