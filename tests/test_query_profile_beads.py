"""Prove the beads query profile matches the beads parser dialect."""

from __future__ import annotations

import pytest

from sase.ace.query_profile import beads_query_schema, compile_query_profile
from sase.bead.filter_query import BeadFilterQueryError, parse_bead_filter_query

from tests._query_profile_helpers import assert_closed_host_predicates


def test_beads_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(beads_query_schema())
    assert profile.pane_id == "beads"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    assert_closed_host_predicates(profile)
    sample_values = {
        "type": "task",
        "tier": "epic",
        "status": "open",
        "size": "medium",
        "due": "soon",
        "project": "myproj",
        "assignee": "alice",
        "owner": "alice@example.com",
        "model": "sonnet",
        "has": "plan",
        "bug": "none",
        "label": "bug",
        "task_type": "flake",
        "since": "1d",
        "until": "1h",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_bead_filter_query(f"{key}:{value}")  # must not raise


def test_beads_profile_every_field_is_repeatable_and_negatable() -> None:
    profile = compile_query_profile(beads_query_schema())
    filterable = tuple(item for item in profile.fields if item.filterable)
    assert all(item.repeatable for item in filterable)
    assert all(item.negatable for item in filterable)
    for key in ("type", "assignee", "since"):
        value = {"type": "task", "assignee": "alice", "since": "1d"}[key]
        parse_bead_filter_query(f"-{key}:{value}")  # must not raise


def test_beads_profile_enum_fields_reject_out_of_vocabulary_values() -> None:
    profile = compile_query_profile(beads_query_schema())
    enum_keys = {item.key for item in profile.fields if item.value_kind == "enum"}
    assert enum_keys == {"type", "tier", "status", "size", "due", "has"}
    for key in enum_keys:
        with pytest.raises(BeadFilterQueryError):
            parse_bead_filter_query(f"{key}:not-a-real-value")


def test_beads_profile_string_fields_accept_arbitrary_values() -> None:
    profile = compile_query_profile(beads_query_schema())
    string_keys = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "string"
    }
    assert string_keys == {
        "project",
        "assignee",
        "owner",
        "model",
        "bug",
        "label",
        "task_type",
    }
    for key in string_keys:
        parse_bead_filter_query(f"{key}:anything-goes")  # must not raise


def test_beads_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(beads_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"id", "title", "body", "refs"}
    assert profile.free_text_hint == "id, title, body, refs (AND)"
