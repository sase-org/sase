"""Filter and collection coverage for the Artifacts Commits pane."""

from __future__ import annotations

from dataclasses import replace
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
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.vcs_log.filter_query import CommitLogFilterValues
from sase.vcs_log.models import VcsLogResult
from tests.ace.tui._commits_pane_helpers import _result, _result_with_sidecar


async def test_custom_default_query_controls_first_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result_with_sidecar()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "commits": {"default_query": "repo:plans sidecar:true limit:5"}
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

    async with AcePage(initial_tab="changespecs") as page:
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        bar = pane.query_one(CommitFilterBar)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        assert bar.display is True
        assert editor.text == "repo:plans sidecar:true limit:5"
        assert calls == []

        await page.press("]")
        await page.wait_for(lambda _state: bool(calls) and pane.result is not None)

        assert calls[0]["repo_filters"] == ("plans",)
        assert calls[0]["include_sidecars"] is True
        assert calls[0]["limit"] == 5


async def test_commits_filter_bar_rejects_invalid_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="changespecs", notifications=True) as page:
        await page.press("]")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        bar = pane.query_one(CommitFilterBar)

        await page.press("slash", "ctrl+u", "r", "e", "p", "o")
        await page.wait_for(lambda _state: pane.filters.text == ("repo",))
        await page.press("colon", "enter")
        await page.wait_for(
            lambda _state: (
                bar.query_one("#commit-filter-status", Static).has_class("error")
                and pane.filters.text == ()
            )
        )

        assert bar.display is True
        assert bar.query_one("#commit-filter-status", Static).has_class("error")
        assert pane.filters.text == ()


async def test_commits_negative_repo_reconciles_before_collection_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("]")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        bar = pane.query_one(CommitFilterBar)
        await page.press("slash")
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        query = "-repo:sase-core-foundation"
        editor.load_text(query)
        editor.cursor_position = len(query)

        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and [repo.name for repo in pane.result.repos]
                == ["alpha-platform-repository"]
                and calls[-1].get("exclude_repo_filters") == ("sase-core-foundation",)
            )
        )
        assert calls[-1]["limit"] == 40
        assert [entry.commit.short_id for entry in pane.result.commits] == ["aaaaaaa"]
        assert "exact" in bar.query_one("#commit-filter-status", Static).content.plain

        await page.press("enter")
        await page.wait_for(
            lambda _state: (
                page.app.focused is pane.query_one("#commits-timeline", CommitsTimeline)
            )
        )
        assert bar.display is True
        assert pane.filters.excluded_repos == ("sase-core-foundation",)
        assert editor.text == f"{query} sidecar:true"
        assert query not in pane.query_one("#commits-info", Static).content.plain

        await page.press("slash")
        editor.load_text("-author:Grace")
        editor.cursor_position = len(editor.text)
        await page.wait_for(
            lambda _state: (
                pane.filters.excluded_authors == ("Grace",) and calls[-1]["limit"] == 0
            )
        )
        await page.press("escape")
        await page.wait_for(
            lambda _state: (
                page.app.focused is pane.query_one("#commits-timeline", CommitsTimeline)
            )
        )
        assert pane.filters.excluded_repos == ("sase-core-foundation",)


def test_sidecar_snapshot_coverage_is_directional() -> None:
    scope = (None, False)
    narrow_values = CommitLogFilterValues(sidecar=False)
    broad_values = CommitLogFilterValues()
    narrow = AuthoritativeCommitSnapshot(scope, narrow_values, 40, _result())
    broad = AuthoritativeCommitSnapshot(scope, broad_values, 40, _result_with_sidecar())

    assert snapshot_covers(narrow, narrow_values) is True
    assert snapshot_covers(narrow, broad_values) is False
    assert snapshot_covers(broad, narrow_values) is True


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

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("]")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
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
                page.app.focused is pane.query_one("#commits-timeline", CommitsTimeline)
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
        assert editor.text == "sidecar:false"

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
