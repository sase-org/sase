"""Tests for the alias-history modal's immutable request/state helpers."""

from __future__ import annotations

from sase.ace.tui.modals.alias_history_state import (
    AliasHistoryEntryRequest,
    adjusted_alias_history_limit,
    alias_history_run_key,
    initial_alias_history_load_request,
)
from sase.llm_provider.alias_history import _AliasHistoryProvenance, AliasHistoryRun


def _run(artifact_dir: str = "/tmp/a") -> AliasHistoryRun:
    return AliasHistoryRun(
        artifact_dir=artifact_dir,
        project_key="gh_sase-org__sase",
        project_name="sase",
        workflow_dir_name="ace-run",
        timestamp="20260816120000",
        alias_position=0,
        status="done",
        has_done_marker=True,
        hidden=False,
        provenance=_AliasHistoryProvenance(kind="direct", label="direct"),
        rollup_status="done",
    )


def test_entry_request_is_single_alias_for_one_alias() -> None:
    entry = AliasHistoryEntryRequest(
        aliases=("large",), title_label="@large", is_user_owned=False
    )
    assert entry.is_single_alias is True


def test_entry_request_is_not_single_alias_for_bucket() -> None:
    entry = AliasHistoryEntryRequest(
        aliases=("research_a", "research_b"),
        title_label="research",
        is_user_owned=True,
    )
    assert entry.is_single_alias is False


def test_initial_load_request_uses_config_limit_and_cached_freshness() -> None:
    entry = AliasHistoryEntryRequest(
        aliases=("large", "medium"), title_label="bucket", is_user_owned=False
    )
    request = initial_alias_history_load_request(entry)
    assert request.aliases == ("large", "medium")
    assert request.limit_per_alias is None
    assert request.include_hidden is False
    assert request.freshness == "cached"


def test_run_key_combines_alias_and_artifact_dir() -> None:
    run = _run("/tmp/agent-a")
    assert alias_history_run_key("large", run) == "large:/tmp/agent-a"


def test_run_key_distinguishes_same_alias_different_runs() -> None:
    first = alias_history_run_key("large", _run("/tmp/one"))
    second = alias_history_run_key("large", _run("/tmp/two"))
    assert first != second


def test_run_key_distinguishes_same_run_different_group_alias() -> None:
    run = _run("/tmp/shared")
    assert alias_history_run_key("large", run) != alias_history_run_key("medium", run)


def test_adjusted_limit_adds_page_size_on_load_more() -> None:
    assert (
        adjusted_alias_history_limit(
            10, initial_limit=10, page_size=100, direction="load_more"
        )
        == 110
    )


def test_adjusted_limit_unloads_down_to_initial_window() -> None:
    assert (
        adjusted_alias_history_limit(
            110, initial_limit=10, page_size=100, direction="unload"
        )
        == 10
    )
    assert (
        adjusted_alias_history_limit(
            50, initial_limit=10, page_size=100, direction="unload"
        )
        == 10
    )
    assert (
        adjusted_alias_history_limit(
            10, initial_limit=10, page_size=100, direction="unload"
        )
        == 10
    )
