"""Prove provider query schemas are derived generically from provider specs."""

from __future__ import annotations

from pathlib import Path

import yaml

from sase.ace.query_profile import compile_query_profile, provider_query_schema
from sase.ace.query_profile.registry import HOST_PREDICATES

from tests._query_profile_helpers import assert_closed_host_predicates


_NOTES_FIXTURE = (
    Path(__file__).parent
    / "ace"
    / "tui"
    / "artifacts_contract"
    / "fixtures"
    / "notes"
    / "provider.yml"
)


def test_provider_query_schema_derives_fields_from_the_notes_fixture() -> None:
    spec = yaml.safe_load(_NOTES_FIXTURE.read_text(encoding="utf-8"))
    profile = compile_query_profile(provider_query_schema("notes", spec))
    assert profile.pane_id == "ref:notes"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    assert_closed_host_predicates(profile)
    # ``related`` and ``family`` back the fixture's declared relations: a
    # ``ref.relations[].source`` must name a declared ``ref.properties`` key, so
    # relation sources are ordinary queryable fields like any other property.
    assert {item.key for item in profile.fields} == {
        "title",
        "status",
        "related",
        "family",
        "path",
    }
    assert all(item.value_kind == "string" for item in profile.fields)
    assert all(item.searchable for item in profile.fields)
    assert all(item.negatable for item in profile.fields)
    assert profile.identity_field == "path"
    assert profile.free_text_hint == "family, related, status, title, path (AND)"


def test_provider_query_schema_handles_missing_and_malformed_specs() -> None:
    empty = compile_query_profile(provider_query_schema("empty", None))
    assert {item.key for item in empty.fields} == {"path"}
    assert compile_query_profile(provider_query_schema("empty", {})).identity_field == (
        "path"
    )
    malformed = {"ref": {"properties": "not-a-mapping"}}
    assert {
        item.key
        for item in compile_query_profile(
            provider_query_schema("bad", malformed)
        ).fields
    } == {"path"}


def test_provider_query_schema_degrades_unknown_types_to_string() -> None:
    spec = {
        "ref": {
            "properties": {
                "created": {"type": "datetime"},
                "tags": {"type": "string_list"},
                "mystery": {"type": "some_future_type"},
            }
        }
    }
    profile = compile_query_profile(provider_query_schema("kind", spec))
    assert profile.field("created").value_kind == "date"
    assert profile.field("tags").value_kind == "string"
    assert profile.field("tags").repeatable is True
    assert profile.field("mystery").value_kind == "string"


def test_provider_query_schema_grants_only_closed_host_predicates() -> None:
    spec = {"ref": {"properties": {"anything": {"type": "string"}}}}
    schema = provider_query_schema("kind", spec)
    assert schema.sigils == ()
    assert schema.macros == ()
    assert schema.predicates == tuple(sorted(HOST_PREDICATES))
    assert schema.any_special is True
