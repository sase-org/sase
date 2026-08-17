"""Index-backed ranking for saved placeholder completions."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionMetadata,
    PlaceholderRankingMetadata,
    build_indexed_placeholder_completion_result,
    build_placeholder_completion_result,
)
from sase.ace.tui.widgets.prompt_completion import (
    PromptCompletionSettings,
    parse_prompt_completion_settings,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.history.prompt_word_index import _parse_sase_timestamp_epoch

from ._placeholder_completion_helpers import (
    RankedPlaceholderCompletionTestApp,
    placeholder_entry,
    placeholder_index,
    related_over_frequent_index,
)


def _sources(ta: PromptTextArea) -> list[str | None]:
    return [
        getattr(candidate.metadata, "source", None)
        for candidate in ta._file_completion_candidates
    ]


def _insertions(ta: PromptTextArea) -> list[str]:
    return [candidate.insertion for candidate in ta._file_completion_candidates]


def _rank_at(
    text: str,
    *,
    now: float,
    smart: bool = True,
    include_common_when_prefix_empty: bool = True,
):
    return build_indexed_placeholder_completion_result(
        text,
        len(text),
        related_over_frequent_index(),
        now=now,
        smart=smart,
        include_common_when_prefix_empty=include_common_when_prefix_empty,
    )


def test_placeholder_ranking_settings_parse_defaults_and_fallbacks() -> None:
    defaults = parse_prompt_completion_settings({})
    assert defaults.placeholder_ranking == "smart"
    assert defaults.placeholder_ranking_signals is True

    recent = parse_prompt_completion_settings({"placeholder_ranking": "recent"})
    assert recent.placeholder_ranking == "recent"

    unknown = parse_prompt_completion_settings({"placeholder_ranking": "weird"})
    assert unknown.placeholder_ranking == "smart"
    assert (
        parse_prompt_completion_settings(
            {"placeholder_ranking": " RECENT "}
        ).placeholder_ranking
        == "recent"
    )

    assert (
        parse_prompt_completion_settings(
            {"placeholder_ranking_signals": False}
        ).placeholder_ranking_signals
        is False
    )
    assert (
        parse_prompt_completion_settings(
            {"placeholder_ranking_signals": 0}
        ).placeholder_ranking_signals
        is False
    )
    assert (
        parse_prompt_completion_settings(
            {"placeholder_ranking_signals": "no"}
        ).placeholder_ranking_signals
        is True
    )


def test_indexed_builder_ranks_saved_tags_that_are_not_the_most_used() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    result = _rank_at("please monitor bravo charlie delta then <", now=now)

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == [
        "phase title",
        "worker",
    ]
    assert [candidate.metadata.source for candidate in result.candidates] == [
        "common",
        "common",
    ]
    top = result.candidates[0].metadata
    assert isinstance(top, PlaceholderCompletionMetadata)
    assert isinstance(top.ranking, PlaceholderRankingMetadata)
    assert top.ranking.reason == "relation"
    assert top.ranking.related_to == "bravo"
    assert result.candidates[1].metadata.ranking is not None


def test_indexed_builder_recent_mode_keeps_store_order_without_metadata() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    result = _rank_at(
        "please monitor bravo charlie delta then <",
        now=now,
        smart=False,
    )

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == [
        "worker",
        "phase title",
    ]
    assert all(
        isinstance(candidate.metadata, PlaceholderCompletionMetadata)
        and candidate.metadata.ranking is None
        for candidate in result.candidates
    )


def test_indexed_builder_keeps_prompt_local_order_and_dedups_saved_tags() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    index = placeholder_index(
        placeholder_entry(
            "alpha",
            count=2,
            last_used="260801_000000",
            context={"monitor": 2},
        ),
        placeholder_entry(
            "worker",
            count=4,
            last_used="260815_000000",
            context={"filler": 4},
        ),
        prompt_count=16,
        context_frequency={"monitor": 2, "filler": 4},
    )
    text = "Use <alpha> and <alpine> then <"
    result = build_indexed_placeholder_completion_result(
        text,
        len(text),
        index,
        now=now,
        smart=True,
        include_common_when_prefix_empty=True,
    )

    assert result is not None
    assert [
        (candidate.insertion, getattr(candidate.metadata, "source", None))
        for candidate in result.candidates
    ] == [
        ("alpha", "prompt"),
        ("alpine", "prompt"),
        ("worker", "common"),
    ]
    assert result.candidates[0].metadata.ranking is None
    assert result.candidates[2].metadata.ranking is not None


def test_indexed_builder_hides_saved_group_at_an_empty_auto_prefix() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    auto = _rank_at(
        "please monitor bravo charlie delta then use <alpha> then <",
        now=now,
        include_common_when_prefix_empty=False,
    )
    manual = _rank_at(
        "please monitor bravo charlie delta then use <alpha> then <",
        now=now,
    )

    assert auto is not None
    assert [candidate.insertion for candidate in auto.candidates] == ["alpha"]
    assert manual is not None
    assert [candidate.insertion for candidate in manual.candidates] == [
        "alpha",
        "phase title",
        "worker",
    ]


def test_list_builder_is_unchanged_when_common_is_an_explicit_sequence() -> None:
    text = "Use <feature flag> and <fe"
    result = build_placeholder_completion_result(
        text,
        len(text),
        ["fedora", "feature branch"],
    )

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == [
        "feature flag",
        "fedora",
        "feature branch",
    ]
    assert [candidate.metadata for candidate in result.candidates] == [
        PlaceholderCompletionMetadata(source="prompt"),
        PlaceholderCompletionMetadata(source="common"),
        PlaceholderCompletionMetadata(source="common"),
    ]


async def test_smart_menu_ranks_related_saved_tag_ahead_of_frequent_recent() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    app = RankedPlaceholderCompletionTestApp(related_over_frequent_index())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("please monitor bravo charlie delta then <")
        ta.cursor_location = (0, len(ta.text))

        with patch(
            "sase.ace.tui.widgets._placeholder_highlight.time.time",
            return_value=now,
        ):
            await pilot.press("ctrl+t")

        assert ta._completion_kind == PLACEHOLDER_COMPLETION_KIND
        assert _insertions(ta) == ["phase title", "worker"]
        assert _sources(ta) == ["common", "common"]
        top = ta._file_completion_candidates[0].metadata
        assert isinstance(top, PlaceholderCompletionMetadata)
        assert top.ranking is not None
        assert top.ranking.reason == "relation"


async def test_recent_menu_reproduces_store_order_without_ranking_metadata() -> None:
    app = RankedPlaceholderCompletionTestApp(
        related_over_frequent_index(),
        settings=PromptCompletionSettings(placeholder_ranking="recent"),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("please monitor bravo charlie delta then <")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert app.settings.placeholder_ranking == "recent"
        assert _insertions(ta) == ["worker", "phase title"]
        assert all(
            isinstance(candidate.metadata, PlaceholderCompletionMetadata)
            and candidate.metadata.ranking is None
            for candidate in ta._file_completion_candidates
        )


async def test_auto_trigger_hides_ranked_saved_group_until_a_prefix() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    app = RankedPlaceholderCompletionTestApp(related_over_frequent_index())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and ")
        ta.cursor_location = (0, len(ta.text))

        with patch(
            "sase.ace.tui.widgets._placeholder_highlight.time.time",
            return_value=now,
        ):
            await pilot.press("<")

            assert ta._placeholder_completion_trigger == "auto"
            assert _insertions(ta) == ["alpha"]

            await pilot.press("p")

            assert _insertions(ta) == ["phase title"]
            assert _sources(ta) == ["common"]


async def test_disabled_index_reproduces_prompt_local_menu() -> None:
    empty = placeholder_index(prompt_count=0)
    app = RankedPlaceholderCompletionTestApp(
        empty,
        settings=PromptCompletionSettings(common_placeholder_count=0),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and <alpine> then ")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("<")

        assert _insertions(ta) == ["alpha", "alpine"]
        assert _sources(ta) == ["prompt", "prompt"]

        await pilot.press("ctrl+t")

        assert _insertions(ta) == ["alpha", "alpine"]
        assert _sources(ta) == ["prompt", "prompt"]


async def test_ctrl_d_removes_a_ranked_saved_row_without_rebuilding_the_store() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    app = RankedPlaceholderCompletionTestApp(related_over_frequent_index())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("please monitor bravo charlie delta then <")
        ta.cursor_location = (0, len(ta.text))

        with (
            patch(
                "sase.ace.tui.widgets._placeholder_highlight.time.time",
                return_value=now,
            ),
            patch("sase.ace.tui.util.io_async.schedule_persist") as schedule,
            patch.object(app, "notify") as notify,
        ):
            await pilot.press("ctrl+t", "ctrl+d")

        assert app.forgotten_common_placeholders == ["phase title"]
        forgotten = app.common_placeholder_index()
        assert forgotten is not None
        assert [entry.text for entry in forgotten.entries] == ["worker"]
        assert _insertions(ta) == ["worker"]
        notify.assert_called_once_with(
            "Deleted saved placeholder: <phase title>",
            severity="information",
            markup=False,
        )
        assert schedule.call_args.args[2] == "phase title"


async def test_ctrl_d_still_refuses_prompt_rows_on_the_ranked_path() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    app = RankedPlaceholderCompletionTestApp(related_over_frequent_index())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and <alpine> then <")
        ta.cursor_location = (0, len(ta.text))

        with (
            patch(
                "sase.ace.tui.widgets._placeholder_highlight.time.time",
                return_value=now,
            ),
            patch("sase.ace.tui.util.io_async.schedule_persist") as schedule,
            patch.object(app, "notify") as notify,
        ):
            await pilot.press("ctrl+t", "ctrl+d")

        assert _insertions(ta)[:2] == ["alpha", "alpine"]
        assert app.forgotten_common_placeholders == []
        schedule.assert_not_called()
        notify.assert_called_once_with(
            "This placeholder comes from the current prompt, not the saved list",
            severity="information",
            markup=False,
        )


async def test_cold_index_menu_re_ranks_once_the_cache_publishes() -> None:
    now = _parse_sase_timestamp_epoch("260815_000000")
    app = RankedPlaceholderCompletionTestApp(None)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(
            "please monitor bravo charlie delta then use <alpha> and <alpine> then <"
        )
        ta.cursor_location = (0, len(ta.text))

        with patch(
            "sase.ace.tui.widgets._placeholder_highlight.time.time",
            return_value=now,
        ):
            await pilot.press("ctrl+t")

            assert _insertions(ta) == ["alpha", "alpine"]
            assert _sources(ta) == ["prompt", "prompt"]

            app.publish_common_placeholder_index(related_over_frequent_index())
            ta._refresh_file_completion_from_cursor()

            assert _insertions(ta) == ["alpha", "alpine", "phase title", "worker"]
            assert _sources(ta) == ["prompt", "prompt", "common", "common"]
            saved = ta._file_completion_candidates[2].metadata
            assert isinstance(saved, PlaceholderCompletionMetadata)
            assert saved.ranking is not None
            assert saved.ranking.reason == "relation"
