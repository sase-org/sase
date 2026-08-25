"""Prove the files query profile matches the files parser dialect."""

from __future__ import annotations

import pytest

from sase.ace.query_profile import compile_query_profile, files_query_schema
from sase.ace.tui.widgets.artifacts.files_filtering import (
    FilesFilterQueryError,
    parse_files_filter_query,
)

from tests._query_profile_helpers import assert_closed_host_predicates


def test_files_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(files_query_schema())
    assert profile.pane_id == "files"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    assert_closed_host_predicates(profile)
    sample_values = {
        "kind": "file",
        "project": "myproj",
        "agent": "bob",
        "workflow": "flow",
        "origin": "created",
        "since": "2024-01-01",
        "until": "2024-02-01",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_files_filter_query(f"{key}:{value}")  # must not raise


def test_files_profile_negatable_fields_match_the_parser() -> None:
    profile = compile_query_profile(files_query_schema())
    assert set(profile.negatable_fields()) == {
        "agent",
        "kind",
        "origin",
        "project",
        "since",
        "until",
        "workflow",
    }
    for key, value in {
        "agent": "bob",
        "kind": "file",
        "origin": "created",
        "project": "myproj",
        "since": "2024-01-01",
        "until": "2024-02-01",
        "workflow": "flow",
    }.items():
        parse_files_filter_query(f"-{key}:{value}")  # must not raise
    assert parse_files_filter_query("-freetext").excluded_text == ("freetext",)


def test_files_profile_enum_fields_reject_out_of_vocabulary_values() -> None:
    profile = compile_query_profile(files_query_schema())
    enum_keys = {item.key for item in profile.fields if item.value_kind == "enum"}
    assert enum_keys == {"kind", "origin"}
    for key in enum_keys:
        with pytest.raises(FilesFilterQueryError):
            parse_files_filter_query(f"{key}:not-a-real-value")


def test_files_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(files_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"label", "stored_path", "source_path"}
    assert profile.free_text_hint == "label, stored path, source path (AND)"
