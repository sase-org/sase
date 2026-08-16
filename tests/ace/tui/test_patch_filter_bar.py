"""Patch filter bar completion tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace import saved_queries
from sase.ace.query.completion import patch_completion_context
from sase.ace.query_history import QueryHistoryStacks
from sase.ace.query_record import QueryRecord
from sase.ace.testing import AcePage, make_patch
from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.widgets.artifacts.panes import ArtifactsPatchesPane
from sase.ace.tui.widgets.artifacts.patch_filter_bar import PatchFilterBar


@pytest.fixture
def patch_profile():
    profile = compiled_profile_for_builtin_pane("patches")
    assert profile is not None
    return profile


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    [
        ("", 0, ("key", "", False)),
        ("foo ", 4, ("key", "", False)),
        ("(", 1, ("key", "", False)),
        ("!", 1, ("key", "", True)),
        ("foo AND ", 8, ("key", "", False)),
        ("sta", 3, ("key", "sta", False)),
        ("status:", 7, ("status", "", False)),
        ("+sa", 3, ("project", "sa", False)),
        ("^par", 4, ("ancestor", "par", False)),
        ("~sib", 4, ("sibling", "sib", False)),
        ("&nam", 4, ("name", "nam", False)),
        ("%", 1, ("macro", "", False)),
        ('"quoted', 7, ("text", "quoted", False)),
    ],
)
def test_patch_completion_contexts(text, cursor, expected, patch_profile) -> None:
    assert patch_completion_context(text, cursor, profile=patch_profile) == expected


def test_patch_filter_bar_offers_patch_specific_rows(patch_profile) -> None:
    bar = PatchFilterBar(profile=patch_profile)
    assert bar._completion_context("", 0) == ("key", "", False)

    displays = [
        candidate.display for candidate in bar._candidates_for("key", "", negated=False)
    ]

    assert "+project" in displays
    assert "!!!" in displays
    assert "@@@" in displays
    assert "$$$" in displays
    assert "*" in displays
    assert "#" in displays


def test_patch_filter_bar_macro_rows(patch_profile) -> None:
    bar = PatchFilterBar(profile=patch_profile)

    displays = [
        candidate.display
        for candidate in bar._candidates_for("macro", "", negated=False)
    ]

    assert "%w" in displays
    assert "%d" in displays
    assert "%y" in displays


def test_patch_filter_bar_unmounted_refresh_updates_are_noops(patch_profile) -> None:
    bar = PatchFilterBar(profile=patch_profile)

    bar.set_query('"feature"')
    bar.set_status(1, exact=True, error=None)
    bar.open('"feature"')
    bar.close()

    assert bar._last_query_text == '"feature"'  # type: ignore[attr-defined]
    assert not bar._editing  # type: ignore[attr-defined]


@pytest.fixture
def isolated_query_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    monkeypatch.setattr(
        "sase.ace.saved_queries._SAVED_QUERIES_FILE",
        tmp_path / "saved_queries.json",
    )
    monkeypatch.setattr(
        "sase.ace.saved_queries._LAST_QUERY_FILE",
        tmp_path / "last_query.txt",
    )
    monkeypatch.setattr(
        "sase.ace.query_history._QUERY_HISTORY_FILE",
        tmp_path / "query_history.json",
    )
    monkeypatch.setattr(
        "sase.ace.query_selection._QUERY_SELECTION_FILE",
        tmp_path / "query_selections.json",
    )
    return tmp_path


def _session_patches():
    return [
        make_patch(
            name="feature_a",
            description="Feature alpha",
            status="READY",
            file_path="/tmp/sase/sase.sase",
        ),
        make_patch(
            name="feature_b",
            description="Feature beta",
            status="WIP",
            file_path="/tmp/sase/sase.sase",
        ),
        make_patch(
            name="other_patch",
            description="Other work",
            status="DRAFT",
            file_path="/tmp/sase/sase.sase",
        ),
    ]


async def _open_patch_filter_bar(page: AcePage) -> PatchFilterBar:
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
    pane.show_filters()
    bar = pane.query_one(PatchFilterBar)
    await page.wait_for(lambda _state: bar._editing)  # type: ignore[attr-defined]
    return bar


async def _set_live_query(
    page: AcePage,
    bar: PatchFilterBar,
    text: str,
) -> None:
    bar.set_query(text)
    bar.post_message(PatchFilterBar.QueryChanged(text))
    await page.pause()


async def test_patch_filter_live_typing_rolls_back_without_persistence(
    isolated_query_persistence: Path,
) -> None:
    async with AcePage(
        query='"feature"',
        initial_tab="patches",
        patches=_session_patches(),
    ) as page:
        await page.wait_for(
            lambda _state: (
                [patch.name for patch in page.app.patches] == ["feature_a", "feature_b"]
            )
        )
        page.app._query_history = {"patches": QueryHistoryStacks(prev=[], next=[])}
        bar = await _open_patch_filter_bar(page)

        await _set_live_query(page, bar, '"feature_b"')

        assert page.app.query_string == '"feature"'
        assert page.app._query_history["patches"].prev == []
        assert not (isolated_query_persistence / "last_query.txt").exists()
        assert [patch.name for patch in page.app.patches] == ["feature_b"]

        bar.post_message(PatchFilterBar.Dismissed())
        await page.wait_for(
            lambda _state: (
                [patch.name for patch in page.app.patches] == ["feature_a", "feature_b"]
            )
        )

        assert page.app.query_string == '"feature"'
        assert page.app.current_idx == 0
        assert page.app.patches[0].name == "feature_a"
        assert page.app._query_history["patches"].prev == []
        assert not (isolated_query_persistence / "last_query.txt").exists()


async def test_patch_filter_submit_commits_history_and_last_query(
    isolated_query_persistence: Path,
) -> None:
    async with AcePage(
        query='"feature"',
        initial_tab="patches",
        patches=_session_patches(),
    ) as page:
        page.app._query_history = {"patches": QueryHistoryStacks(prev=[], next=[])}
        bar = await _open_patch_filter_bar(page)

        await _set_live_query(page, bar, '"feature_b"')
        bar.post_message(PatchFilterBar.Submitted('"feature_b"'))
        await page.wait_for(lambda _state: page.app.query_string == '"feature_b"')

        assert not bar._editing  # type: ignore[attr-defined]
        assert [patch.name for patch in page.app.patches] == ["feature_b"]
        assert page.app._query_history["patches"].prev == [
            QueryRecord(source='"feature"', canonical='"feature"')
        ]
        assert (isolated_query_persistence / "last_query.txt").read_text() == (
            '"feature_b"'
        )


async def test_patch_filter_parse_error_leaves_visible_list_unchanged() -> None:
    async with AcePage(
        query='"feature"',
        initial_tab="patches",
        patches=_session_patches(),
    ) as page:
        baseline = [patch.name for patch in page.app.patches]
        bar = await _open_patch_filter_bar(page)

        await _set_live_query(page, bar, "(")

        status = bar.query_one("#patch-filter-status", Static)
        assert status.has_class("error")
        assert status.content.plain
        assert [patch.name for patch in page.app.patches] == baseline
        assert page.app.query_string == '"feature"'


async def test_patch_filter_save_slot_grammar_keeps_active_query(
    isolated_query_persistence: Path,
) -> None:
    async with AcePage(
        query='"feature"',
        initial_tab="patches",
        patches=_session_patches(),
    ) as page:
        bar = await _open_patch_filter_bar(page)

        bar.set_query("#3 status:DRAFT")
        bar.post_message(PatchFilterBar.Submitted("#3 status:DRAFT"))
        await page.wait_for(
            lambda _state: "3" in saved_queries.load_saved_queries("patches")
        )

        assert page.app.query_string == '"feature"'
        assert bar._editing  # type: ignore[attr-defined]
        saved = saved_queries.load_saved_queries("patches")["3"]
        assert saved.source == "status:DRAFT"
        assert saved.canonical == "status:DRAFT"

        bar.set_query("#3")
        bar.post_message(PatchFilterBar.Submitted("#3"))
        await page.wait_for(
            lambda _state: "3" not in saved_queries.load_saved_queries("patches")
        )

        assert page.app.query_string == '"feature"'
        assert bar._editing  # type: ignore[attr-defined]


async def test_action_patches_filters_is_scoped_to_patches_pane() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")

        page.app.action_patches_filters()
        await page.pause()

        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        bar = pane.query_one(PatchFilterBar)
        assert not bar._editing  # type: ignore[attr-defined]
