"""Prove the stitches query profile matches the commit parser dialect."""

from __future__ import annotations

import pytest

from sase.ace.query_profile import (
    beads_query_schema,
    compile_query_profile,
    files_query_schema,
    patches_query_schema,
    plans_query_schema,
    stitches_query_schema,
)
from sase.vcs_log.filter_query import CommitFilterQueryError, parse_commit_filter_query

from tests._query_profile_helpers import assert_closed_host_predicates


def test_stitches_profile_has_no_sigils_or_macros() -> None:
    profile = compile_query_profile(stitches_query_schema())
    assert profile.pane_id == "stitches"
    assert profile.boolean is False
    assert profile.sigils == ()
    assert profile.macros == ()
    assert_closed_host_predicates(profile)


def test_stitches_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(stitches_query_schema())
    sample_values = {
        "project": "myproj",
        "repo": "myrepo",
        "author": "alice",
        "origin": "stitch",
        "type": "automatic",
        "since": "1d",
        "until": "1h",
        "sidecar": "true",
        "merges": "hide",
        "limit": "40",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_commit_filter_query(f"{key}:{value}")  # must not raise


def test_stitches_profile_negatable_fields_match_the_parser() -> None:
    profile = compile_query_profile(stitches_query_schema())
    negatable = set(profile.negatable_fields())
    assert negatable == {"repo", "author", "origin", "type"}
    for key in negatable:
        value = {
            "repo": "myrepo",
            "author": "alice",
            "origin": "stitch",
            "type": "automatic",
        }[key]
        parse_commit_filter_query(f"-{key}:{value}")  # must not raise
    for key in {item.key for item in profile.fields if item.filterable} - negatable:
        value = {
            "project": "myproj",
            "since": "1d",
            "until": "1h",
            "sidecar": "true",
            "merges": "hide",
            "limit": "40",
        }[key]
        with pytest.raises(CommitFilterQueryError):
            parse_commit_filter_query(f"-{key}:{value}")


def test_stitches_profile_project_field_is_not_repeatable() -> None:
    profile = compile_query_profile(stitches_query_schema())
    assert profile.field("project") is not None
    assert profile.field("project").repeatable is False
    with pytest.raises(CommitFilterQueryError, match="does not accept comma"):
        parse_commit_filter_query("project:a,b")


def test_stitches_profile_repeatable_fields_accept_comma_lists() -> None:
    profile = compile_query_profile(stitches_query_schema())
    for key in profile.negatable_fields():
        assert profile.field(key).repeatable is True
    values = parse_commit_filter_query("repo:a,b")
    assert values.repos == ("a", "b")
    values = parse_commit_filter_query("type:automatic,bead_work")
    assert values.types == ("automatic", "bead_work")


def test_stitches_profile_search_only_field_is_subject() -> None:
    profile = compile_query_profile(stitches_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"subject"}
    assert profile.field("subject").searchable is True


def test_host_owned_limit_is_not_a_row_field_except_on_stitches() -> None:
    assert compile_query_profile(stitches_query_schema()).field("limit") is not None
    for schema in (
        beads_query_schema(),
        plans_query_schema(),
        files_query_schema(),
        patches_query_schema(),
    ):
        profile = compile_query_profile(schema)
        assert profile.field("limit") is None
        assert "limit" not in profile.filterable_fields()
