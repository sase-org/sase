from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.models.agent_loader import AgentLoadState, load_tiered_agents
from tests._agents_tab_query_helpers import _make_agent


def test_load_tiered_agents_uses_bounded_safe_query_pushdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _make_agent(cl_name="target")
    later_target = _make_agent(cl_name="target-later")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[target, later_target],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=1,
                returned_count=2,
                has_more=False,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    agents, state = load_tiered_agents(search_query="cl:target", requested_limit=1)

    assert agents == [target]
    assert state.returned_count == 1
    assert state.has_more is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 1,
            "candidate_filter": {
                "kind": "contains",
                "field": "cl",
                "value": "target",
            },
        }
    ]


def test_load_tiered_agents_unsupported_query_uses_full_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier2",
                complete_history=True,
                artifact_source="source_scan",
                used_artifact_index=False,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    _agents, state = load_tiered_agents(
        search_query="status:failed",
        requested_limit=25,
    )

    assert state.complete_history is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": True,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": None,
            "candidate_filter": None,
        }
    ]
