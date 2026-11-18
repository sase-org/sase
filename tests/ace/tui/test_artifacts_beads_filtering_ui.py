"""Filter bar and pane interactions for Artifacts Beads."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import beads_pane
from sase.ace.tui.widgets.artifacts.bead_filter_bar import BeadFilterBar
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from tests.ace.tui._artifacts_beads_helpers import snapshot


async def _open_bead_filter(page: AcePage, pane: ArtifactsBeadsPane) -> BeadFilterBar:
    """Slash-open the Beads filter and wait until the bar is actually editing."""

    await page.press("/")
    await page.wait_for(
        lambda _state: pane.query_one(BeadFilterBar)._editing,  # type: ignore[attr-defined]
        timeout_message=lambda: (
            "wait_for() timed out waiting for Beads filter edit —"
            f" session_open={pane._filter_session_open!r}"
            f" editing={pane.query_one(BeadFilterBar)._editing!r}"  # type: ignore[attr-defined]
        ),
    )
    return pane.query_one(BeadFilterBar)


class _BeadFilterBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield BeadFilterBar()


async def test_bead_filter_bar_completes_negated_status_and_dynamic_people() -> None:
    app = _BeadFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(BeadFilterBar)
        bar.set_completion_sources(
            projects=("Alpha",),
            assignees=("Alpha.Agent",),
            owners=("owner@example.com",),
            models=("codex/gpt-5",),
            bugs=("#42", "drift"),
            labels=("priority:high",),
        )
        bar.open("-sta")
        await pilot.pause()

        completion = app.query_one("#bead-filter-completion", OptionList)
        first = completion.get_option_at_index(0).prompt.plain
        assert first.startswith("-status:")
        await pilot.press("tab")
        await pilot.pause()
        editor = app.query_one("#bead-filter-input", SingleLineVimTextArea)
        assert editor.text == "-status:"

        editor.load_text("assignee:Alpha")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert editor.text == "assignee:Alpha.Agent "

        editor.load_text("label:prio")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert editor.text == "label:priority:high "


async def test_hide_closed_default_is_visible_and_clearable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        assert pane.filters.excluded_statuses == ("closed",)
        bar = pane.query_one(BeadFilterBar)
        assert bar.display
        display = bar.query_one("#bead-filter-display", Static)
        await page.wait_for(lambda _state: "-status:closed" in display.render().plain)

        assert pane.select_entry_target(
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1"))
        )
        pane.set_selected_epic_expanded(True)
        assert (
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "phase", "alpha-1.1"))
            not in pane.entry_targets()
        )

        bar = await _open_bead_filter(page, pane)
        bar.set_query("")
        bar.post_message(BeadFilterBar.Submitted(""))
        await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]

        assert pane.filters.is_empty
        assert bar.display
        assert display.render().plain == pane._query_profile.free_text_hint
        assert (
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "phase", "alpha-1.1"))
            in pane.entry_targets()
        )


async def test_clicking_idle_bead_bar_opens_the_filter_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        bar = pane.query_one(BeadFilterBar)
        assert not pane._filter_session_open

        await page.click("#bead-filter-bar")
        await page.pause()

        assert pane._filter_session_open
        assert bar._editing  # type: ignore[attr-defined]


async def test_committing_bead_query_updates_idle_bar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        bar = pane.query_one(BeadFilterBar)
        display = bar.query_one("#bead-filter-display", Static)

        bar = await _open_bead_filter(page, pane)
        bar.set_query("tier:epic")
        bar.post_message(BeadFilterBar.Submitted("tier:epic"))
        await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]

        assert pane.filters.tiers == ("epic",)
        assert display.render().plain == "tier:epic"


async def test_changing_project_scope_keeps_idle_bead_bar_in_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = snapshot(tmp_path, project="alpha")
    beta = snapshot(tmp_path, project="beta")
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda project, **_kwargs: alpha if project == "alpha" else beta,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        pane.set_project_scope("alpha")
        await page.wait_for(lambda _state: pane.snapshot is alpha)
        bar = pane.query_one(BeadFilterBar)
        display = bar.query_one("#bead-filter-display", Static)

        bar = await _open_bead_filter(page, pane)
        bar.set_query("tier:epic")
        bar.post_message(BeadFilterBar.Submitted("tier:epic"))
        await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]
        assert display.render().plain == "tier:epic"

        pane.set_project_scope("beta")
        await page.wait_for(lambda _state: pane.snapshot is beta)

        assert display.render().plain == "tier:epic"


async def test_bead_bar_geometry_is_unchanged_between_idle_and_editing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        option_list = pane.query_one("#beads-list")
        idle_region = option_list.region
        assert idle_region.height > 0

        await _open_bead_filter(page, pane)
        await page.pause()
        assert option_list.region == idle_region

        await page.press("escape")
        await page.pause()
        assert option_list.region == idle_region
