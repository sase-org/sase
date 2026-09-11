from __future__ import annotations

from sase.ace.agent_query.pushdown import compile_agent_query_pushdown
from sase.ace.tui.models.agent_live_query_pushdown import (
    compile_agents_live_query_pushdown,
)


def test_compile_agent_query_pushdown_builds_exact_scalar_filter(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.agent_query.pushdown.project_display_name_map_signature",
        lambda: (("gh_example__internal_tools", "Internal Tools"),),
    )

    plan = compile_agent_query_pushdown(
        'project:"Internal Tools" AND (model:opus OR provider:anthropic) '
        "AND NOT type:workflow"
    )

    assert plan.window_safe is True
    assert plan.candidate_filter == {
        "kind": "all",
        "filters": [
            {
                "kind": "any",
                "filters": [
                    {
                        "kind": "contains",
                        "field": "project",
                        "value": "Internal Tools",
                    },
                    {
                        "kind": "equals",
                        "field": "project",
                        "value": "gh_example__internal_tools",
                    },
                ],
            },
            {
                "kind": "any",
                "filters": [
                    {"kind": "contains", "field": "model", "value": "opus"},
                    {
                        "kind": "contains",
                        "field": "provider",
                        "value": "anthropic",
                    },
                ],
            },
            {
                "kind": "not",
                "filter": {"kind": "equals", "field": "type", "value": "workflow"},
            },
        ],
    }


def test_compile_agent_query_pushdown_keeps_unsupported_queries_unbounded() -> None:
    plan = compile_agent_query_pushdown("status:failed")

    assert plan.raw_query == "status:failed"
    assert plan.window_safe is False
    assert plan.candidate_filter is None
    assert plan.unsupported_reason == "unsupported_query"


def test_compile_agent_query_pushdown_keeps_machine_queries_unbounded() -> None:
    plan = compile_agent_query_pushdown("machine:apollo")

    assert plan.window_safe is False
    assert plan.candidate_filter is None
    assert plan.unsupported_reason == "unsupported_query"


def test_compile_agent_query_pushdown_maps_run_type_alias() -> None:
    plan = compile_agent_query_pushdown("type:run")

    assert plan.window_safe is True
    assert plan.candidate_filter == {
        "kind": "equals",
        "field": "type",
        "value": "agent",
    }


def test_compile_agents_live_query_pushdown_builds_exact_profile_filter(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_live_query_pushdown."
        "project_display_name_map_signature",
        lambda: (("gh_example__internal_tools", "Internal Tools"),),
    )

    plan = compile_agents_live_query_pushdown(
        'project:"Internal Tools" AND (model:opus OR provider:codex) '
        "AND NOT kind:workflow"
    )

    assert plan.window_safe is True
    assert plan.candidate_filter == {
        "kind": "all",
        "filters": [
            {
                "kind": "any",
                "filters": [
                    {
                        "kind": "equals",
                        "field": "project",
                        "value": "Internal Tools",
                    },
                    {
                        "kind": "equals",
                        "field": "project",
                        "value": "gh_example__internal_tools",
                    },
                ],
            },
            {
                "kind": "any",
                "filters": [
                    {"kind": "contains", "field": "model", "value": "opus"},
                    {"kind": "equals", "field": "provider", "value": "codex"},
                ],
            },
            {
                "kind": "not",
                "filter": {"kind": "equals", "field": "type", "value": "workflow"},
            },
        ],
    }


def test_compile_agents_live_query_pushdown_matches_legacy_equivalent_filters() -> None:
    pairs = (
        ("cl:target", "cl:target"),
        ("model:opus", "model:opus"),
        ("type:workflow", "kind:workflow"),
        ("type:run", "kind:agent"),
        ("cl:target AND NOT type:workflow", "cl:target AND NOT kind:workflow"),
    )

    for legacy_query, live_query in pairs:
        legacy = compile_agent_query_pushdown(legacy_query)
        live = compile_agents_live_query_pushdown(live_query)

        assert live.window_safe is legacy.window_safe
        assert live.candidate_filter == legacy.candidate_filter


def test_compile_agents_live_query_pushdown_keeps_unsupported_queries_unbounded() -> (
    None
):
    for query in (
        "status:FAILED",
        "machine:apollo",
        "kind:member",
        '"free text"',
    ):
        plan = compile_agents_live_query_pushdown(query)

        assert plan.raw_query == query
        assert plan.window_safe is False
        assert plan.candidate_filter is None
        assert plan.unsupported_reason == "unsupported_query"


def test_compile_agents_live_query_pushdown_reports_legacy_parse_hint() -> None:
    plan = compile_agents_live_query_pushdown("age>2h")

    assert plan.window_safe is False
    assert plan.candidate_filter is None
    assert plan.unsupported_reason is not None
    assert "until:2h" in plan.unsupported_reason
