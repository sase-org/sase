"""Behavior and renderer coverage for the Artifacts Commits pane."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from typing import Any

import pytest
from rich.console import Console
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.commit_filters_modal import CommitFiltersModal
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.modals.help_modal import HelpModal
from sase.ace.tui.widgets.artifacts import CommitsPane, CommitsTimeline
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.vcs_log.models import LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log.render import build_pretty_legend


_DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 old
+new
"""


def _rendered_text(renderable: Any) -> str:
    stream = StringIO()
    Console(file=stream, color_system=None, width=120).print(renderable)
    return stream.getvalue()


def _result(timestamp: int | None = None) -> VcsLogResult:
    now = timestamp or int(datetime.now(tz=UTC).timestamp())
    commits = (
        AggregatedCommitWire(
            "alpha",
            VcsCommitWire(
                full_id="a" * 40,
                short_id="aaaaaaa",
                author_name="Ada Lovelace",
                author_email="ada@example.com",
                timestamp=now,
                subject="feat: interactive timeline",
                body=(
                    "Render a rich commit detail.\n\nSASE_AGENT=sase-69.3\nSASE_BUG=42"
                ),
                presence="local_only",
            ),
        ),
        AggregatedCommitWire(
            "sase-core",
            VcsCommitWire(
                full_id="b" * 40,
                short_id="bbbbbbb",
                author_name="Grace Hopper",
                author_email="grace@example.com",
                timestamp=now - 60,
                subject="fix: preserve selection",
                body="Keep the highlighted SHA across refreshes.",
                presence="remote_only",
            ),
        ),
    )
    return VcsLogResult(
        repos=(
            LogRepo("alpha", "/tmp/alpha", "primary"),
            LogRepo("sase-core", "/tmp/core", "linked"),
        ),
        commits=commits,
        warnings=(),
        remote_states=(
            RepoRemoteState("alpha", "origin/main", 1, 0, False, 1.0),
            RepoRemoteState("sase-core", "origin/main", 0, 1, True, 1.0),
        ),
    )


def test_commits_renderer_builds_legend_headers_rows_and_tag_chips() -> None:
    result = _result()

    legend = build_pretty_legend(result)
    timeline = CommitsTimeline()
    selected = timeline.update_result(result)

    assert "alpha (1)" in legend.plain
    assert "↑1 ↓0" in legend.plain
    assert "↑ unpushed" in legend.plain
    assert selected == 0
    assert timeline.option_count == 3  # one day banner + two commit rows
    first = timeline.get_option_at_index(1).prompt
    assert "aaaaaaa" in first.plain
    assert "@sase-69.3" in first.plain
    assert "#42" in first.plain
    assert "Ada Lovelace" in first.plain


async def test_commits_pilot_drives_filters_detail_copy_modal_and_toggles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    calls: list[dict[str, Any]] = []
    diff_calls: list[str] = []
    copied: list[str] = []

    def collect(**kwargs: Any) -> VcsLogResult:
        calls.append(kwargs)
        return result

    def load_diff(spec: Any) -> str:
        diff_calls.append(spec.sha)
        return _DIFF

    monkeypatch.setattr(commits_module, "run_vcs_log", collect)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", load_diff)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await page.wait_for(lambda _state: bool(diff_calls))
        detail = pane.query_one("#commits-detail", Static)
        footer = pane.query_one("#commits-footer", Static)
        assert footer.content.plain == (
            "j/k navigate  enter view  y copy  f filters  d SDD  "
            "a all  F fetch  R refresh  p project"
        )
        await page.wait_for(lambda _state: "Changes:" in _rendered_text(detail.content))
        assert "feat: interactive timeline" in _rendered_text(detail.content)

        assert calls[0]["no_fetch"] is True
        assert calls[0]["force_fetch"] is False

        await page.press("j")
        await page.wait_for(lambda _state: pane._selected_commit_index == 1)
        await page.press("y")
        assert copied == ["b" * 40]

        await page.press("f")
        await page.expect_modal("CommitFiltersModal")
        modal = page.app.screen
        assert isinstance(modal, CommitFiltersModal)
        modal.query_one("#commit-filter-authors", Input).value = "Grace"
        modal.query_one("#commit-filter-limit", Input).value = "5"
        modal.action_apply()
        await page.expect_no_modal()
        await page.wait_for(
            lambda _state: any(
                call["limit"] == 5 and call["filters"].authors == ("Grace",)
                for call in calls
            )
        )

        await page.press("enter")
        await page.expect_modal("CommitViewModal")
        assert isinstance(page.app.screen, CommitViewModal)
        await page.press("q")
        await page.expect_no_modal()

        await page.press("d")
        await page.wait_for(
            lambda _state: any(call["include_sdd"] is True for call in calls)
        )
        await page.press("a")
        await page.wait_for(
            lambda _state: any(call["all_projects"] is True for call in calls)
        )
        await page.press("R")
        await page.wait_for(lambda _state: len(calls) >= 5)
        await page.press("F")
        await page.wait_for(
            lambda _state: any(call["force_fetch"] is True for call in calls)
        )


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

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)

        footer = pane.query_one("#commits-footer", Static)
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
        assert "F / f2" in modal._build_left_column().plain
