"""Configuration coverage for the Artifacts Commits default query."""

from __future__ import annotations

import pytest
from jsonschema import Draft7Validator, ValidationError

from sase.ace.tui.widgets.artifacts.commit_config import (
    BUNDLED_COMMITS_DEFAULT_QUERY,
    merge_commits_startup_project,
    resolve_commits_default_query,
)
from sase.config.inventory import config_field_model, load_config_schema
from sase.vcs_log.filter_query import parse_commit_filter_query, to_query_string
from tests._project_display_case import ProjectDisplayCase


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


def test_startup_project_precedence_is_explicit_then_config_then_cwd() -> None:
    configured = parse_commit_filter_query("project:configured sidecar:false")

    assert (
        merge_commits_startup_project(
            configured,
            explicit_project="ace-query",
            current_project="cwd",
        ).project
        == "ace-query"
    )
    assert (
        merge_commits_startup_project(
            configured,
            explicit_project=None,
            current_project="cwd",
        ).project
        == "configured"
    )
    assert (
        merge_commits_startup_project(
            parse_commit_filter_query("sidecar:false"),
            explicit_project=None,
            current_project="cwd",
        ).project
        == "cwd"
    )


def test_startup_project_remains_absent_without_any_known_project() -> None:
    values = parse_commit_filter_query("sidecar:false")

    assert (
        merge_commits_startup_project(
            values,
            explicit_project=None,
            current_project=None,
        )
        is values
    )


@pytest.mark.parametrize("source", ("inferred", "configured", "ace-query"))
async def test_known_startup_project_is_displayed_before_first_collection(
    source: str,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    from typing import Any

    from sase.ace.testing import AcePage
    from sase.ace.tui.widgets.artifacts import CommitsPane
    from sase.ace.tui.widgets.single_line_vim_text_area import (
        SingleLineVimTextArea,
    )
    from sase.project_display_names import ProjectRefDisplaySnapshot
    import sase.ace.tui.widgets.artifacts.commits as commits_module
    from tests.ace.tui._commits_pane_helpers import _result

    startup_load_calls = 0
    collection_calls: list[dict[str, Any]] = []

    def load_startup_projection() -> ProjectRefDisplaySnapshot:
        nonlocal startup_load_calls
        startup_load_calls += 1
        return ProjectRefDisplaySnapshot(project_display_case.snapshot)

    monkeypatch.setattr(
        "sase.project_display_names.load_project_ref_display_snapshot",
        load_startup_projection,
    )
    configured_query = (
        f"project:{project_display_case.project_key} sidecar:false"
        if source == "configured"
        else (
            "project:configured sidecar:false"
            if source == "ace-query"
            else "sidecar:false"
        )
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {"artifacts": {"commits": {"default_query": configured_query}}}
        },
    )
    current_project = (
        project_display_case.project_key if source == "inferred" else "cwd-project"
    )
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: ("/tmp/current.sase", 1, current_project),
    )
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: collection_calls.append(kwargs) or _result(),
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")
    query = (
        f"project:{project_display_case.project_key}"
        if source == "ace-query"
        else '"feature"'
    )

    async with AcePage(query=query, initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        editor = pane.query_one("#commit-filter-input", SingleLineVimTextArea)
        assert (
            editor.text == f"project:{project_display_case.project_label} sidecar:false"
        )
        await page.wait_for(lambda _state: bool(collection_calls))

        assert (
            collection_calls[0]["project_scope"] == project_display_case.project_label
        )
        assert startup_load_calls == 1
