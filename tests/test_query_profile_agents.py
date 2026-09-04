"""Pin the Artifacts Agent pane query profile."""

from __future__ import annotations

import pytest

from sase.ace.query.profile_reference import (
    ProfileQueryError,
    canonical_query_for_profile,
    parse_query_for_profile,
)
from sase.ace.query_profile import agents_query_schema, compile_query_profile

from tests._query_profile_helpers import assert_closed_host_predicates


def test_agents_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(agents_query_schema())
    assert profile.pane_id == "agents"
    assert profile.boolean is True
    assert profile.sigils == () and profile.macros == ()
    assert_closed_host_predicates(profile)
    sample_values = {
        "name": "sase-r8.9.land",
        "kind": "workflow-child",
        "family": "research.12",
        "clan": "athena.sase-8t",
        "tribe": "epic",
        "role": "code",
        "workflow": "review",
        "parent": "20260822161630",
        "project": "sase",
        "state": "dismissed",
        "status": "failed",
        "hidden": "true",
        "dismissed": "true",
        "revivable": "true",
        "historically_viewable": "true",
        "durably_revivable": "true",
        "restartable": "false",
        "attention": "true",
        "retry": "false",
        "attempt": "2",
        "model": "gpt-5.6-sol",
        "provider": "codex",
        "relation": "read",
        "artifact": "plan:202608/example.md",
        "linked": "true",
        "since": "7d",
        "until": "2026-08-01",
        "after": "2h",
        "before": "today",
        "min": "5m",
        "max": "2h",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_query_for_profile(f"{key}:{value}", profile)  # must not raise


def test_agents_profile_string_field_matching_shapes() -> None:
    profile = compile_query_profile(agents_query_schema())
    exact = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "string" and item.exact_match
    }
    substring = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "string" and not item.exact_match
    }
    assert exact == {"name", "family", "clan", "project", "artifact"}
    assert substring == {"role", "workflow", "parent", "model"}
    assert profile.field("role").static_values == ("code", "plan", "mon")


def test_agents_profile_enum_fields_pin_static_vocabularies() -> None:
    profile = compile_query_profile(agents_query_schema())
    assert profile.field("kind").static_values == (
        "agent",
        "member",
        "family",
        "clan",
        "workflow",
        "workflow-child",
    )
    assert profile.field("state").static_values == ("active", "done", "dismissed")
    assert profile.field("status").static_values == (
        "STARTING",
        "RUNNING",
        "WAITING",
        "DONE",
        "FAILED",
        "COMPLETED",
    )
    assert profile.field("tribe").static_values == ("epic", "chop", "research")
    assert profile.field("provider").static_values == (
        "agy",
        "claude",
        "codex",
        "grok",
        "muse",
        "opencode",
        "qwen",
    )
    assert "read" in profile.field("relation").static_values
    assert "implements" in profile.field("relation").static_values

    assert canonical_query_for_profile("status:failed", profile) == "status:FAILED"
    assert canonical_query_for_profile("relation:read", profile) == "relation:read"
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("kind:not-real", profile)
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("provider:not-real", profile)
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("relation:not-real", profile)


def test_agents_profile_boolean_fields_require_explicit_values() -> None:
    profile = compile_query_profile(agents_query_schema())
    bool_keys = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "bool"
    }
    assert bool_keys == {
        "hidden",
        "dismissed",
        "revivable",
        "historically_viewable",
        "durably_revivable",
        "restartable",
        "attention",
        "retry",
        "linked",
    }
    for key in bool_keys:
        assert canonical_query_for_profile(f"{key}:true", profile) == f"{key}:true"
        assert canonical_query_for_profile(key, profile) == f'"{key}"'
        with pytest.raises(ProfileQueryError):
            parse_query_for_profile(f"{key}:yes", profile)


def test_agents_profile_time_fields_document_month_minute_collision() -> None:
    profile = compile_query_profile(agents_query_schema())
    date_hints = {
        profile.field("since").hint,
        profile.field("until").hint,
        profile.field("after").hint,
        profile.field("before").hint,
    }
    duration_hints = {profile.field("min").hint, profile.field("max").hint}
    assert all("Nm means months" in hint for hint in date_hints)
    assert all("Nm means minutes" in hint for hint in duration_hints)
    assert profile.field("attempt").value_kind == "int"


def test_agents_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(agents_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"label", "text"}
    assert set(profile.searchable_fields()) == {"name", "label", "text"}
    assert profile.free_text_hint == "name, label, text metadata (implicit AND)"
