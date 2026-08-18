"""PNG visual coverage for the Artifacts Stitches timeline and detail."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from textual.widgets._header import HeaderIcon
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.modals.inventory_project_picker import InventoryProjectChoice
from sase.ace.tui.widgets.artifacts import CommitsPane
from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.artifacts.commits_timeline import CommitsTimeline
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.vcs_log.filter_query import parse_commit_filter_query, to_query_string
from tests.ace.tui._commits_pane_helpers import (
    _DIFF,
    _result,
    _result_with_merge,
    _result_with_sidecar,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_state,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _pinned_sase_project_choices() -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key="sase",
                display_name="sase",
                state="enabled",
            ),
        ),
        enabled_projects=("sase",),
        display_names={"sase": "sase"},
        current_project="sase",
    )


@pytest.fixture(autouse=True)
def _pin_rolling_default_query_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin rolling-query and remote-fetch clocks for stable visual output."""
    reference = datetime(2026, 7, 7, 12, tzinfo=UTC)
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: ("/tmp/sase.sase", 1, "sase"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _pinned_sase_project_choices,
    )
    monkeypatch.setattr(
        "sase.ace.query.profile_reference_support.normalize_reference_time",
        lambda: reference,
    )
    monkeypatch.setattr(
        "sase.vcs_log._render_util._now_epoch",
        reference.timestamp,
    )


async def _open_commits(
    page: AcePage,
    result: commits_module.VcsLogResult,
) -> tuple[CommitsPane, CommitFilterBar]:
    await wait_for_startup(page)
    await page.expect_state("artifacts_subtab", "stitches")
    pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
    await page.wait_for(
        lambda _state: pane.filters.project == "sase" and pane.result is result
    )
    return pane, pane.query_one(CommitFilterBar)


async def _commit_filter_query(
    page: AcePage,
    pane: CommitsPane,
    bar: CommitFilterBar,
    query: str,
) -> None:
    values = parse_commit_filter_query(query)
    await page.press("slash")
    await wait_for_state(page, lambda: bar.display, description="commit filter bar")
    bar.query_one("#commit-filter-input", SingleLineVimTextArea).load_text(query)
    await wait_for_state(
        page,
        lambda: (
            pane.filters == values
            and (pane._scope_key(), values) in pane._authoritative_results
        ),
        description="authoritative commit filter result",
        timeout=30.0,
    )
    await page.press("enter")
    await wait_for_state(
        page,
        lambda: pane.query_one("#stitches-timeline", CommitsTimeline).has_focus,
        description="commits timeline focus",
    )
    assert bar.display is True


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
        _pinned_sase_project_choices,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="patches",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(
            lambda _state: pane.filters.project == "sase" and pane.result is result
        )
        assert (
            pane.query_one("#commit-filter-input", SingleLineVimTextArea).text
            == "project:sase sidecar:false merges:hide since:24h"
        )
        await wait_for_svg_contains(page, "feat(artifacts): keep every commit")
        await wait_for_svg_contains(page, "Changes:")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_timeline_detail_120x40",
            title="ACE Artifacts Stitches timeline",
        )


async def test_commits_origin_legend_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    long_base = _result(timestamp)
    base = replace(
        long_base,
        repos=(
            replace(long_base.repos[0], name="alpha"),
            replace(long_base.repos[1], name="core"),
        ),
        commits=(
            replace(long_base.commits[0], repo="alpha"),
            replace(long_base.commits[1], repo="core"),
        ),
        remote_states=(
            replace(long_base.remote_states[0], name="alpha"),
            replace(long_base.remote_states[1], name="core"),
        ),
    )
    stitch_entry = replace(
        base.commits[1],
        commit=replace(
            base.commits[1].commit,
            full_id="c" * 40,
            short_id="ccccccc",
            timestamp=timestamp - 120,
            subject="feat(stitches): record tracked workflow commit",
            origin="stitch",
        ),
    )
    result = replace(base, commits=(*base.commits, stitch_entry))
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _pinned_sase_project_choices,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="patches",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(
            lambda _state: pane.filters.project == "sase" and pane.result is result
        )
        await wait_for_svg_contains(page, "✦")
        await wait_for_svg_contains(page, "↻")
        await wait_for_svg_contains(page, "✎")
        await wait_for_svg_contains(page, "stitch")
        await wait_for_svg_contains(page, "auto")
        await wait_for_svg_contains(page, "manual")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_origin_legend_120x40",
            title="ACE Artifacts Stitches origin legend",
        )


async def test_commits_merge_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "commits": {"default_query": "sidecar:false merges:show since:24h"}
                }
            }
        },
    )
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result_with_merge(timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _pinned_sase_project_choices,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="patches",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(
            lambda _state: pane.filters.project == "sase" and pane.result is result
        )
        assert (
            pane.query_one("#commit-filter-input", SingleLineVimTextArea).text
            == "project:sase sidecar:false merges:show since:24h"
        )
        await wait_for_svg_contains(page, "mmmmmmm")
        await wait_for_svg_contains(page, "◆ merge")
        await wait_for_svg_contains(page, "Changes introduced by this merge")
        await wait_for_svg_contains(page, "parents")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_merge_row_120x40",
            title="ACE Artifacts Stitches merge row",
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
        _pinned_sase_project_choices,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="patches",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(
            lambda _state: pane.filters.project == "sase" and pane.result is result
        )
        timeline = pane.query_one("#stitches-timeline", CommitsTimeline)
        await page.wait_for(
            lambda _state: (
                timeline.option_count == 1
                and "No commits match" in timeline.get_option_at_index(0).prompt.plain
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_empty_120x40",
            title="ACE Artifacts Stitches empty",
        )


async def test_commits_persistent_filter_small_terminal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "commits": {"default_query": "sidecar:false since:24h limit:40"}
                }
            }
        },
    )
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = replace(
        _result(timestamp),
        provider_truncation_possible=True,
    )
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    # This snapshot covers an explicit limit and capped-state chrome. Keep
    # the unrelated detail pane on its stable no-diff path so lazy syntax
    # layout cannot race the screenshot under a heavily parallel full run.
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: None)

    async with AcePage(
        query='"visual"',
        size=(80, 24),
        patches=patches(),
        initial_tab="patches",
    ) as page:
        pane, bar = await _open_commits(page, result)
        assert (
            bar.query_one("#commit-filter-input", SingleLineVimTextArea).text
            == "project:sase sidecar:false merges:hide since:24h limit:40"
        )
        assert bar.query_one("#commit-filter-status").content.plain == "capped"
        assert pane.query_one("#stitches-position").content.plain == "[1/2+]  ·  "
        await page.wait_for(lambda _state: bool(pane._diff_cache))
        await wait_for_visual_idle(page)
        page.app.query_one(HeaderIcon).display = True
        # The detail content is incidental here, and Textual's proportional
        # thumb can differ by a few raster pixels as its async layout settles.
        # Hide that scrollbar so this snapshot measures the capped filter UI.
        pane.query_one("#stitches-detail-scroll").styles.overflow_y = "hidden"
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_persistent_filter_80x24",
            title="ACE Artifacts Stitches persistent filter at 80x24",
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
        _pinned_sase_project_choices,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="patches",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("artifacts_subtab", "stitches")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(
            lambda _state: pane.filters.project == "sase" and pane.result is result
        )
        await wait_for_svg_contains(page, "feat(artifacts): keep every commit")
        await page.press("apostrophe")
        await wait_for_svg_contains(page, "JUMP")
        timeline = pane.query_one("#stitches-timeline", CommitsTimeline)
        await page.wait_for(
            lambda _state: timeline.get_option_at_index(1).prompt.plain.startswith(
                "[0]"
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_jump_hints_120x40",
            title="ACE Artifacts Stitches jump hints",
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
        patches=patches(),
        initial_tab="patches",
    ) as page:
        pane, bar = await _open_commits(page, result)
        query = "repo:alpha-platform-repository feat"
        await _commit_filter_query(page, pane, bar, query)
        await page.press("slash")
        canonical = to_query_string(parse_commit_filter_query(query))
        await page.wait_for(
            lambda _state: (
                bar.display
                and bar.query_one("#commit-filter-input", SingleLineVimTextArea).text
                == canonical
            )
        )
        await page.wait_for(
            lambda _state: (
                bar.query_one("#commit-filter-status").content.plain == "exact"
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_filter_bar_prefilled_120x40",
            title="ACE Artifacts Stitches prefilled filter bar",
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
        patches=patches(),
        initial_tab="patches",
    ) as page:
        pane, bar = await _open_commits(page, result)
        pane.show_filters()
        bar.set_project_completion_sources(("sase", "sase-github"))
        bar.open("project:")
        completion = bar.query_one("#commit-filter-completion", OptionList)
        await page.wait_for(
            lambda _state: completion.display and completion.option_count == 2
        )
        await wait_for_svg_contains(page, "project name")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_filter_completion_120x40",
            title="ACE Artifacts Stitches project completion",
        )


async def test_commits_sidecar_filter_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    narrow = _result(timestamp)
    broad = _result_with_sidecar(timestamp)
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **kwargs: broad if kwargs["include_sidecars"] else narrow,
    )
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: _DIFF)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="patches",
    ) as page:
        pane, bar = await _open_commits(page, narrow)
        await page.press("slash")
        editor = bar.query_one("#commit-filter-input", SingleLineVimTextArea)
        editor.load_text("sidecar:true")
        editor.cursor_position = len(editor.text)
        completion = bar.query_one("#commit-filter-completion", OptionList)
        await page.wait_for(
            lambda _state: (
                pane.filters.sidecar
                and pane.result is broad
                and completion.display
                and completion.option_count == 1
            )
        )
        await wait_for_svg_contains(page, "sidecar:true")
        await wait_for_svg_contains(page, "ccccccc")
        await wait_for_svg_contains(page, "include sidecar repositories")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_sidecar_filter_120x40",
            title="ACE Artifacts Stitches sidecar filter",
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
        patches=patches(),
        initial_tab="patches",
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
                and pane.query_one("#stitches-timeline", CommitsTimeline).has_focus
            )
        )
        canonical = bar.query_one("#commit-filter-input", SingleLineVimTextArea).text
        assert "repo:sase-core-foundation" in canonical
        assert "limit:" not in canonical
        await wait_for_svg_contains(page, "fix(artifacts): preserve")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_stitches_narrowed_filter_chips_120x40",
            title="ACE Artifacts Stitches narrowed filter chips",
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
        patches=patches(),
        initial_tab="patches",
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
            "artifacts_stitches_filter_parse_error_120x40",
            title="ACE Artifacts Stitches filter parse error",
        )
