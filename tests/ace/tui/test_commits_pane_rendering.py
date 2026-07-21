"""Rendering and timeline contracts for the Artifacts Commits pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.util.lazy_syntax import (
    PLAIN_RENDER_MAX_BYTES,
    LazySyntaxRenderCache,
)
from sase.ace.tui.widgets.artifacts import CommitsPane, CommitsTimeline
from sase.ace.tui.widgets.artifacts.commits_rendering import (
    build_commit_detail,
    build_commit_view_spec,
    build_commits_info,
)
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.core.vcs_log_wire import CommitPresence
from sase.plan_documents import PlanWorkspace
from sase.vcs_log.models import LogRepo, RepoRemoteState
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
        project_display_name=None,
        project_scope=None,
        all_projects=False,
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
        project_display_name=None,
        project_scope=None,
        all_projects=False,
        result=result,
        refreshing=False,
    ).plain
    capped = build_commits_info(
        project_display_name=None,
        project_scope=None,
        all_projects=False,
        result=result,
        refreshing=False,
        active_limit=40,
    ).plain

    assert "limit:" not in exact
    assert "limit:40" in capped


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
