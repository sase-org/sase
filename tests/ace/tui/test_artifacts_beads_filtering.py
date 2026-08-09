"""In-memory filters and inline query interactions for Artifacts Beads."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import beads_pane
from sase.ace.tui.widgets.artifacts.bead_filter_bar import BeadFilterBar
from sase.ace.tui.widgets.artifacts.beads_filtering import (
    build_bead_filter_index,
    compile_bead_matcher,
)
from sase.ace.tui.widgets.artifacts.beads_list import build_bead_options
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.bead.filter_query import (
    BeadFilterQueryError,
    default_bead_filter_values,
    parse_bead_filter_query,
)
from sase.bead.model import CloseRecord, ReopenCause, Resolution, TaskPlusOneEvidence
from tests.ace.tui._artifacts_beads_helpers import snapshot


class _BeadFilterBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield BeadFilterBar()


def _matched_ids(tmp_path: Path, query: str) -> list[str]:
    value = snapshot(tmp_path)
    value.epics[0].issue.is_ready_to_work = True
    value.epics[0].issue.model = "codex/gpt-5"
    value.epics[0].issue.patch_name = "sase-dd"
    value.epics[0].issue.patch_bug_id = "42"
    value.tasks[1].issue.assignee = "worker.alpha"
    value.phases_by_epic[("alpha", "alpha-1")][0].issue.notes = "Closed phase notes."
    value = replace(value, blocked_ids=frozenset({("alpha", "alpha-open")}))
    matcher = compile_bead_matcher(
        parse_bead_filter_query(
            query,
            now=datetime(2026, 7, 29, tzinfo=UTC),
        )
    )
    return [
        record.bead_id for record in build_bead_filter_index(value) if matcher(record)
    ]


def test_parse_bead_filter_query_accepts_negated_repeatable_terms() -> None:
    values = parse_bead_filter_query(
        "type:task,phase -status:closed tier:epic size:medium project:Alpha "
        'assignee:"alpha agent" owner:owner@example.com model:gpt-5 has:triage '
        'since:2026-07-01 until:2026-07-31 "ready for" -ordinary',
        now=datetime(2026, 7, 29, tzinfo=UTC),
    )

    assert values.types == ("task", "phase")
    assert values.excluded_statuses == ("closed",)
    assert values.tiers == ("epic",)
    assert values.sizes == ("medium",)
    assert values.projects == ("Alpha",)
    assert values.assignees == ("alpha agent",)
    assert values.owners == ("owner@example.com",)
    assert values.models == ("gpt-5",)
    assert values.has == ("triage",)
    assert values.since_texts == ("2026-07-01",)
    assert values.until_texts == ("2026-07-31",)
    assert values.text == ("ready for",)
    assert values.excluded_text == ("ordinary",)


@pytest.mark.parametrize(
    "query",
    [
        "type:bug",
        "status:done",
        "has:file",
        "unknown:value",
        "since:not-a-date",
        "type:",
    ],
)
def test_invalid_bead_filter_tokens_are_rejected(query: str) -> None:
    with pytest.raises(BeadFilterQueryError):
        parse_bead_filter_query(query, now=datetime(2026, 7, 29, tzinfo=UTC))


def test_filter_terms_match_bead_metadata_and_derived_labels(tmp_path: Path) -> None:
    assert _matched_ids(tmp_path, "-status:closed") == [
        "alpha-ready",
        "alpha-open",
        "alpha-1",
        "alpha-1.2",
    ]
    assert _matched_ids(tmp_path, "type:phase") == ["alpha-1.1", "alpha-1.2"]
    assert _matched_ids(tmp_path, "status:triage has:triage") == ["alpha-ready"]
    assert _matched_ids(tmp_path, "status:blocked") == ["alpha-open"]
    assert _matched_ids(tmp_path, "status:launched tier:epic") == ["alpha-1"]
    assert _matched_ids(tmp_path, "owner:owner@example.com assignee:alpha.agent") == [
        "alpha-1"
    ]
    assert _matched_ids(tmp_path, "model:gpt has:plan has:bug") == ["alpha-1"]
    assert _matched_ids(tmp_path, "size:medium has:deps") == ["alpha-1.2"]
    assert _matched_ids(tmp_path, "project:Alpha") == [
        "alpha-ready",
        "alpha-open",
        "alpha-1",
        "alpha-1.1",
        "alpha-1.2",
    ]
    assert _matched_ids(tmp_path, "since:2026-07-06") == [
        "alpha-ready",
        "alpha-1",
        "alpha-1.2",
    ]
    assert _matched_ids(tmp_path, '"Render the tree" -deps') == []


def test_has_plus_one_and_evidence_text_use_cached_filter_index(tmp_path: Path) -> None:
    value = snapshot(tmp_path)
    value.tasks[1].issue.plus_one_evidence.append(
        TaskPlusOneEvidence(
            timestamp="2026-08-01T15:00:00Z",
            reporter="agent.beta",
            note="Cold restart reproduction.",
            refs=("research:202608/cache.md",),
        )
    )
    index = build_bead_filter_index(value)

    has_matcher = compile_bead_matcher(parse_bead_filter_query("has:+1"))
    text_matcher = compile_bead_matcher(parse_bead_filter_query('"cold restart"'))

    assert [record.bead_id for record in index if has_matcher(record)] == ["alpha-open"]
    assert [record.bead_id for record in index if text_matcher(record)] == [
        "alpha-open"
    ]


def test_has_reopened_and_close_history_text_use_cached_filter_index(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    value.tasks[1].issue.close_history.append(
        CloseRecord(
            closed_at="2026-07-30T09:12:04Z",
            reopened_at="2026-08-05T17:04:11Z",
            reopened_via=ReopenCause.PLUS_ONE,
            close_reason="Not reproducible on main; the retry shim covers it.",
            resolution=Resolution.CANCELED,
            reopened_by="claude.probe",
        )
    )
    index = build_bead_filter_index(value)

    has_matcher = compile_bead_matcher(parse_bead_filter_query("has:reopened"))
    text_matcher = compile_bead_matcher(parse_bead_filter_query('"retry shim covers"'))

    assert [record.bead_id for record in index if has_matcher(record)] == ["alpha-open"]
    assert [record.bead_id for record in index if text_matcher(record)] == [
        "alpha-open"
    ]


def test_default_hide_closed_filter_hides_closed_phases_and_shows_counts(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    matcher = compile_bead_matcher(default_bead_filter_values())
    matched_ids = frozenset(
        record.option_id for record in build_bead_filter_index(value) if matcher(record)
    )
    options, rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics={("alpha", "alpha-1")},
        matched_option_ids=matched_ids,
    )
    prompts = {option.id: option.prompt.plain for option in options if option.id}

    assert "phase:alpha-1.1" not in rows
    assert "phase:alpha-1.2" in rows
    assert prompts["header:tasks"].startswith("── Tasks (2/2)")
    assert prompts["header:epics"].startswith("── Epics (1/1)")


def test_filter_index_reuses_unchanged_snapshot_source_key(tmp_path: Path) -> None:
    pane = ArtifactsBeadsPane()
    first = snapshot(tmp_path)
    second = replace(first)
    changed = replace(first, source_key=("changed",))
    pane.project_scope = "alpha"

    pane._snapshot = first
    original = pane._ensure_filter_index(needed=True)
    pane._snapshot = second
    reused = pane._ensure_filter_index(needed=True)
    pane._snapshot = changed
    rebuilt = pane._ensure_filter_index(needed=True)

    assert reused is original
    assert rebuilt is not original


async def test_bead_filter_bar_completes_negated_status_and_dynamic_people() -> None:
    app = _BeadFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(BeadFilterBar)
        bar.set_completion_sources(
            projects=("Alpha",),
            assignees=("Alpha.Agent",),
            owners=("owner@example.com",),
            models=("codex/gpt-5",),
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
        await page.press("2")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        assert pane.filters.excluded_statuses == ("closed",)
        assert "-status:closed" in pane.query_one("#beads-info", Static).content.plain

        assert pane.select_entry_target(("bead", "alpha", "epic", "alpha-1"))
        pane.set_selected_epic_expanded(True)
        assert ("bead", "alpha", "phase", "alpha-1.1") not in pane.entry_targets()

        await page.press("/")
        bar = pane.query_one(BeadFilterBar)
        await page.wait_for(lambda _state: bar.display)
        bar.set_query("")
        bar.post_message(BeadFilterBar.Submitted(""))
        await page.wait_for(lambda _state: not bar.display)

        assert pane.filters.is_empty
        assert (
            "-status:closed" not in pane.query_one("#beads-info", Static).content.plain
        )
        assert ("bead", "alpha", "phase", "alpha-1.1") in pane.entry_targets()
