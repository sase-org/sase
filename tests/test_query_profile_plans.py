"""Prove the plans query profile matches the plan parser dialect."""

from __future__ import annotations

import pytest

from sase.ace.query_profile import compile_query_profile, plans_query_schema
from sase.plan_search.filter_query import PlanFilterQueryError, parse_plan_filter_query

from tests._query_profile_helpers import assert_closed_host_predicates


def test_plans_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(plans_query_schema())
    assert profile.pane_id == "ref:plan"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    assert_closed_host_predicates(profile)
    sample_values = {
        "kind": "proposal",
        "status": "anything-goes",
        "tier": "epic",
        "project": "myproj",
        "since": "1d",
        "until": "1h",
        "path": "docs/demo.md",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_plan_filter_query(f"{key}:{value}")  # must not raise


def test_plans_profile_declares_no_enum_validated_fields() -> None:
    profile = compile_query_profile(plans_query_schema())
    assert not any(item.value_kind == "enum" for item in profile.fields)
    # kind/status/tier all accept values outside their completion hints.
    for key in ("kind", "status", "tier"):
        parse_plan_filter_query(f"{key}:totally-made-up")  # must not raise


def test_plans_profile_since_until_are_not_repeatable() -> None:
    profile = compile_query_profile(plans_query_schema())
    assert profile.field("since").repeatable is False
    assert profile.field("until").repeatable is False
    with pytest.raises(PlanFilterQueryError, match="may only appear once"):
        parse_plan_filter_query("since:1d since:2d")


def test_plans_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(plans_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"title", "body"}
    assert profile.free_text_hint == "title, body, path (AND)"
    assert profile.identity_field == "path"
    assert profile.field("path").filterable is True
    assert profile.field("path").exact_match is True
