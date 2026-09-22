from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.models.agent_live_query_engine import agents_history_query_key
from sase.ace.tui.models.agent_loader import AgentLoadState, load_tiered_agents
from sase.feature_flags import override_flags
from tests._agents_tab_query_helpers import _make_agent


def test_load_tiered_agents_uses_bounded_safe_query_pushdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sase-zf.2: the legacy pushdown compiler stays exercised with the flag off."""
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

    with override_flags(agents_unified_query=False):
        agents, state = load_tiered_agents(search_query="cl:target", requested_limit=1)

    assert agents == [target]
    assert state.history_query_key == agents_history_query_key(
        "cl:target",
        use_unified_query=False,
    )
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


def test_load_tiered_agents_unified_query_uses_bounded_pushdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sase-zf.3: with the flag on, safe live-profile queries push down."""
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

    with override_flags(agents_unified_query=True):
        agents, state = load_tiered_agents(search_query="cl:target", requested_limit=1)

    assert agents == [target]
    assert state.history_query_key == agents_history_query_key(
        "cl:target",
        use_unified_query=True,
    )
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


def test_load_tiered_machine_filter_stays_on_bounded_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = _make_agent(cl_name="local")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[local],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=25,
                returned_count=1,
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

    with override_flags(agents_unified_query=True):
        _agents, state = load_tiered_agents(
            search_query="not machine:apollo",
            requested_limit=25,
        )

    assert state.query_incomplete is not True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 25,
            "candidate_filter": {
                "kind": "not",
                "filter": {
                    "kind": "equals",
                    "field": "machine",
                    "value": "apollo",
                },
            },
        }
    ]


def test_load_tiered_agents_unsupported_query_defers_full_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=25,
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

    assert state.query_incomplete is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 25,
            "candidate_filter": None,
        }
    ]


def test_load_tiered_unsupported_unified_query_uses_bounded_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _make_agent(status="FAILED", cl_name="a")
    running = _make_agent(status="RUNNING", cl_name="b")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[failed, running],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=25,
                returned_count=2,
                has_more=True,
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

    with override_flags(agents_unified_query=True):
        agents, state = load_tiered_agents(
            search_query="status:FAILED",
            requested_limit=25,
        )

    assert agents == [failed]
    assert state.query_incomplete is True
    assert state.needs_full_history_reconcile is True
    assert state.returned_count == 1
    assert state.has_more is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 25,
            "candidate_filter": None,
        }
    ]


def test_load_tiered_unsupported_legacy_query_uses_bounded_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _make_agent(status="FAILED", cl_name="a")
    running = _make_agent(status="RUNNING", cl_name="b")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[failed, running],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=25,
                returned_count=2,
                has_more=True,
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

    with override_flags(agents_unified_query=False):
        agents, state = load_tiered_agents(
            search_query="status:failed",
            requested_limit=25,
        )

    assert agents == [failed]
    assert state.query_incomplete is True
    assert state.needs_full_history_reconcile is True
    assert state.returned_count == 1
    assert state.has_more is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 25,
            "candidate_filter": None,
        }
    ]


def test_load_tiered_agents_full_history_preserves_safe_candidate_filter(
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
                artifact_source="artifact_index",
                used_artifact_index=True,
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

    with override_flags(agents_unified_query=True):
        _agents, state = load_tiered_agents(
            full_history=True,
            search_query="cl:target",
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
            "candidate_filter": {
                "kind": "contains",
                "field": "cl",
                "value": "target",
            },
        }
    ]
