"""Behavior and renderer coverage for the Artifacts Commits pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
import threading
from typing import Any

import pytest
from rich.console import Console
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.modals.help_modal import HelpModal
from sase.ace.tui.util.lazy_syntax import (
    PLAIN_RENDER_MAX_BYTES,
    LazySyntaxRenderCache,
)
from sase.ace.tui.widgets.artifacts import CommitsPane, CommitsTimeline
from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.artifacts.commits_collection import (
    AuthoritativeCommitSnapshot,
    snapshot_covers,
)
from sase.ace.tui.widgets.artifacts.commits_rendering import build_commit_detail
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.core.vcs_log_wire import (
    AggregatedCommitWire,
    CommitPresence,
    VcsCommitWire,
)
from sase.vcs_log.models import LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log.filter_query import CommitLogFilterValues
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


def _byte_heavy_diff() -> str:
    header = """diff --git a/events.jsonl b/events.jsonl
--- a/events.jsonl
+++ b/events.jsonl
@@ -1 +1 @@
"""
    return header + ("+" + "x" * 7_000 + "\n") * 500


def _result(timestamp: int | None = None) -> VcsLogResult:
    now = timestamp or int(datetime.now(tz=UTC).timestamp())
    commits = (
        AggregatedCommitWire(
            "alpha-platform-repository",
            VcsCommitWire(
                full_id="a" * 40,
                short_id="aaaaaaa",
                author_name="Ada Lovelace, Principal Analytical Engine Programmer",
                author_email="ada@example.com",
                timestamp=now,
                subject=(
                    "feat(artifacts): keep every commit timeline entry on one calm "
                    "physical row"
                ),
                body=(
                    "Render the selected commit's complete metadata without "
                    "sacrificing scan density.\n\n"
                    "SASE_TYPE=bead_work\n"
                    "SASE_AGENT=sase-69.3\n"
                    "SASE_MACHINE=athena\n"
                    "SASE_PLAN=sdd/plans/commits_single_line_timeline.md\n"
                    "SASE_BUG=42"
                ),
                presence="local_only",
            ),
        ),
        AggregatedCommitWire(
            "sase-core-foundation",
            VcsCommitWire(
                full_id="b" * 40,
                short_id="bbbbbbb",
                author_name="Rear Admiral Grace Murray Hopper",
                author_email="grace@example.com",
                timestamp=now - 60,
                subject=(
                    "fix(artifacts): preserve the selected commit identity across "
                    "timeline refreshes"
                ),
                body="Keep the highlighted SHA across refreshes.",
                presence="remote_only",
            ),
        ),
    )
    return VcsLogResult(
        repos=(
            LogRepo("alpha-platform-repository", "/tmp/alpha", "primary"),
            LogRepo("sase-core-foundation", "/tmp/core", "linked"),
        ),
        commits=commits,
        warnings=(),
        remote_states=(
            RepoRemoteState(
                "alpha-platform-repository", "origin/main", 1, 0, False, 1.0
            ),
            RepoRemoteState("sase-core-foundation", "origin/main", 0, 1, True, 1.0),
        ),
    )


def _result_with_sidecar(timestamp: int | None = None) -> VcsLogResult:
    base = _result(timestamp)
    now = timestamp or int(datetime.now(tz=UTC).timestamp())
    sidecar = AggregatedCommitWire(
        "plans",
        VcsCommitWire(
            full_id="c" * 40,
            short_id="ccccccc",
            author_name="Plan Curator",
            author_email="plans@example.com",
            timestamp=now - 120,
            subject="docs(plans): record the approved sidecar rollout",
            body="Keep plans history available through sidecar:true.",
            presence="synced",
        ),
    )
    return replace(
        base,
        repos=(*base.repos, LogRepo("plans", "/tmp/plans", "sidecar")),
        commits=(sidecar, *base.commits),
        remote_states=(
            *base.remote_states,
            RepoRemoteState("plans", "origin/main", 0, 0, True, 1.0),
        ),
    )


def test_commits_renderer_builds_compact_single_line_rows() -> None:
    result = _result()

    legend = build_pretty_legend(result)
    timeline = CommitsTimeline()
    selected = timeline.update_result(result)

    assert "alpha-platform-repository (1)" in legend.plain
    assert "↑1 ↓0" in legend.plain
    assert "↑ unpushed" in legend.plain
    assert selected == 0
    assert timeline.option_count == 3  # one day banner + two commit rows
    first = timeline.get_option_at_index(1).prompt
    assert "aaaaaaa" in first.plain
    assert "alpha-platform-repository" in first.plain
    assert "feat(artifacts): keep every commit" in first.plain
    assert "@sase-69.3" not in first.plain
    assert "#42" not in first.plain
    assert "Ada Lovelace" not in first.plain
    assert "\n" not in first.plain
    assert first.no_wrap is True
    assert first.overflow == "ellipsis"


@pytest.mark.parametrize(
    ("presence", "indicator"),
    (
        ("local_only", "↑ unpushed"),
        ("remote_only", "↓ GitHub-only"),
        ("synced", "● synced"),
        ("unknown", "· unknown"),
    ),
)
def test_commit_detail_preserves_full_metadata_for_every_presence(
    presence: CommitPresence,
    indicator: str,
) -> None:
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result(timestamp)
    original = result.commits[0]
    entry = replace(
        original,
        commit=replace(original.commit, presence=presence),
    )

    detail = build_commit_detail(
        entry,
        _DIFF,
        loading=False,
        result=result,
        render_cache=LazySyntaxRenderCache(),
    )
    text = _rendered_text(detail)

    assert "alpha-platform-repository  aaaaaaa" in text
    assert "Ada Lovelace, Principal Analytical Engine Programmer" in text
    assert "Monday, July 6, 2026 at 10:30:00" in text
    assert indicator in text
    assert entry.commit.subject in text
    assert "Render the selected commit's complete metadata" in text
    assert "type" in text and "bead_work" in text
    assert "agent" in text and "sase-69.3" in text
    assert "machine" in text and "athena" in text
    assert "plan" in text and "commits_single_line_timeline.md" in text
    assert "bug" in text and "42" in text
    assert "Changes:" in text
    assert "+new" in text


def test_commit_detail_omits_empty_author() -> None:
    result = _result()
    original = result.commits[0]
    entry = replace(
        original,
        commit=replace(original.commit, author_name=""),
    )

    detail = build_commit_detail(
        entry,
        None,
        loading=False,
        result=result,
        render_cache=LazySyntaxRenderCache(),
    )

    assert "Author" not in _rendered_text(detail)


def test_commit_detail_bounds_byte_heavy_diff_and_explains_truncation() -> None:
    result = _result()
    entry = result.commits[0]

    detail = build_commit_detail(
        entry,
        _byte_heavy_diff(),
        loading=False,
        result=result,
        render_cache=LazySyntaxRenderCache(),
    )
    text = _rendered_text(detail)

    assert len(text.encode("utf-8")) <= PLAIN_RENDER_MAX_BYTES + 20_000
    assert "approximately" in text
    assert "run git show aaaaaaa in alpha-platform-repository" in text


async def test_commits_timeline_mounted_rows_stay_one_line_with_jump_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="changespecs", size=(80, 30)) as page:
        await page.press("]")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        timeline = pane.query_one("#commits-timeline", CommitsTimeline)

        def assert_one_line_contract() -> None:
            timeline._line_cache.clear()
            timeline._update_lines()
            commit_indexes = [
                index
                for index, option in enumerate(timeline.options)
                if option.id is not None
                and option.id.startswith("commit-")
                and not option.id.startswith("commit-day-")
            ]
            assert timeline.styles.text_wrap == "nowrap"
            assert timeline.styles.text_overflow == "ellipsis"
            assert commit_indexes
            assert all(
                timeline._line_cache.heights[index] == 1 for index in commit_indexes
            )
            assert all(
                timeline.get_option_at_index(index).prompt.no_wrap is True
                and timeline.get_option_at_index(index).prompt.overflow == "ellipsis"
                for index in commit_indexes
            )
            assert all(
                option.disabled
                for option in timeline.options
                if option.id is not None and option.id.startswith("commit-day-")
            )

        assert_one_line_contract()
        target = pane.entry_targets()[1]
        assert pane.select_entry_target(target) is True
        selected_target = pane.selected_entry_target()
        pane.apply_entry_jump_hints(
            {
                entry_target: str(index + 1)
                for index, entry_target in enumerate(pane.entry_targets())
            }
        )
        assert pane.selected_entry_target() == selected_target
        assert timeline.get_option_at_index(1).prompt.plain.startswith("[1] ")
        assert_one_line_contract()


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
        assert (
            "Sidecars hidden" in pane.query_one("#commits-info", Static).content.plain
        )
        assert footer.content.plain == (
            "j/k navigate  enter view  y copy  / filter  d sidecars  "
            "a all  F fetch  R refresh  p project"
        )
        await page.wait_for(lambda _state: "Changes:" in _rendered_text(detail.content))
        assert "feat(artifacts): keep every commit" in _rendered_text(detail.content)

        assert calls[0]["no_fetch"] is True
        assert calls[0]["force_fetch"] is False

        await page.press("j")
        await page.wait_for(lambda _state: pane._selected_commit_index == 1)
        await page.press("y")
        assert copied == ["b" * 40]

        bar = pane.query_one(CommitFilterBar)
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        baseline_calls = len(calls)
        await page.press("slash")
        await page.wait_for(lambda _state: bar.display)
        assert editor.text == ""
        assert page.app.focused is editor

        await page.press("f", "i", "x")
        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and [entry.commit.short_id for entry in pane.result.commits]
                == ["bbbbbbb"]
            )
        )
        assert page.app.focused is editor
        await page.wait_for(
            lambda _state: (
                pane.filters.text == ("fix",)
                and (pane._scope_key(), pane.filters) in pane._authoritative_results
            )
        )
        assert len(calls) == baseline_calls + 1
        assert calls[baseline_calls]["limit"] == 0
        assert all(thread_id != event_loop_thread for thread_id in collector_threads)

        await page.press("enter")
        await page.wait_for(lambda _state: not bar.display)
        assert page.app.focused is pane.query_one("#commits-timeline", CommitsTimeline)
        assert pane.filters.text == ("fix",)
        assert [entry.commit.short_id for entry in pane.result.commits] == ["bbbbbbb"]
        reconciled_calls = len(calls)
        await page.pause()
        assert len(calls) == reconciled_calls

        # The legacy `f` action opens the same inline bar. Escape restores the
        # pre-open values and cached authoritative result after a live preview.
        await page.press("f")
        await page.wait_for(lambda _state: bar.display)
        assert editor.text == "fix"
        await page.press("ctrl+u", "f", "e", "a", "t")
        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and [entry.commit.short_id for entry in pane.result.commits]
                == ["aaaaaaa"]
            )
        )
        await page.press("escape")
        await page.wait_for(lambda _state: not bar.display)
        assert pane.filters.text == ("fix",)
        assert [entry.commit.short_id for entry in pane.result.commits] == ["bbbbbbb"]

        await page.press("enter")
        await page.expect_modal("CommitViewModal")
        assert isinstance(page.app.screen, CommitViewModal)
        await page.press("q")
        await page.expect_no_modal()

        await page.press("d")
        await page.wait_for(
            lambda _state: any(call["include_sidecars"] is True for call in calls)
        )
        assert pane.filters.sidecar is True
        assert "sidecar:true" in pane.query_one("#commits-info", Static).content.plain
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

        # Slash remains inert on Bugs rather than opening the commit bar or
        # historical PR query modal. Plans owns its own filter-bar route.
        await page.press("3")
        await page.expect_state("artifacts_subtab", "bugs")
        await page.press("slash")
        await page.pause()
        assert bar.display is False
        assert page.state["modal"] is None


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

        await page.press("slash", "r", "e", "p", "o")
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
        await page.wait_for(lambda _state: not bar.display)
        assert pane.filters.excluded_repos == ("sase-core-foundation",)
        assert query in pane.query_one("#commits-info", Static).content.plain

        await page.press("slash")
        editor.load_text("-author:Grace")
        editor.cursor_position = len(editor.text)
        await page.wait_for(
            lambda _state: (
                pane.filters.excluded_authors == ("Grace",) and calls[-1]["limit"] == 0
            )
        )
        await page.press("escape")
        await page.wait_for(lambda _state: not bar.display)
        assert pane.filters.excluded_repos == ("sase-core-foundation",)


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

        await page.press("comma", "question_mark")
        await page.expect_modal("HelpModal")
        modal = page.app.screen
        assert isinstance(modal, HelpModal)
        help_text = modal._build_left_column().plain
        assert "F / f2" in help_text
        assert "sidecar:true" in help_text
        assert "Toggle sidecar history" in help_text


def test_sidecar_snapshot_coverage_is_directional() -> None:
    scope = (None, False)
    narrow_values = CommitLogFilterValues()
    broad_values = CommitLogFilterValues(sidecar=True)
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
        await page.wait_for(lambda _state: not bar.display)
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
        assert "sidecar:true" not in pane._filter_chips()

        await page.press("slash")
        editor.load_text("repo:plans")
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
