"""Interaction and keymap coverage for the Artifacts Stitches pane."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.modals.help_modal import HelpModal
from sase.ace.tui.widgets.artifacts import CommitsPane, CommitsTimeline
from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.vcs_log.models import VcsLogResult
from tests.ace.tui._commits_pane_helpers import (
    _DIFF,
    _rendered_text,
    _result,
)


async def test_commits_pilot_drives_live_filter_bar_detail_copy_and_toggles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    calls: list[dict[str, Any]] = []
    collector_threads: list[int] = []
    diff_calls: list[str] = []
    copied: list[str] = []
    event_loop_thread = threading.get_ident()

    def collect(**kwargs: Any) -> VcsLogResult:
        collector_threads.append(threading.get_ident())
        calls.append(kwargs)
        return result

    def load_diff(spec: Any) -> str:
        diff_calls.append(spec.sha)
        return _DIFF

    monkeypatch.setattr(commits_module, "run_vcs_log", collect)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", load_diff)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press("1")
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await page.wait_for(lambda _state: bool(diff_calls))
        detail = pane.query_one("#stitches-detail", Static)
        footer = pane.query_one("#stitches-footer", Static)
        info = pane._build_info().plain
        assert "Sidecars hidden" not in info
        assert "Sidecars included" not in info
        assert "sidecar:" not in info
        assert footer.content.plain == (
            "j/k navigate  ·  enter view  ·  y copy  ·  / filter  ·  d sidecars  ·  "
            "s merges  ·  a all  ·  F fetch  ·  R refresh  ·  p project"
        )
        await page.wait_for(lambda _state: "Changes:" in _rendered_text(detail.content))
        assert "feat(artifacts): keep every commit" in _rendered_text(detail.content)
        position = pane.query_one("#stitches-position", Static)
        assert position.content.plain == "[1/2]  ·  "

        assert calls[0]["no_fetch"] is True
        assert calls[0]["force_fetch"] is False
        assert calls[0]["include_sidecars"] is False
        assert calls[0]["filter_spec"].since is not None
        assert calls[0]["limit"] == 0

        await page.press("j")
        await page.wait_for(lambda _state: pane._selected_commit_index == 1)
        assert position.content.plain == "[2/2]  ·  "
        await page.press("y")
        assert copied == ["b" * 40]

        bar = pane.query_one(CommitFilterBar)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        assert bar.display is True
        assert editor.read_only is True
        assert editor.text == "sidecar:false merges:hide since:24h"
        baseline_calls = len(calls)
        await page.press("slash")
        await page.wait_for(lambda _state: page.app.focused is editor)
        assert editor.read_only is False
        assert editor.text == "sidecar:false merges:hide since:24h"
        assert page.app.focused is editor

        await page.press("ctrl+u", "f", "i", "x")
        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and [entry.commit.short_id for entry in pane.result.commits]
                == ["bbbbbbb"]
            )
        )
        assert position.content.plain == "[1/1]  ·  "
        assert page.app.focused is editor
        await page.wait_for(
            lambda _state: (
                pane.filters.text == ("fix",)
                and (pane._scope_key(), pane.filters) in pane._authoritative_results
            )
        )
        assert position.content.plain == "[1/1]  ·  "
        # Under full-suite load the live preview can collect an intermediate
        # state while the editor is processing the clear-then-type sequence.
        assert len(calls) >= baseline_calls + 1
        assert calls[baseline_calls]["limit"] == 0
        assert calls[baseline_calls]["include_sidecars"] is True
        assert all(thread_id != event_loop_thread for thread_id in collector_threads)

        await page.press("enter")
        await page.wait_for(
            lambda _state: (
                page.app.focused
                is pane.query_one("#stitches-timeline", CommitsTimeline)
            )
        )
        assert bar.display is True
        assert editor.read_only is True
        assert page.app.focused is pane.query_one("#stitches-timeline", CommitsTimeline)
        assert pane.filters.text == ("fix",)
        assert editor.text == "sidecar:true merges:hide fix"
        assert [entry.commit.short_id for entry in pane.result.commits] == ["bbbbbbb"]
        reconciled_calls = len(calls)
        await page.pause()
        assert len(calls) == reconciled_calls

        # The legacy `f` action opens the same inline bar. Escape restores the
        # pre-open values and cached authoritative result after a live preview.
        await page.press("f")
        await page.wait_for(lambda _state: page.app.focused is editor)
        assert editor.text == "sidecar:true merges:hide fix"
        await page.press("ctrl+u", "f", "e", "a", "t")
        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and [entry.commit.short_id for entry in pane.result.commits]
                == ["aaaaaaa"]
            )
        )
        assert position.content.plain == "[1/1]  ·  "
        await page.press("escape")
        await page.wait_for(
            lambda _state: (
                page.app.focused
                is pane.query_one("#stitches-timeline", CommitsTimeline)
            )
        )
        assert bar.display is True
        assert pane.filters.text == ("fix",)
        assert editor.text == "sidecar:true merges:hide fix"
        assert [entry.commit.short_id for entry in pane.result.commits] == ["bbbbbbb"]
        assert position.content.plain == "[1/1]  ·  "

        await page.press("enter")
        await page.expect_modal("CommitViewModal")
        assert isinstance(page.app.screen, CommitViewModal)
        await page.press("q")
        await page.expect_no_modal()

        await page.press("d")
        await page.wait_for(lambda _state: calls[-1]["include_sidecars"] is False)
        assert pane.filters.sidecar is False
        assert editor.text == "sidecar:false merges:hide fix"
        assert "sidecar:" not in pane._build_info().plain

        # With no automatic or picked project, `a` cannot invent hidden cwd
        # scope and leaves the visible all-project query unchanged.
        calls_before_unknown_toggle = len(calls)
        await page.press("a")
        await page.pause()
        assert len(calls) == calls_before_unknown_toggle
        assert pane.filters.project is None

        pane.set_project_scope(
            "gh_acme__widgets",
            display_name="widgets",
            project_file="/tmp/widgets.sase",
        )
        await page.wait_for(
            lambda _state: (
                calls[-1]["project_scope"] == "widgets"
                and calls[-1]["all_projects"] is False
            )
        )
        assert editor.text == "project:widgets sidecar:false merges:hide fix"

        await page.press("a")
        await page.wait_for(lambda _state: pane.filters.project is None)
        assert any(call["all_projects"] is True for call in calls)
        assert editor.text == "sidecar:false merges:hide fix"

        await page.press("a")
        await page.wait_for(lambda _state: pane.filters.project == "widgets")
        assert editor.text == "project:widgets sidecar:false merges:hide fix"

        refresh_baseline = len(calls)
        await page.press("R")
        await page.wait_for(lambda _state: len(calls) == refresh_baseline + 1)
        await page.press("F")
        await page.wait_for(
            lambda _state: any(call["force_fetch"] is True for call in calls)
        )

        # Slash remains inert on Beads rather than opening the commit bar or
        # historical PR query modal. Plans owns its own filter-bar route.
        await page.press("3")
        await page.expect_state("artifacts_subtab", "beads")
        await page.press("slash")
        await page.pause()
        assert bar.display is True
        assert page.app.focused is not editor
        assert page.state["modal"] is None


async def test_commits_refresh_override_drives_action_footer_and_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"ace": {"keymaps": {"app": {"commits_refresh": "f2"}}}},
    )
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)

    async with AcePage(initial_tab="patches") as page:
        await page.press("1")
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)

        footer = pane.query_one("#stitches-footer", Static)
        assert "f2 refresh" in footer.content.plain
        assert "R refresh" not in footer.content.plain

        baseline = len(calls)
        await page.press("R")
        await page.pause()
        assert len(calls) == baseline

        await page.press("f2")
        await page.wait_for(lambda _state: len(calls) == baseline + 1)

        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = page.app.screen
        assert isinstance(modal, HelpModal)
        help_text = modal._build_left_column().plain
        assert "F / f2" in help_text
        assert "sidecar:true" in help_text
        assert "merges:hide" in help_text
        assert "Cycle merge visibility" in help_text
        assert "project:NAME" in help_text
        assert "Single; omitted = all projects" in help_text
        assert "Sidecars / project: off/on" in help_text
        assert "until:DAY includes the full day" in help_text
        assert "[P/N] / [P/N+]" in help_text


async def test_commit_fetch_task_uses_visible_project_name_and_matching_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    submissions: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        pane.set_project_scope(
            "gh_acme__widgets",
            display_name="widgets",
            project_file="/tmp/widgets.sase",
        )
        await page.wait_for(lambda _state: pane.filters.project == "widgets")
        monkeypatch.setattr(
            page.app,
            "_submit_tracked_proc",
            lambda *args, **kwargs: submissions.append((args, kwargs)),
        )

        pane.fetch_commits()

        assert len(submissions) == 1
        args, kwargs = submissions[0]
        assert args[:3] == (
            "commit-fetch",
            "commits:widgets",
            "/tmp/widgets.sase",
        )
        assert kwargs["display_name"] == "Fetch commits (widgets)"
        assert kwargs["dedup_key"] == "commit-fetch:widgets"
        assert "gh_acme__widgets" not in kwargs["duplicate_message"]


async def test_commits_cycle_merges_updates_query_and_recollects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: calls.append(kwargs) or result,
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)

    async with AcePage(initial_tab="patches") as page:
        await page.press("1")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        bar = pane.query_one(CommitFilterBar)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)

        await page.press("s")
        await page.wait_for(
            lambda _state: (
                pane.filters.merges == "show"
                and calls[-1]["filter_spec"].merges == "show"
            )
        )
        assert editor.text == "sidecar:false merges:show since:24h"

        await page.press("s")
        await page.wait_for(
            lambda _state: (
                pane.filters.merges == "only"
                and calls[-1]["filter_spec"].merges == "only"
            )
        )
        assert editor.text == "sidecar:false merges:only since:24h"

        await page.press("s")
        await page.wait_for(lambda _state: pane.filters.merges == "hide")
        assert editor.text == "sidecar:false merges:hide since:24h"
