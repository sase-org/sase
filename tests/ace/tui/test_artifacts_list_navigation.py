"""Fast stable-target navigation for non-PR Artifacts lists."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import ArtifactsBugsPane
from sase.ace.tui.widgets.artifacts import BugIssueList, BugLinkList, CommitsPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.ace.tui.widgets.artifacts.plans_data import PlansSnapshot
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.vcs_log.models import LogRepo, VcsLogResult
from tests.ace.tui.test_artifacts_bugs import _issue, _snapshot as _bugs_snapshot
from tests.ace.tui._artifacts_plans_helpers import (
    _choices,
    _snapshot as _plans_snapshot,
)


def _commits_result(count: int = 15) -> VcsLogResult:
    now = int(datetime(2026, 7, 17, 12, tzinfo=UTC).timestamp())
    commits = tuple(
        AggregatedCommitWire(
            "alpha",
            VcsCommitWire(
                full_id=f"{index + 1:040x}",
                short_id=f"{index + 1:07x}",
                author_name="Navigator",
                author_email="nav@example.com",
                timestamp=now - index * 86_400,
                subject=f"commit {index + 1}",
                body="",
                presence="local_only",
            ),
        )
        for index in range(count)
    )
    return VcsLogResult(
        repos=(LogRepo("alpha", "/tmp/alpha", "primary"),),
        commits=commits,
        warnings=(),
    )


def _expanded_plans_snapshot(tmp_path: Path, phase_count: int = 12) -> PlansSnapshot:
    snapshot = _plans_snapshot(tmp_path)
    epic = snapshot.epics[0].issue
    phase = snapshot.phases_by_epic[("alpha", epic.id)][0].issue
    phases = tuple(
        replace(
            snapshot.phases_by_epic[("alpha", epic.id)][0],
            issue=replace(
                phase,
                id=f"alpha-1.{index}",
                title=f"Phase {index}",
            ),
        )
        for index in range(1, phase_count + 1)
    )
    return replace(
        snapshot,
        phases_by_epic={("alpha", epic.id): phases},
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
    )


async def _assert_distance_navigation(
    page: AcePage,
    pane: CommitsPane | ArtifactsBugsPane | ArtifactsPlansPane,
) -> None:
    targets = pane.entry_targets()
    assert len(targets) == 15
    assert pane.selected_entry_target() == targets[0]

    await page.press("ctrl+f")
    assert pane.selected_entry_target() == targets[10]
    await page.press("ctrl+f")
    assert pane.selected_entry_target() == targets[14]
    await page.press("ctrl+b")
    assert pane.selected_entry_target() == targets[4]

    selected = pane.selected_entry_target()
    view = page.app._artifacts_view()
    assert view is not None
    scroll = view.detail_scroll(page.app.current_artifacts_subtab)
    await scroll.mount(Static("\n".join(f"detail line {i}" for i in range(100))))
    await page.wait_for(lambda _state: scroll.max_scroll_y > 0)
    visible_height = scroll.scrollable_content_region.height
    await page.press("ctrl+d")
    await page.wait_for(lambda _state: scroll.scroll_y > 0)
    assert pane.selected_entry_target() == selected
    assert scroll.scroll_y == min(visible_height // 2, scroll.max_scroll_y)
    await page.press("ctrl+u")
    await page.wait_for(lambda _state: scroll.scroll_y == 0)
    assert pane.selected_entry_target() == selected
    await page.press("g")
    assert pane.selected_entry_target() == targets[0]
    await page.press("G")
    assert pane.selected_entry_target() == targets[-1]


async def test_commits_fast_navigation_skips_day_banners_and_jumps_without_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _commits_result()
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("]")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        assert len(pane.entry_targets()) == 15
        assert pane.query_one("#commits-timeline", OptionList).option_count == 30
        await _assert_distance_navigation(page, pane)
        assert page.app.focused is pane.query_one("#commits-timeline", OptionList)

        await page.press("apostrophe", "apostrophe")
        assert pane.selected_entry_target() == pane.entry_targets()[0]
        await page.press("apostrophe")
        timeline = pane.query_one("#commits-timeline", OptionList)
        assert timeline.get_option_at_index(0).disabled is True
        assert "[" not in timeline.get_option_at_index(0).prompt.plain
        assert timeline.get_option_at_index(1).prompt.plain.startswith("[0] ")
        assert timeline.get_option_at_index(3).prompt.plain.startswith("[1] ")
        footer = page.query_one_widget("#keybinding-content", Static)
        assert "JUMP" in footer.content.plain
        await page.press("1")
        assert pane.selected_entry_target() == pane.entry_targets()[1]
        assert page.state["modal"] is None
        assert "JUMP" not in footer.content.plain

        await page.press("apostrophe", "apostrophe")
        assert pane.selected_entry_target() == pane.entry_targets()[0]
        await page.press("apostrophe", "escape")
        assert "JUMP" not in footer.content.plain
        await page.press("apostrophe", "question_mark")
        assert page.state["modal"] is None
        assert "JUMP" not in footer.content.plain

        first_target = pane.entry_targets()[0]
        selected_target = pane.selected_entry_target()
        pane.apply_entry_jump_hints({first_target: "A"})
        assert timeline.get_option_at_index(1).prompt.plain.startswith("[A] ")
        assert pane.selected_entry_target() == selected_target
        pane.clear_entry_jump_hints()


async def test_bugs_fast_navigation_restores_issue_focus_and_ignores_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _bugs_snapshot(tuple(_issue(number) for number in range(1, 16)))
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        page.app._set_artifacts_project_scope("alpha", picked=True)
        page.app.current_artifacts_subtab = "bugs"
        pane = page.query_one_widget("#artifacts-bugs-pane", ArtifactsBugsPane)
        await page.wait_for(lambda _state: pane.issues == snapshot.issues)
        links = pane.query_one("#bugs-links", BugLinkList)
        links.focus()
        await _assert_distance_navigation(page, pane)
        assert isinstance(page.app.focused, BugIssueList)

        await page.press("g", "apostrophe")
        issues = pane.query_one("#bugs-list", BugIssueList)
        assert issues.get_option_at_index(0).prompt.plain.startswith("[0] ")
        assert issues.get_option_at_index(1).prompt.plain.startswith("[1] ")
        assert links.option_count == 0
        await page.press("1")
        assert pane.selected_issue is not None
        assert pane.selected_issue.number == 2
        assert page.state["modal"] is None

        first_target = pane.entry_targets()[0]
        pane.apply_entry_jump_hints({first_target: "A"})
        assert issues.get_option_at_index(0).prompt.plain.startswith("[A] ")
        assert links.option_count == 0
        assert pane.selected_issue is not None
        assert pane.selected_issue.number == 2
        pane.clear_entry_jump_hints()
        pane.accept_snapshot(replace(snapshot, issues=tuple(reversed(snapshot.issues))))
        assert pane.selected_issue is not None
        assert pane.selected_issue.number == 2


async def test_bugs_two_character_jump_waits_for_complete_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _bugs_snapshot(tuple(_issue(number) for number in range(1, 64)))
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        page.app._set_artifacts_project_scope("alpha", picked=True)
        page.app.current_artifacts_subtab = "bugs"
        pane = page.query_one_widget("#artifacts-bugs-pane", ArtifactsBugsPane)
        await page.wait_for(lambda _state: pane.issues == snapshot.issues)
        origin = pane.selected_entry_target()

        await page.press("apostrophe")
        assert page.app._artifacts_jump_target_to_hint[pane.entry_targets()[0]] == "00"
        assert page.app._artifacts_jump_target_to_hint[pane.entry_targets()[62]] == "10"

        await page.press("1")
        assert page.app._entry_jump_mode_active is True
        assert page.app._artifacts_jump_pending_prefix == "1"
        assert pane.selected_entry_target() == origin

        await page.press("0")
        assert pane.selected_issue is not None
        assert pane.selected_issue.number == 63
        assert page.app._entry_jump_mode_active is False
        assert page.app._artifacts_jump_pending_prefix == ""


async def test_plans_fast_navigation_skips_headings_and_includes_expanded_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _expanded_plans_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        pane._expanded_epics.add(("alpha", "alpha-1"))
        pane._refresh_options()
        await _assert_distance_navigation(page, pane)
        option_list = pane.query_one("#plans-list", OptionList)
        assert page.app.focused is option_list
        assert option_list.option_count == 18

        await page.press("g", "apostrophe")
        selectable_prompts = [
            option_list.get_option_at_index(index).prompt.plain
            for index in range(option_list.option_count)
            if not option_list.get_option_at_index(index).disabled
        ]
        disabled_prompts = [
            option_list.get_option_at_index(index).prompt.plain
            for index in range(option_list.option_count)
            if option_list.get_option_at_index(index).disabled
        ]
        assert selectable_prompts[0].startswith("[0] ")
        assert selectable_prompts[1].startswith("[1] ")
        assert all(not prompt.startswith("[") for prompt in disabled_prompts)
        await page.press("1")
        assert pane.selected_row() is not None
        assert pane.selected_row().kind == "epic"  # type: ignore[union-attr]
        assert page.state["modal"] is None

        first_target = pane.entry_targets()[0]
        pane.apply_entry_jump_hints({first_target: "A"})
        assert next(
            option_list.get_option_at_index(index).prompt.plain
            for index in range(option_list.option_count)
            if not option_list.get_option_at_index(index).disabled
        ).startswith("[A] ")
        assert pane.selected_row() is not None
        assert pane.selected_row().kind == "epic"  # type: ignore[union-attr]
        pane.clear_entry_jump_hints()


async def test_non_pr_jump_history_is_isolated_and_model_changes_cancel_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commits = _commits_result(3)
    bugs = _bugs_snapshot(tuple(_issue(number) for number in range(1, 4)))
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: commits)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_args, **_kwargs: bugs,
    )

    async with AcePage(initial_tab="changespecs") as page:
        page.app._set_artifacts_project_scope("alpha", picked=True)
        await page.press("]")
        commits_pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: commits_pane.result is commits)
        await page.press("apostrophe", "1")
        assert page.app._artifacts_jump_history["commits"] == (
            "commit",
            "alpha",
            commits.commits[0].commit.full_id,
        )

        page.app.current_artifacts_subtab = "bugs"
        bugs_pane = page.query_one_widget("#artifacts-bugs-pane", ArtifactsBugsPane)
        await page.wait_for(lambda _state: bugs_pane.issues == bugs.issues)
        await page.press("apostrophe", "1")
        await page.press("apostrophe")
        footer = page.query_one_widget("#keybinding-content", Static)
        assert "' back" in footer.content.plain
        bugs_pane.accept_snapshot(_bugs_snapshot((_issue(9),)))
        assert "JUMP" not in footer.content.plain
        assert page.app._entry_jump_mode_active is False
        await page.press("apostrophe")
        assert "' first" in footer.content.plain
        assert "bugs" not in page.app._artifacts_jump_history
        await page.press("escape")

        page.app.current_artifacts_subtab = "commits"
        await page.press("apostrophe")
        assert "' back" in footer.content.plain
        await page.press("apostrophe")
        assert commits_pane.selected_entry_target() == commits_pane.entry_targets()[0]


async def test_configured_navigation_actions_route_to_non_pr_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _commits_result(3)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "keymaps": {
                    "app": {
                        "scroll_to_top": "f6",
                        "scroll_prompt_down": "f7",
                    }
                }
            }
        },
    )
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("]")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await page.press("G")
        assert pane.selected_entry_target() == pane.entry_targets()[-1]
        await page.press("g")
        assert pane.selected_entry_target() == pane.entry_targets()[-1]
        await page.press("f6")
        assert pane.selected_entry_target() == pane.entry_targets()[0]
        await page.press("f7")
        assert pane.selected_entry_target() == pane.entry_targets()[-1]
