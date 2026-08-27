from __future__ import annotations

from sase.ace.agent_query.pushdown import compile_agent_query_pushdown


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


def test_compile_agent_query_pushdown_maps_run_type_alias() -> None:
    plan = compile_agent_query_pushdown("type:run")

    assert plan.window_safe is True
    assert plan.candidate_filter == {
        "kind": "equals",
        "field": "type",
        "value": "agent",
    }
