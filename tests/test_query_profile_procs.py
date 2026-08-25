"""Prove the procs query profile matches the proc query facade dialect."""

from __future__ import annotations

import pytest

from sase.ace.query.profile_reference import (
    ProfileQueryError,
    canonical_query_for_profile,
    parse_query_for_profile,
)
from sase.ace.query.types import to_canonical_string
from sase.ace.query_profile import compile_query_profile, procs_query_schema
from sase.main.parser_proc import PROC_KIND_CHOICES, PROC_STATUS_CHOICES


def test_procs_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(procs_query_schema())
    assert profile.pane_id == "procs"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    assert profile.predicates == ()
    assert profile.any_special is False
    sample_values = {
        "text": "anything",
        "cmd": "just check",
        "out": "traceback",
        "name": "my proc",
        "agent": "bbugyi200.athena.sase-s9.2",
        "project": "sase",
        "status": "running",
        "kind": "command",
        "monitor": "true",
        "running": "true",
        "failed": "false",
        "exit": "1",
        "min": "300",
        "max": "5m",
        "after": "1d",
        "before": "today",
        "since": "1d",
        "until": "today",
        "limit": "40",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        # ``limit:`` is host-owned and stripped before dialect parse, so a
        # lone ``limit:N`` query parses as empty; pair it with an anchor.
        query = f"{key}:{value}" if key != "limit" else f"monitor {key}:{value}"
        parse_query_for_profile(query, profile)  # must not raise


def test_procs_profile_every_field_but_limit_is_negatable() -> None:
    profile = compile_query_profile(procs_query_schema())
    filterable = {item.key: item for item in profile.fields if item.filterable}
    assert {key for key, item in filterable.items() if not item.negatable} == {"limit"}
    for key, value in {"monitor": "true", "status": "running", "min": "300"}.items():
        parse_query_for_profile(f"-{key}:{value}", profile)  # must not raise


def test_procs_profile_status_and_kind_enums_match_the_cli() -> None:
    profile = compile_query_profile(procs_query_schema())
    assert profile.field("status").static_values == PROC_STATUS_CHOICES
    assert profile.field("kind").static_values == PROC_KIND_CHOICES
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("status:not-a-real-status", profile)
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("kind:not-a-real-kind", profile)


def test_procs_profile_boolean_fields_take_the_bare_shorthand() -> None:
    profile = compile_query_profile(procs_query_schema())
    bool_keys = {item.key for item in profile.fields if item.value_kind == "bool"}
    assert bool_keys == {"monitor", "running", "failed"}
    for key in bool_keys:
        assert canonical_query_for_profile(key, profile) == f"{key}:true"
        assert canonical_query_for_profile(f"-{key}", profile) == f"-{key}:true"


def test_procs_profile_duration_and_date_bound_keys_normalize() -> None:
    profile = compile_query_profile(procs_query_schema())
    assert canonical_query_for_profile("min:5m", profile) == "min:300"
    assert canonical_query_for_profile("max:2h", profile) == "max:7200"
    with pytest.raises(ProfileQueryError, match="composite"):
        parse_query_for_profile("min:1h30m", profile)


def test_procs_profile_searchable_fields_are_the_free_text_corpus() -> None:
    profile = compile_query_profile(procs_query_schema())
    assert set(profile.searchable_fields()) == {"cmd", "out", "name"}
    assert profile.free_text_hint == "command, label, output (implicit AND)"


def test_procs_profile_project_field_is_exact_match() -> None:
    profile = compile_query_profile(procs_query_schema())
    assert profile.field("project").exact_match is True


def test_procs_profile_declares_the_host_limit_field() -> None:
    assert compile_query_profile(procs_query_schema()).field("limit") is not None


def test_procs_profile_has_no_host_predicates() -> None:
    profile = compile_query_profile(procs_query_schema())
    assert profile.predicates == ()
    assert profile.any_special is False
    # With no predicates declared, the bare @/!/$ shorthands fall back to text.
    assert to_canonical_string(parse_query_for_profile("@", profile)) == '"@"'


def test_procs_profile_worked_example_canonicalizes() -> None:
    profile = compile_query_profile(procs_query_schema())
    canonical = canonical_query_for_profile('"just check" -monitor -min:300', profile)
    assert canonical == '-min:300 -monitor:true "just check"'
