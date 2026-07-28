"""Rendering and timeline contracts for the Artifacts Commits pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from rich.color import Color
from rich.console import Console
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.util.lazy_syntax import (
    PLAIN_RENDER_MAX_BYTES,
    LazySyntaxRenderCache,
)
from sase.ace.tui.widgets.artifacts import CommitsPane, CommitsTimeline
from sase.ace.tui.widgets.artifacts.commits_rendering import (
    build_commit_detail,
    build_commit_position_badge,
    build_commit_view_spec,
    build_commits_info,
    build_commits_legend,
)
import sase.ace.tui.widgets.artifacts.commits as commits_module
import sase.ace.tui.widgets.artifacts.commits_pane as commits_pane_module
from sase.core.vcs_log_wire import CommitPresence
from sase.plan_documents import PlanWorkspace
from sase.vcs_log._style import GOLD
from sase.vcs_log.models import LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log.render import build_pretty_legend
from tests.ace.tui._commits_pane_helpers import (
    _DIFF,
    _byte_heavy_diff,
    _rendered_text,
    _result,
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


def test_commits_info_legend_only_lists_repositories_with_displayed_rows() -> None:
    result = _result()
    with_empty_repo = replace(
        result,
        repos=(*result.repos, LogRepo("empty-repo", "/tmp/empty", "linked")),
        remote_states=(
            *result.remote_states,
            RepoRemoteState("empty-repo", "origin/main", 3, 2, True, 1.0),
        ),
    )
    row_limited = replace(with_empty_repo, commits=with_empty_repo.commits[:1])

    info = build_commits_info(
        result=row_limited,
        refreshing=False,
    ).plain

    assert "alpha-platform-repository (1)" in info
    assert "sase-core-foundation" not in info
    assert "empty-repo" not in info
    assert "↑3 ↓2" not in info


def test_commits_info_only_renders_active_cap_when_supplied() -> None:
    result = _result()

    exact = build_commits_info(
        result=result,
        refreshing=False,
    ).plain
    capped = build_commits_info(
        result=result,
        refreshing=False,
        active_limit=40,
    ).plain

    assert "limit:" not in exact
    assert "limit:40" in capped
    assert "Scope" not in capped
    assert "project" not in capped.casefold()


def test_commit_position_badge_is_one_based_styled_and_precedes_repository() -> None:
    result = _result()
    badge = build_commit_position_badge(
        result=result,
        selected_commit_index=1,
    )
    console = Console()

    assert badge.plain == "[2/2]  ·  "
    assert badge.get_style_at_offset(console, 0).dim is True
    numerator_style = badge.get_style_at_offset(console, 1)
    assert numerator_style.bold is True
    assert numerator_style.color == Color.parse("white")
    denominator_style = badge.get_style_at_offset(console, 3)
    assert denominator_style.bold is True
    assert denominator_style.color == Color.parse(GOLD)

    info = build_commits_info(
        result=result,
        refreshing=False,
        selected_commit_index=1,
    )
    assert info.plain.splitlines()[1].startswith(
        "[2/2]  ·  alpha-platform-repository (1)"
    )
    assert "\n  vs origin/main" in build_commits_legend(result).plain


@pytest.mark.parametrize(
    ("result", "selected_commit_index", "expected"),
    (
        (None, None, ""),
        (VcsLogResult((), (), ()), None, "[0/0]  ·  "),
        (_result(), None, "[-/2]  ·  "),
        (
            replace(_result(), provider_truncation_possible=True),
            0,
            "[1/2+]  ·  ",
        ),
        (
            replace(_result(), aggregate_truncated=True),
            0,
            "[1/2+]  ·  ",
        ),
    ),
    ids=("pre-load", "empty", "no-selection", "provider-cap", "aggregate-cap"),
)
def test_commit_position_badge_truthful_states(
    result: VcsLogResult | None,
    selected_commit_index: int | None,
    expected: str,
) -> None:
    assert (
        build_commit_position_badge(
            result=result,
            selected_commit_index=selected_commit_index,
        ).plain
        == expected
    )


def test_commit_position_badge_handles_referenced_large_timeline() -> None:
    result = _result()
    template = result.commits[0]
    commits = tuple(
        replace(
            template,
            commit=replace(
                template.commit,
                full_id=f"{index:040x}",
                short_id=f"{index:07x}",
            ),
        )
        for index in range(105)
    )

    assert (
        build_commit_position_badge(
            result=replace(result, commits=commits),
            selected_commit_index=14,
        ).plain
        == "[15/105]  ·  "
    )


def test_empty_commits_info_has_one_separator_before_presence_legend() -> None:
    info = build_commits_info(
        result=VcsLogResult((), (), ()),
        refreshing=False,
    )

    assert info.plain.splitlines()[1].startswith("[0/0]  ·  ↑ unpushed")
    assert "·  ·" not in info.plain


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


def test_commit_view_spec_preserves_owner_context_and_full_tagged_message() -> None:
    result = _result()
    owner = PlanWorkspace(
        workspace_dir="/workspace/alpha",
        plans_root="/workspace/alpha/sase/repos/plans",
        project="alpha",
    )
    result = replace(
        result,
        repos=(replace(result.repos[0], plan_workspaces=(owner,)), *result.repos[1:]),
    )

    spec = build_commit_view_spec(result.commits[0], result)

    assert spec.plan_workspaces == (owner,)
    assert "SASE_PLAN=sdd/plans/commits_single_line_timeline.md" in spec.message


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
        await page.press("1")
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
        position = pane.query_one("#commits-position", Static)
        assert position.content.plain == "[1/2]  ·  "
        monkeypatch.setattr(
            commits_pane_module,
            "build_commits_legend",
            lambda _result: pytest.fail("selection rebuilt the repository legend"),
        )
        assert pane.select_entry_target(target) is True
        assert position.content.plain == "[2/2]  ·  "
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
