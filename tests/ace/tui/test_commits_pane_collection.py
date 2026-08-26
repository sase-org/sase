"""Collection and snapshot coverage for the Artifacts Stitches pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import CommitsPane, CommitsTimeline
from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.artifacts.commits_collection import (
    AuthoritativeCommitSnapshot,
    snapshot_covers,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.core.time import get_timezone
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.vcs_log.filter_query import CommitLogFilterValues, parse_commit_filter_query
from sase.vcs_log.models import VcsLogResult
from tests.ace.tui._commits_pane_helpers import _result, _result_with_sidecar


def _result_with_commit_count(
    count: int,
    *,
    timestamp: int | None = None,
    aggregate_truncated: bool = False,
    provider_truncation_possible: bool = False,
) -> VcsLogResult:
    base = _result(timestamp)
    template = base.commits[0]
    commits = tuple(
        replace(
            template,
            commit=replace(
                template.commit,
                full_id=f"{index:040x}",
                short_id=f"{index:07x}",
                timestamp=template.commit.timestamp - index,
            ),
        )
        for index in range(count)
    )
    return replace(
        base,
        commits=commits,
        aggregate_truncated=aggregate_truncated,
        provider_truncation_possible=provider_truncation_possible,
    )


def test_sidecar_snapshot_coverage_is_directional() -> None:
    scope = (None, True)
    narrow_values = CommitLogFilterValues(sidecar=False)
    broad_values = CommitLogFilterValues()
    narrow = AuthoritativeCommitSnapshot(scope, narrow_values, 0, _result())
    broad = AuthoritativeCommitSnapshot(scope, broad_values, 0, _result_with_sidecar())

    assert snapshot_covers(narrow, narrow_values) is True
    assert snapshot_covers(narrow, broad_values) is False
    assert snapshot_covers(broad, narrow_values) is True


def test_show_merges_snapshot_covers_every_merge_visibility_mode() -> None:
    scope = (None, True)
    hide_values = CommitLogFilterValues(merges="hide")
    show_values = CommitLogFilterValues(merges="show")
    only_values = CommitLogFilterValues(merges="only")
    author_show_values = CommitLogFilterValues(authors=("Ada",), merges="show")
    author_only_values = CommitLogFilterValues(authors=("Ada",), merges="only")
    hide_snapshot = AuthoritativeCommitSnapshot(scope, hide_values, 0, _result())
    show_snapshot = AuthoritativeCommitSnapshot(scope, show_values, 0, _result())
    only_snapshot = AuthoritativeCommitSnapshot(scope, only_values, 0, _result())
    author_show_snapshot = AuthoritativeCommitSnapshot(
        scope,
        author_show_values,
        0,
        _result(),
    )

    assert snapshot_covers(show_snapshot, hide_values) is True
    assert snapshot_covers(show_snapshot, show_values) is True
    assert snapshot_covers(show_snapshot, only_values) is True
    assert snapshot_covers(author_show_snapshot, author_only_values) is True
    assert snapshot_covers(hide_snapshot, show_values) is False
    assert snapshot_covers(hide_snapshot, only_values) is False
    assert snapshot_covers(only_snapshot, hide_values) is False


def test_snapshot_coverage_trusts_truncation_metadata_not_row_count() -> None:
    scope = (None, True)
    values = CommitLogFilterValues()
    complete_result = AuthoritativeCommitSnapshot(
        scope,
        values,
        0,
        _result_with_commit_count(40),
    )
    provider_capped = replace(
        complete_result,
        result=replace(
            complete_result.result,
            provider_truncation_possible=True,
        ),
    )
    aggregate_capped = replace(
        complete_result,
        result=replace(
            complete_result.result,
            aggregate_truncated=True,
        ),
    )

    assert snapshot_covers(complete_result, values) is True
    assert snapshot_covers(provider_capped, values) is False
    assert snapshot_covers(aggregate_capped, values) is False


@pytest.mark.parametrize(
    ("result", "expected_count", "capped"),
    (
        (_result_with_commit_count(2), 2, False),
        (
            _result_with_commit_count(2, provider_truncation_possible=True),
            2,
            True,
        ),
        (_result_with_commit_count(2, aggregate_truncated=True), 2, True),
        (_result_with_commit_count(41), 41, False),
    ),
    ids=("exact", "provider-cap", "aggregate-cap", "above-old-default-cap"),
)
async def test_unlimited_commits_status_follows_backend_coverage_without_a_query_cap(
    monkeypatch: pytest.MonkeyPatch,
    result: VcsLogResult,
    expected_count: int,
    capped: bool,
) -> None:
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "stitches": {"default_query": "sidecar:false since:24h limit:all"}
                }
            }
        },
    )
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("stitches"))
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        bar = pane.query_one(CommitFilterBar)
        status = bar.query_one("#commit-filter-status", Static)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and len(pane.result.commits) == expected_count
                and ("capped" in status.content.plain) is capped
            )
        )

        coverage = "capped" if capped else "exact"
        marker = "+" if capped else ""
        assert status.content.plain == coverage
        assert pane.query_one("#stitches-position", Static).content.plain == (
            f"[1/{expected_count}{marker}]  ·  "
        )
        assert "limit:" not in editor.text
        assert "limit:" not in pane._build_info().plain
        assert not any(chip.startswith("limit:") for chip in pane._filter_chips())


async def test_explicit_limit_truncates_and_remains_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result_with_commit_count(41)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "stitches": {"default_query": "sidecar:false since:24h limit:40"}
                }
            }
        },
    )
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("stitches"))
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        bar = pane.query_one(CommitFilterBar)
        status = bar.query_one("#commit-filter-status", Static)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and len(pane.result.commits) == 40
                and "capped" in status.content.plain
            )
        )

        assert calls[0]["limit"] == 40
        assert status.content.plain == "capped"
        assert pane.query_one("#stitches-position", Static).content.plain == (
            "[1/40+]  ·  "
        )
        assert editor.text == "sidecar:false merges:hide since:24h limit:40"
        assert "limit:40" in pane._build_info().plain
        assert "limit:40" in pane._filter_chips()


async def test_type_filter_uses_uncapped_backend_candidates_before_host_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "stitches": {"default_query": "sidecar:false type:manual limit:1"}
                }
            }
        },
    )
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("stitches"))
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        bar = pane.query_one(CommitFilterBar)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and [entry.commit.short_id for entry in pane.result.commits]
                == ["bbbbbbb"]
            )
        )

        assert calls[0]["limit"] == 0
        assert editor.text == "type:manual sidecar:false merges:hide limit:1"


def test_relative_filter_reparse_reuses_snapshot_cache_key() -> None:
    tz = get_timezone()
    first_now = datetime(2026, 7, 18, 12, 0, tzinfo=tz)
    first = parse_commit_filter_query("sidecar:false since:24h", now=first_now)
    reparsed = parse_commit_filter_query(
        "sidecar:false since:24h",
        now=first_now + timedelta(hours=3),
    )
    scope = (None, True)
    result = _result()
    snapshot = AuthoritativeCommitSnapshot(scope, first, 0, result)
    cache = {(scope, first): result}

    assert snapshot_covers(snapshot, reparsed) is True
    assert cache[(scope, reparsed)] is result


async def test_unchanged_relative_query_reuses_cache_and_refreshes_its_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tz = get_timezone()
    initial_now = datetime(2026, 7, 21, 12, 0, tzinfo=tz)
    clock = [initial_now]
    base = _result_with_commit_count(2, timestamp=int(initial_now.timestamp()))
    recent, aging = base.commits
    aging = replace(
        aging,
        commit=replace(
            aging.commit,
            timestamp=int((initial_now - timedelta(hours=23)).timestamp()),
        ),
    )
    raw = replace(base, commits=(recent, aging))
    calls: list[dict[str, Any]] = []
    resolved_windows: list[tuple[int | None, int | None]] = []

    def collect(**kwargs: Any) -> VcsLogResult:
        calls.append(kwargs)
        filter_spec = kwargs["filter_spec"]
        resolved = filter_spec.resolve(now=clock[0])
        resolved_windows.append((resolved.since, resolved.until))
        commits = tuple(
            entry
            for entry in raw.commits
            if resolved.since is None or entry.commit.timestamp >= resolved.since
        )
        return replace(
            raw,
            commits=commits,
            resolved_filters=resolved,
            filter_spec=filter_spec,
        )

    monkeypatch.setattr(commits_module, "run_vcs_log", collect)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")
    monkeypatch.setattr(
        "sase.ace.query.profile_reference_support.normalize_reference_time",
        lambda: clock[0],
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("stitches"))
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(
            lambda _state: (
                len(calls) == 1
                and pane.result is not None
                and len(pane.result.commits) == 2
            )
        )
        values = pane.filters
        generation = pane._generation
        cache_key = (pane._scope_key(), values)
        assert cache_key in pane._authoritative_results

        clock[0] = initial_now + timedelta(hours=2)
        await page.press("slash")
        await page.wait_for(
            lambda _state: pane.result is not None and len(pane.result.commits) == 1
        )
        assert len(calls) == 1
        assert pane._generation == generation
        assert pane.filters == values
        assert cache_key in pane._authoritative_results

        await page.press("escape", "escape")
        await page.wait_for(
            lambda _state: pane.result is not None and len(pane.result.commits) == 2
        )
        assert len(calls) == 1
        assert pane._generation == generation

        await page.press("slash", "enter")
        await page.wait_for(
            lambda _state: (
                page.app.focused
                is pane.query_one("#stitches-timeline", CommitsTimeline)
            )
        )
        assert len(calls) == 1
        assert pane._generation == generation
        assert pane.filters == values

        await page.press("R")
        await page.wait_for(
            lambda _state: (
                len(calls) == 2
                and pane.result is not None
                and len(pane.result.commits) == 1
            )
        )
        assert calls[0]["filter_spec"] == calls[1]["filter_spec"]
        assert resolved_windows[1][0] is not None
        assert resolved_windows[0][0] is not None
        assert resolved_windows[1][0] > resolved_windows[0][0]


async def test_sidecar_filter_and_compatibility_toggle_share_collection_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broad = _result_with_sidecar()
    sidecar_names = {repo.name for repo in broad.repos if repo.kind == "sidecar"}
    narrow = replace(
        broad,
        repos=tuple(repo for repo in broad.repos if repo.kind != "sidecar"),
        commits=tuple(
            entry for entry in broad.commits if entry.repo not in sidecar_names
        ),
        remote_states=tuple(
            state for state in broad.remote_states if state.name not in sidecar_names
        ),
    )
    calls: list[dict[str, Any]] = []

    def collect(**kwargs: Any) -> VcsLogResult:
        calls.append(kwargs)
        return broad if kwargs["include_sidecars"] else narrow

    monkeypatch.setattr(commits_module, "run_vcs_log", collect)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("stitches"))
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is narrow)
        assert calls[-1]["include_sidecars"] is False
        assert all(repo.kind != "sidecar" for repo in pane.result.repos)

        bar = pane.query_one(CommitFilterBar)
        await page.press("slash")
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        editor.load_text("sidecar:true")
        editor.cursor_position = len(editor.text)
        await page.wait_for(
            lambda _state: (
                pane.filters.sidecar
                and pane.result is not None
                and any(repo.kind == "sidecar" for repo in pane.result.repos)
            )
        )
        await page.press("enter")
        await page.wait_for(
            lambda _state: (
                page.app.focused
                is pane.query_one("#stitches-timeline", CommitsTimeline)
            )
        )
        assert bar.display is True
        assert calls[-1]["include_sidecars"] is True
        assert "sidecar:true" in pane._filter_chips()

        await page.press("j")
        await page.wait_for(lambda _state: pane._selected_entry() is not None)
        selected_sha = pane._selected_entry().commit.full_id  # type: ignore[union-attr]

        await page.press("d")
        await page.wait_for(
            lambda _state: (
                not pane.filters.sidecar
                and pane.result is not None
                and all(repo.kind != "sidecar" for repo in pane.result.repos)
            )
        )
        assert pane._selected_entry() is not None
        assert pane._selected_entry().commit.full_id == selected_sha
        assert "sidecar:false" in pane._filter_chips()
        assert editor.text == "sidecar:false merges:hide"

        await page.press("slash")
        editor.load_text("repo:plans sidecar:false")
        editor.cursor_position = len(editor.text)
        await page.wait_for(
            lambda _state: (
                pane.filters.repos == ("plans",)
                and pane.result is not None
                and pane.result.commits == ()
                and calls[-1]["include_sidecars"] is False
            )
        )
        editor.load_text("repo:plans sidecar:true")
        editor.cursor_position = len(editor.text)
        await page.wait_for(
            lambda _state: (
                pane.filters.sidecar
                and pane.result is not None
                and [entry.repo for entry in pane.result.commits] == ["plans"]
                and calls[-1]["include_sidecars"] is True
            )
        )
