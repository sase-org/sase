"""PNG visual coverage for the Artifacts Commits timeline and detail."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.widgets.artifacts import CommitsPane
from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.artifacts.commits_timeline import CommitsTimeline
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.vcs_log.filter_query import parse_commit_filter_query
from tests.ace.tui.test_commits_pane import _DIFF, _result
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _open_commits(
    page: AcePage,
    result: commits_module.VcsLogResult,
) -> tuple[CommitsPane, CommitFilterBar]:
    await wait_for_startup(page)
    await page.press("]")
    await page.expect_state("artifacts_subtab", "commits")
    pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
    await page.wait_for(lambda _state: pane.result is result)
    return pane, pane.query_one(CommitFilterBar)


async def _commit_filter_query(
    page: AcePage,
    pane: CommitsPane,
    bar: CommitFilterBar,
    query: str,
) -> None:
    values = parse_commit_filter_query(query)
    await page.press("slash")
    await page.wait_for(lambda _state: bar.display)
    bar.query_one("#commit-filter-input", SingleLineVimTextArea).load_text(query)
    await page.wait_for(
        lambda _state: (
            pane.filters == values
            and (pane._scope_key(), values) in pane._authoritative_results
        )
    )
    await page.press("enter")
    await page.wait_for(lambda _state: not bar.display)


async def test_commits_timeline_and_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result(timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(
        commits_module,
        "load_commit_diff_text",
        lambda _spec: _DIFF,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: _ArtifactsProjectChoices((), (), {}),
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await wait_for_svg_contains(page, "feat(artifacts): keep every commit")
        await wait_for_svg_contains(page, "Changes:")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_timeline_detail_120x40",
            title="ACE Artifacts Commits timeline",
        )


async def test_commits_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    result = commits_module.VcsLogResult((), (), ())
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: _ArtifactsProjectChoices((), (), {}),
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await wait_for_svg_contains(page, "No commits match")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_empty_120x40",
            title="ACE Artifacts Commits empty",
        )


async def test_commits_jump_hints_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result(timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(
        commits_module,
        "load_commit_diff_text",
        lambda _spec: _DIFF,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: _ArtifactsProjectChoices((), (), {}),
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await wait_for_svg_contains(page, "feat(artifacts): keep every commit")
        await page.press("apostrophe")
        await wait_for_svg_contains(page, "JUMP")
        await wait_for_svg_contains(page, "[0]")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_jump_hints_120x40",
            title="ACE Artifacts Commits jump hints",
        )


async def test_commits_filter_bar_prefilled_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result(timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        pane, bar = await _open_commits(page, result)
        query = "repo:alpha-platform-repository feat"
        await _commit_filter_query(page, pane, bar, query)
        await page.press("slash")
        await page.wait_for(
            lambda _state: (
                bar.display
                and bar.query_one("#commit-filter-input", SingleLineVimTextArea).text
                == query
            )
        )
        await wait_for_svg_contains(page, "1 match")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_filter_bar_prefilled_120x40",
            title="ACE Artifacts Commits prefilled filter bar",
        )


async def test_commits_filter_completion_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result(timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        pane, bar = await _open_commits(page, result)
        pane.show_filters()
        bar.open("repo:")
        completion = bar.query_one("#commit-filter-completion", OptionList)
        await page.wait_for(
            lambda _state: completion.display and completion.option_count == 2
        )
        await wait_for_svg_contains(page, "repository")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_filter_completion_120x40",
            title="ACE Artifacts Commits repository completion",
        )


async def test_commits_narrowed_filter_chips_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result(timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        pane, bar = await _open_commits(page, result)
        query = (
            "repo:sase-core-foundation -repo:alpha-platform-repository "
            "author:Grace limit:all fix"
        )
        await _commit_filter_query(page, pane, bar, query)
        await page.wait_for(
            lambda _state: (
                pane.result is not None
                and [entry.commit.short_id for entry in pane.result.commits]
                == ["bbbbbbb"]
                and pane.query_one("#commits-timeline", CommitsTimeline).has_focus
            )
        )
        await wait_for_svg_contains(page, "repo:sase-core-foundation")
        await wait_for_svg_contains(page, "fix(artifacts): preserve")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_narrowed_filter_chips_120x40",
            title="ACE Artifacts Commits narrowed filter chips",
        )


async def test_commits_filter_parse_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result(timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        _pane, bar = await _open_commits(page, result)
        await page.press("slash")
        await page.wait_for(lambda _state: bar.display)
        bar.query_one("#commit-filter-input", SingleLineVimTextArea).load_text("repo:")
        await page.wait_for(
            lambda _state: bar.query_one("#commit-filter-status").has_class("error")
        )
        # The first Escape dismisses completion while preserving the inline
        # error, leaving the diagnostic as the sole visual focus.
        await page.press("escape")
        await page.wait_for(
            lambda _state: not bar.query_one("#commit-filter-completion").display
        )
        await wait_for_svg_contains(page, "repo: requires a value")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_filter_parse_error_120x40",
            title="ACE Artifacts Commits filter parse error",
        )
