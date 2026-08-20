"""Word-ranking mode tests for prompt-history word completion."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionMetadata,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.history.prompt_word_index import _parse_sase_timestamp_epoch

from ._history_word_completion_helpers import (
    HistoryCompletionTestApp,
    RankedHistoryCompletionTestApp,
    seeded_index,
    skip_unrelated_vcs_catalog_warm,  # noqa: F401 (registers the autouse fixture)
)


async def test_recent_mode_candidates_carry_no_ranking_metadata() -> None:
    app = HistoryCompletionTestApp(["review", "revise"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("re")
        ta.cursor_location = (0, 2)

        await pilot.press("ctrl+t")

        assert app.settings.word_ranking == "recent"
        assert all(
            candidate.metadata is None for candidate in ta._file_completion_candidates
        )


async def test_smart_ranking_prefers_related_word_over_more_recent_unrelated_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors the ranking-engine scenario, wired end to end through Ctrl+T."""
    now = _parse_sase_timestamp_epoch("260801_000000")
    monkeypatch.setattr(
        "sase.ace.tui.widgets._file_completion_history.time.time",
        lambda: now,
    )
    index = seeded_index(
        [
            ("render fresh0", "260730_000000"),
            ("monitor reconcile related0", "260701_000000"),
            ("monitor reconcile related1", "260630_000000"),
            *[
                (f"background{i} filler{i}", f"2606{20 - i:02d}_000000")
                for i in range(9)
            ],
        ]
    )
    app = RankedHistoryCompletionTestApp(index)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("please monitor re")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta._completion_kind == HISTORY_WORD_COMPLETION_KIND
        insertions = [
            candidate.insertion for candidate in ta._file_completion_candidates
        ]
        assert insertions[:2] == ["reconcile", "render"]
        top = ta._file_completion_candidates[0]
        assert isinstance(top.metadata, HistoryWordCompletionMetadata)
        assert top.metadata.reason == "relation"
        assert top.metadata.related_to == "monitor"


async def test_smart_mode_mid_word_completion_preserves_suffix() -> None:
    index = seeded_index([("foobar", "260814_000000")])
    app = RankedHistoryCompletionTestApp(index)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("foobaz")
        ta.cursor_location = (0, len("foo"))

        await pilot.press("ctrl+t")

        assert ta.text == "foobar baz"
        assert ta.cursor_location == (0, len("foobar"))
        assert ta._file_completion_active is False
