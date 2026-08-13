"""Fast stable-target navigation for non-PR Artifacts lists."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.geometry import Region
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import CommitsPane
from sase.ace.tui.widgets.artifacts import files_pane as files_pane_module
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.ace.tui.widgets.artifacts.plans_data import PlansSnapshot
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.vcs_log.models import LogRepo, VcsLogResult
from tests.ace.tui._artifacts_plans_helpers import (
    _choices,
    _snapshot as _plans_snapshot,
)
from tests.ace.tui._artifacts_files_helpers import (
    artifact_file,
    snapshot as _files_snapshot,
)


def _commits_result(count: int = 50) -> VcsLogResult:
    now = int(datetime.now(tz=UTC).timestamp())
    commits = tuple(
        AggregatedCommitWire(
            "alpha",
            VcsCommitWire(
                full_id=f"{index + 1:040x}",
                short_id=f"{index + 1:07x}",
                author_name="Navigator",
                author_email="nav@example.com",
                timestamp=now,
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


def _expanded_plans_snapshot(tmp_path: Path, phase_count: int = 50) -> PlansSnapshot:
    snapshot = _plans_snapshot(tmp_path)
    active = snapshot.active[0]
    documents = tuple(
        replace(
            active,
            document=replace(
                active.document,
                path=str(tmp_path / "202607" / f"active-{index}.md"),
                frontmatter={
                    **active.document.frontmatter,
                    "title": f"Active plan {index}",
                },
            ),
            owner=replace(active.owner, bead_id=f"alpha-{index}"),
        )
        for index in range(1, phase_count + 1)
    )
    return replace(snapshot, active=documents)


class _DetailScheduleRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def schedule(self, _callback: object) -> None:
        self.calls += 1


def _entry_list(
    pane: CommitsPane | ArtifactsPlansPane,
) -> OptionList:
    if isinstance(pane, CommitsPane):
        return pane.query_one("#stitches-timeline", OptionList)
    return pane.query_one("#plans-list", OptionList)


def _assert_highlight_visible(option_list: OptionList) -> None:
    highlighted = option_list.highlighted
    assert highlighted is not None
    option_list._update_lines()
    option_region = Region(
        0,
        option_list._index_to_line[highlighted],
        option_list.scrollable_content_region.width,
        option_list._heights[highlighted],
    )
    viewport_region = Region(
        0,
        int(option_list.scroll_y),
        option_list.scrollable_content_region.width,
        option_list.scrollable_content_region.height,
    )
    assert viewport_region.contains_region(option_region)


async def _assert_distance_navigation(
    page: AcePage,
    pane: CommitsPane | ArtifactsPlansPane,
    *,
    expected_count: int = 50,
) -> None:
    targets = pane.entry_targets()
    assert len(targets) == expected_count
    assert pane.selected_entry_target() == targets[0]
    if isinstance(pane, CommitsPane):
        assert pane.query_one("#stitches-position", Static).content.plain == (
            f"[1/{expected_count}]  ·  "
        )
    option_list = _entry_list(pane)
    recorder = _DetailScheduleRecorder()
    original_debouncer = pane._detail_debouncer
    pane._detail_debouncer = recorder  # type: ignore[assignment]

    try:
        for target_index in (10, 20, 30, 40):
            await page.press("ctrl+f")
            assert pane.selected_entry_target() == targets[target_index]
            _assert_highlight_visible(option_list)
            if isinstance(pane, CommitsPane):
                assert pane.query_one("#stitches-position", Static).content.plain == (
                    f"[{target_index + 1}/{expected_count}]  ·  "
                )
        downward_scroll_y = option_list.scroll_y
        assert downward_scroll_y > 0

        for target_index in (30, 20, 10, 0):
            await page.press("ctrl+b")
            assert pane.selected_entry_target() == targets[target_index]
            _assert_highlight_visible(option_list)
            if isinstance(pane, CommitsPane):
                assert pane.query_one("#stitches-position", Static).content.plain == (
                    f"[{target_index + 1}/50]  ·  "
                )
        assert option_list.scroll_y < downward_scroll_y

        selected = pane.selected_entry_target()
        view = page.app._artifacts_view()
        assert view is not None
        scroll = view.detail_scroll(page.app.current_artifacts_pane_key)
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
        _assert_highlight_visible(option_list)
        if isinstance(pane, CommitsPane):
            assert pane.query_one("#stitches-position", Static).content.plain == (
                "[1/50]  ·  "
            )
        await page.press("G")
        assert pane.selected_entry_target() == targets[-1]
        _assert_highlight_visible(option_list)
        if isinstance(pane, CommitsPane):
            assert pane.query_one("#stitches-position", Static).content.plain == (
                "[50/50]  ·  "
            )
        selected = pane.selected_entry_target()
        assert selected is not None
        pane.apply_entry_jump_hints({selected: "A"})
        assert pane.selected_entry_target() == selected
        _assert_highlight_visible(option_list)
        pane.clear_entry_jump_hints()
        assert pane.selected_entry_target() == selected
        _assert_highlight_visible(option_list)
        assert page.state["modal"] is None
        assert recorder.calls == 9
    finally:
        pane._detail_debouncer = original_debouncer


async def test_commits_fast_navigation_skips_day_banners_and_jumps_without_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _commits_result()
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    async with AcePage(initial_tab="patches") as page:
        await page.press("1")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        assert len(pane.entry_targets()) == 50
        assert pane.query_one("#stitches-timeline", OptionList).option_count == 51
        await _assert_distance_navigation(page, pane)
        assert page.app.focused is pane.query_one("#stitches-timeline", OptionList)

        await page.press("apostrophe", "apostrophe")
        assert pane.selected_entry_target() == pane.entry_targets()[0]
        await page.press("apostrophe")
        timeline = pane.query_one("#stitches-timeline", OptionList)
        assert timeline.get_option_at_index(0).disabled is True
        assert "[" not in timeline.get_option_at_index(0).prompt.plain
        assert timeline.get_option_at_index(1).prompt.plain.startswith("[0] ")
        assert timeline.get_option_at_index(2).prompt.plain.startswith("[1] ")
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


async def test_plans_fast_navigation_skips_document_section_headings(
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

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await _assert_distance_navigation(page, pane, expected_count=52)
        option_list = pane.query_one("#plans-list", OptionList)
        assert page.app.focused is option_list
        assert option_list.option_count == 55

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
        assert pane.selected_row().kind == "active"  # type: ignore[union-attr]
        assert page.state["modal"] is None

        first_target = pane.entry_targets()[0]
        pane.apply_entry_jump_hints({first_target: "A"})
        assert next(
            option_list.get_option_at_index(index).prompt.plain
            for index in range(option_list.option_count)
            if not option_list.get_option_at_index(index).disabled
        ).startswith("[A] ")
        assert pane.selected_row() is not None
        assert pane.selected_row().kind == "active"  # type: ignore[union-attr]
        pane.clear_entry_jump_hints()


async def test_files_implements_shared_stable_target_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = tuple(
        artifact_file(
            f"file-{index:02d}",
            created_at=f"2026-07-24T{23 - index // 3:02d}:{index % 60:02d}:00-04:00",
        )
        for index in range(50)
    )
    snapshot = _files_snapshot(rows)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        files_pane_module,
        "load_files_snapshot",
        lambda _project, _limit: snapshot,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"), "(")
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        targets = pane.entry_targets()
        assert len(targets) == 50
        assert pane.selected_entry_target() == targets[0]

        await page.press("ctrl+f")
        assert pane.selected_entry_target() == targets[10]
        await page.press("ctrl+b")
        assert pane.selected_entry_target() == targets[0]
        await page.press("G")
        assert pane.selected_entry_target() == targets[-1]
        await page.press("g")
        assert pane.selected_entry_target() == targets[0]

        pane.apply_entry_jump_hints({targets[1]: "A"})
        option_list = pane.query_one("#files-list", OptionList)
        assert any(
            option_list.get_option_at_index(index).prompt.plain.startswith("[A] ")
            for index in range(option_list.option_count)
        )
        assert pane.selected_entry_target() == targets[0]
        pane.clear_entry_jump_hints()
        assert pane.selected_entry_target() == targets[0]


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

    async with AcePage(initial_tab="patches") as page:
        await page.press("1")
        pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await page.press("G")
        assert pane.selected_entry_target() == pane.entry_targets()[-1]
        await page.press("g")
        assert pane.selected_entry_target() == pane.entry_targets()[-1]
        await page.press("f6")
        assert pane.selected_entry_target() == pane.entry_targets()[0]
        await page.press("f7")
        assert pane.selected_entry_target() == pane.entry_targets()[-1]
