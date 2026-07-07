"""Tests for VCS repository completion headless foundations."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.workspace_provider import VcsRepoCandidates, VcsRepoEntry
from sase.xprompt import vcs_repo_completion as vrc
from sase.xprompt.vcs_repo_completion import (
    VCS_REPO_GOLDEN_CURSOR,
    VCS_REPO_GOLDEN_VECTORS,
    VcsRepoCompletionConfig,
    apply_vcs_repo_selection,
    fetch_repo_candidates,
    filter_vcs_repo_entries,
    find_vcs_repo_trigger,
    load_vcs_repo_completion_config,
    vcs_repo_catalog_response,
)


@pytest.fixture(autouse=True)
def _clear_repo_completion_cache() -> Iterator[None]:
    vrc._MEMO_CACHE.clear()
    yield
    vrc._MEMO_CACHE.clear()


def _entry(
    name: str,
    *,
    ref: str | None = None,
    pushed_at: str | None = None,
) -> VcsRepoEntry:
    return VcsRepoEntry(
        name=name,
        ref=ref or f"bbugyi200/{name}",
        description=f"{name} description",
        visibility="PUBLIC",
        pushed_at=pushed_at,
    )


@pytest.mark.parametrize(
    ("marked", "workflow_names", "selected_ref", "expected"),
    VCS_REPO_GOLDEN_VECTORS,
)
def test_golden_vectors(
    marked: str,
    workflow_names: tuple[str, ...],
    selected_ref: str,
    expected: str,
) -> None:
    cursor = marked.index(VCS_REPO_GOLDEN_CURSOR)
    prompt = marked.replace(VCS_REPO_GOLDEN_CURSOR, "")

    trigger = find_vcs_repo_trigger(prompt, cursor, workflow_names)
    assert trigger is not None

    assert apply_vcs_repo_selection(prompt, trigger, selected_ref) == expected


def test_trigger_detects_colon_form() -> None:
    trigger = find_vcs_repo_trigger("#gh:bbugyi200/sa", 16, {"gh"})

    assert trigger is not None
    assert trigger.workflow == "gh"
    assert trigger.separator == ":"
    assert trigger.namespace == "bbugyi200"
    assert trigger.query == "sa"
    assert trigger.value_span == (4, 16)
    assert trigger.namespace_span == (4, 13)
    assert trigger.query_span == (14, 16)


def test_trigger_detects_paren_form_with_hitl_marker() -> None:
    prompt = "#gh??(bbugyi200/sa"

    trigger = find_vcs_repo_trigger(prompt, len(prompt), {"gh"})

    assert trigger is not None
    assert trigger.workflow == "gh"
    assert trigger.separator == "("
    assert trigger.namespace == "bbugyi200"
    assert trigger.query == "sa"


def test_trigger_splits_nested_namespace_at_last_slash() -> None:
    prompt = "#gl:group/subgroup/sa"

    trigger = find_vcs_repo_trigger(prompt, len(prompt), {"gl"})

    assert trigger is not None
    assert trigger.namespace == "group/subgroup"
    assert trigger.query == "sa"


def test_trigger_query_stops_at_cursor_but_value_span_covers_ref() -> None:
    prompt = "#gh:bbugyi200/sasex"
    cursor = prompt.index("sa") + 2

    trigger = find_vcs_repo_trigger(prompt, cursor, {"gh"})

    assert trigger is not None
    assert trigger.query == "sa"
    assert trigger.value_span == (4, len(prompt))


@pytest.mark.parametrize(
    "prompt",
    [
        "#gh:bbugyi200",
        "#gh:/sa",
        "#gh:~/sa",
        "#gh:./sa",
        "#gh:https://github.com/bbugyi200/sase",
        "#gh_bbugyi200/sase",
        "word#gh:bbugyi200/sa",
        "#foo:bbugyi200/sa",
        "#gh(bbugyi200/sa)",
    ],
)
def test_trigger_negatives(prompt: str) -> None:
    assert find_vcs_repo_trigger(prompt, len(prompt), {"gh"}) is None


def test_config_reader_uses_defaults_and_overrides() -> None:
    assert load_vcs_repo_completion_config({}) == VcsRepoCompletionConfig()

    config = load_vcs_repo_completion_config(
        {
            "vcs_repo_completion": {
                "enabled": False,
                "cache_ttl_seconds": 30,
                "max_repos": 25,
            }
        }
    )

    assert config == VcsRepoCompletionConfig(
        enabled=False,
        cache_ttl_seconds=30,
        max_repos=25,
    )


def test_fetch_repo_candidates_uses_memo_and_disk_cache(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase_home"))
    monkeypatch.setattr(vrc.time, "time", lambda: 1000.0)
    calls: list[tuple[str, str]] = []

    def fake_list(workflow_type: str, namespace: str) -> VcsRepoCandidates:
        calls.append((workflow_type, namespace))
        return VcsRepoCandidates(
            status="ok",
            provider_display="GitHub",
            entries=(_entry("sase"),),
        )

    monkeypatch.setattr(vrc.workspace_provider, "list_repo_candidates", fake_list)
    config = VcsRepoCompletionConfig(cache_ttl_seconds=600)

    first = fetch_repo_candidates("gh", "bbugyi200", config=config)
    second = fetch_repo_candidates("gh", "bbugyi200", config=config)
    vrc._MEMO_CACHE.clear()
    third = fetch_repo_candidates("gh", "bbugyi200", config=config)

    assert [entry.name for entry in first.entries] == ["sase"]
    assert [entry.name for entry in second.entries] == ["sase"]
    assert [entry.name for entry in third.entries] == ["sase"]
    assert calls == [("gh", "bbugyi200")]


def test_fetch_repo_candidates_serves_stale_entries_on_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase_home"))
    now = 1000.0
    monkeypatch.setattr(vrc.time, "time", lambda: now)
    responses = [
        VcsRepoCandidates(
            status="ok",
            provider_display="GitHub",
            entries=(_entry("sase"),),
        ),
        VcsRepoCandidates(
            status="error",
            error_kind="auth",
            message="run gh auth login",
            provider_display="GitHub",
            entries=(),
        ),
    ]

    def fake_list(_workflow_type: str, _namespace: str) -> VcsRepoCandidates:
        return responses.pop(0)

    monkeypatch.setattr(vrc.workspace_provider, "list_repo_candidates", fake_list)
    config = VcsRepoCompletionConfig(cache_ttl_seconds=10)

    assert fetch_repo_candidates("gh", "bbugyi200", config=config).status == "ok"
    now = 1020.0
    stale = fetch_repo_candidates("gh", "bbugyi200", config=config)

    assert stale.status == "error"
    assert stale.error_kind == "auth"
    assert stale.message == "run gh auth login"
    assert stale.stale is True
    assert [entry.name for entry in stale.entries] == ["sase"]


def test_fetch_repo_candidates_disabled_skips_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_list(_workflow_type: str, _namespace: str) -> VcsRepoCandidates:
        raise AssertionError("provider should not be called")

    monkeypatch.setattr(vrc.workspace_provider, "list_repo_candidates", fake_list)

    result = fetch_repo_candidates(
        "gh",
        "bbugyi200",
        config=VcsRepoCompletionConfig(enabled=False),
    )

    assert result.status == "ok"
    assert result.entries == ()


def test_filter_vcs_repo_entries_ranks_prefix_then_recent_then_name() -> None:
    entries = [
        _entry("bob-sase", pushed_at="2026-04-01T00:00:00Z"),
        _entry("sample", pushed_at="2026-01-01T00:00:00Z"),
        _entry("sash"),
        _entry("sase", pushed_at="2026-02-01T00:00:00Z"),
        _entry("other"),
    ]

    filtered = filter_vcs_repo_entries(entries, "sa")

    assert [entry.name for entry in filtered] == [
        "sase",
        "sample",
        "sash",
        "bob-sase",
    ]


def test_vcs_repo_catalog_response_round_trip(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase_home"))
    monkeypatch.setattr(
        vrc.workspace_provider,
        "list_repo_candidates",
        lambda _workflow, _namespace: VcsRepoCandidates(
            status="ok",
            provider_display="GitHub",
            entries=(_entry("sase"),),
        ),
    )

    data = vcs_repo_catalog_response(
        {"schema_version": 1, "workflow": "gh", "namespace": "bbugyi200"}
    )

    assert data["schema_version"] == 1
    assert data["status"] == "ok"
    assert data["provider_display"] == "GitHub"
    assert data["entries"] == [
        {
            "name": "sase",
            "ref": "bbugyi200/sase",
            "description": "sase description",
            "visibility": "PUBLIC",
            "is_fork": False,
            "is_archived": False,
            "pushed_at": None,
        }
    ]


def test_vcs_repo_catalog_response_rejects_bad_request() -> None:
    with pytest.raises(ValueError, match="workflow is required"):
        vcs_repo_catalog_response({"schema_version": 1, "namespace": "bbugyi200"})
