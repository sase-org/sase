"""Configuration coverage for the Artifacts Commits default query."""

from __future__ import annotations

import pytest
from jsonschema import Draft7Validator, ValidationError

from sase.ace.tui.widgets.artifacts.commit_config import (
    BUNDLED_COMMITS_DEFAULT_QUERY,
    resolve_commits_default_query,
)
from sase.config.inventory import config_field_model, load_config_schema
from sase.vcs_log.filter_query import parse_commit_filter_query, to_query_string


def test_commits_default_query_schema_accepts_nested_string() -> None:
    Draft7Validator(load_config_schema()).validate(
        {"ace": {"artifacts": {"commits": {"default_query": "sidecar:true"}}}}
    )


def test_commits_default_query_is_exposed_in_config_inventory() -> None:
    fields = {field.path: field for field in config_field_model().fields}
    field = fields["ace.artifacts.commits.default_query"]

    assert field.types == ("string",)
    assert field.default == BUNDLED_COMMITS_DEFAULT_QUERY


@pytest.mark.parametrize("value", [False, 24, [], {}])
def test_commits_default_query_schema_rejects_wrong_types(value: object) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(load_config_schema()).validate(
            {"ace": {"artifacts": {"commits": {"default_query": value}}}}
        )


def test_valid_custom_commits_query_is_parsed_once_for_startup() -> None:
    resolved = resolve_commits_default_query(
        {"artifacts": {"commits": {"default_query": "repo:sase sidecar:true"}}}
    )

    assert to_query_string(resolved.values) == "repo:sase sidecar:true"
    assert resolved.diagnostic is None


@pytest.mark.parametrize("value", [False, "repo:"])
def test_invalid_runtime_query_falls_back_with_diagnostic(value: object) -> None:
    resolved = resolve_commits_default_query(
        {"artifacts": {"commits": {"default_query": value}}}
    )

    assert resolved.values == parse_commit_filter_query(BUNDLED_COMMITS_DEFAULT_QUERY)
    assert resolved.diagnostic is not None
    assert "using bundled commits query" in resolved.diagnostic


def test_missing_runtime_query_uses_bundled_value_without_warning() -> None:
    resolved = resolve_commits_default_query({})

    assert to_query_string(resolved.values) == BUNDLED_COMMITS_DEFAULT_QUERY
    assert resolved.values.limit == 0
    assert resolved.diagnostic is None
