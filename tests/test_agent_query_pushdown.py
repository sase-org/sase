from __future__ import annotations

from sase.ace.query_profile.profiles._agents_live import agents_live_query_schema
from sase.ace.tui.models.agent_live_query_pushdown import (
    KNOWN_FALLBACK_FIELDS,
    _PUSHABLE_EXACT_FIELDS,
    _PUSHABLE_KIND_FIELD,
    _PUSHABLE_MACHINE_FIELD,
    _PUSHABLE_PROJECT_FIELD,
    _PUSHABLE_TEXT_FIELDS,
    compile_agents_live_query_pushdown,
)

_PUSHABLE_FIELDS = (
    _PUSHABLE_TEXT_FIELDS
    | _PUSHABLE_EXACT_FIELDS
    | {_PUSHABLE_KIND_FIELD, _PUSHABLE_PROJECT_FIELD, _PUSHABLE_MACHINE_FIELD}
)


def test_compile_agents_live_query_pushdown_builds_exact_profile_filter(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_live_query_pushdown."
        "project_display_name_map_signature",
        lambda: (("gh_example__internal_tools", "Internal Tools"),),
    )

    plan = compile_agents_live_query_pushdown(
        'project:"Internal Tools" AND (model:opus OR provider:codex)'
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
        ],
    }


def test_compile_agents_live_query_pushdown_keeps_unsupported_queries_unbounded() -> (
    None
):
    for query in (
        "status:FAILED",
        "kind:member",
        "NOT provider:grok",
        "cl:target AND NOT kind:workflow",
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


def test_compile_machine_pushdown_builds_exact_machine_filters() -> None:
    machine_equals = {"kind": "equals", "field": "machine", "value": "apollo"}
    live_match = compile_agents_live_query_pushdown("machine:apollo")
    live_not = compile_agents_live_query_pushdown("not machine:apollo")
    live_compound = compile_agents_live_query_pushdown(
        "cl:feature AND not machine:apollo"
    )

    assert live_match.window_safe is True
    assert live_match.candidate_filter == machine_equals
    assert live_not.window_safe is True
    assert live_not.candidate_filter == {"kind": "not", "filter": machine_equals}
    assert live_compound.window_safe is True
    assert live_compound.candidate_filter == {
        "kind": "all",
        "filters": [
            {"kind": "contains", "field": "cl", "value": "feature"},
            {"kind": "not", "filter": machine_equals},
        ],
    }


def test_compile_machine_pushdown_normalizes_local_to_here() -> None:
    here_equals = {"kind": "equals", "field": "machine", "value": "here"}
    live = compile_agents_live_query_pushdown("machine:local")

    assert live.window_safe is True
    assert live.candidate_filter == here_equals


def test_compile_machine_pushdown_leaves_bare_machine_unpushable() -> None:
    live = compile_agents_live_query_pushdown("machine:")

    assert live.window_safe is False
    assert live.candidate_filter is None


def test_compile_agents_live_query_pushdown_still_rejects_non_machine_negation() -> (
    None
):
    plan = compile_agents_live_query_pushdown("NOT provider:grok")

    assert plan.window_safe is False
    assert plan.candidate_filter is None


def test_agents_live_pushdown_coverage_classifies_every_profile_field() -> None:
    keys = {field.key for field in agents_live_query_schema().fields}

    assert not (_PUSHABLE_FIELDS & KNOWN_FALLBACK_FIELDS)
    assert keys - _PUSHABLE_FIELDS - KNOWN_FALLBACK_FIELDS == set()
    assert keys == _PUSHABLE_FIELDS | KNOWN_FALLBACK_FIELDS


def test_agents_live_pushdown_coverage_fails_for_unclassified_field() -> None:
    keys = {field.key for field in agents_live_query_schema().fields}
    keys.add("brand_new_trap")

    assert keys - _PUSHABLE_FIELDS - KNOWN_FALLBACK_FIELDS == {"brand_new_trap"}


def test_agents_live_pushdown_never_pushes_glob_values() -> None:
    for query in ("project:sa*", "provider:*", "model:claude*"):
        plan = compile_agents_live_query_pushdown(query)

        assert plan.raw_query == query
        assert plan.window_safe is False
        assert plan.candidate_filter is None
