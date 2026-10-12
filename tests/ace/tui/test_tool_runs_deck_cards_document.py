"""Document, outcome-line, search, and detail-level deck-cards tests."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.tool_runs import summaries as _summaries_module
from sase.ace.tui.tool_runs.deck import (
    DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    TOOLS_RUNS_CARD_ID,
    ToolRunsDetailLevel,
    coerce_tool_runs_detail_level,
    tool_run_outcome_line,
    tool_runs_card_search_text,
    tools_truncated_line,
)
from sase.ace.tui.tool_runs.snapshot import _set_snapshot
from sase.ace.tui.tool_runs import snapshot as _snapshot_module
from sase.ace.tui.widgets.decks.tool_runs.document import build_tool_runs_document
from sase.ace.tui.widgets.decks.tool_runs.view import ToolRunsDeckView
from sase.ace.tui.widgets.llm_calls_panel import AgentLLMCallsPanel
from sase.core.tool_run import ToolRunGlance
from tests.ace.tui._tool_runs_deck_cards_shared import make_brief

__all__ = [
    "setup_function",
    "teardown_function",
    "test_block_meta_rail_facts",
    "test_detail_levels_are_independent_per_card",
    "test_empty_document_without_subject_or_runs",
    "test_outcome_line_duration_and_settle_time",
    "test_outcome_line_words",
    "test_runs_detail_level_defaults_standard",
    "test_search_finds_block_text",
    "test_single_run_is_block_less_with_no_rail",
    "test_truncated_card_says_so",
    "test_two_runs_navigate_blocks",
]


def _live_glance(run_id: str, **kwargs: Any) -> ToolRunGlance:
    return ToolRunGlance(
        run_id=run_id,
        label=kwargs.get("label", "check"),
        state=kwargs.get("state", "running"),
        created_ts=kwargs.get("created_ts", 1000),
        last_activity_ts=kwargs.get("last_activity_ts", 1000),
        agent=kwargs.get("agent"),
        owner_kind=kwargs.get("owner_kind"),
        owner_id=kwargs.get("owner_id"),
    )


def setup_function(_: object) -> None:
    _set_snapshot(None)
    _snapshot_module._TOOL_RUNS_DISABLED_REASON = None
    _snapshot_module._TOOL_RUNS_DISABLED_LOGGED = False
    with _summaries_module._summary_lock:
        _summaries_module._summary_lru.clear()


def teardown_function(_: object) -> None:
    _set_snapshot(None)
    with _summaries_module._summary_lock:
        _summaries_module._summary_lru.clear()


# Outcome-line blocks: ( / ) on two runs, no rail on one.


def test_two_runs_navigate_blocks() -> None:
    runs = (
        make_brief("a" * 32, bucket="new_failures", new=3, known=1, created_ts=1000),
        make_brief("b" * 32, bucket="known_only", known=2, created_ts=2000),
    )
    document = build_tool_runs_document(runs, subject=object(), digest="sig")
    assert len(document.cards) == 1
    card = document.cards[0]
    assert card.card_id == TOOLS_RUNS_CARD_ID
    assert card.title == "⚒ Runs"
    assert card.has_block_navigation is True
    assert card.block_ids == ("a" * 32, "b" * 32)
    first, second = card.blocks
    assert first.meta.number == "1"
    assert first.meta.label == "check"
    assert first.meta.kind == "tool_run"
    assert first.meta.status_bucket == "new_failures"
    assert second.meta.number == "2"
    assert second.meta.status_bucket == "known_only"


def test_single_run_is_block_less_with_no_rail() -> None:
    runs = (make_brief("a" * 32, bucket="pass", created_ts=1000),)
    document = build_tool_runs_document(runs, subject=object(), digest="sig")
    card = document.cards[0]
    assert card.blocks == ()
    assert card.has_block_navigation is False
    assert "✓" in tool_run_outcome_line(runs[0]).plain


def test_empty_document_without_subject_or_runs() -> None:
    assert build_tool_runs_document((), subject=object(), digest="s").cards == ()
    assert (
        build_tool_runs_document(
            (make_brief("a" * 32),), subject=None, digest="s"
        ).cards
        == ()
    )


def test_truncated_card_says_so() -> None:
    runs = (
        make_brief("a" * 32, created_ts=1000),
        make_brief("b" * 32, created_ts=2000),
    )
    document = build_tool_runs_document(
        runs, subject=object(), digest="s", total_runs=3, truncated=True
    )
    card = document.cards[0]
    assert tools_truncated_line(1) == "+1 older runs · Admin Center → Tools"
    assert any("+1 older runs" in getattr(part, "plain", "") for part in card.preamble)
    assert len(card.blocks) == 2


# Outcome-line words per bucket.


def test_outcome_line_words() -> None:
    new_failures = make_brief("a" * 32, bucket="new_failures", new=3, known=1)
    assert "3 NEW · 1 KNOWN" in tool_run_outcome_line(new_failures).plain
    known_only = make_brief("b" * 32, bucket="known_only", known=2)
    assert "known only" in tool_run_outcome_line(known_only).plain
    killed = make_brief(
        "c" * 32,
        bucket="killed",
        state="killed",
        terminal_cause="signal",
        duration_ms=540000,
    )
    assert "killed at 9m00s · signal" in tool_run_outcome_line(killed).plain
    undetermined = make_brief("d" * 32, bucket="undetermined")
    assert "untriaged" in tool_run_outcome_line(undetermined).plain
    live = _live_glance("e" * 32)
    assert "running" in tool_run_outcome_line(live).plain


def test_outcome_line_duration_and_settle_time() -> None:
    brief = make_brief("a" * 32, bucket="pass")
    plain = tool_run_outcome_line(brief).plain
    assert "4m12s (typ 4m13s)" in plain
    assert "·" in plain


def test_search_finds_block_text() -> None:
    runs = (
        make_brief("ab12cd34" * 4, bucket="new_failures", new=2, known=0),
        make_brief("ef56ab78" * 4, bucket="pass"),
    )
    document = build_tool_runs_document(runs, subject=object(), digest="s")
    assert len(document.cards) == 1
    text = tool_runs_card_search_text(document.cards[0].renderables)
    assert "2 NEW" in text
    assert "pass" in text
    assert tool_runs_card_search_text(()) == ""


def test_block_meta_rail_facts() -> None:
    from sase.ace.tui.tool_runs.deck import tool_run_block_meta

    meta = tool_run_block_meta(0, make_brief("a" * 32, label="lint", bucket="killed"))
    assert (meta.number, meta.label, meta.glyph, meta.kind) == (
        "1",
        "lint",
        "⊘",
        "tool_run",
    )


# Detail levels: h/l on Runs leaves LLM Calls unchanged and vice versa.


def test_runs_detail_level_defaults_standard() -> None:
    assert DEFAULT_TOOL_RUNS_DETAIL_LEVEL == ToolRunsDetailLevel.STANDARD
    assert coerce_tool_runs_detail_level(object()) == ToolRunsDetailLevel.STANDARD
    view = ToolRunsDeckView()
    assert view.detail_level == ToolRunsDetailLevel.STANDARD


def test_detail_levels_are_independent_per_card() -> None:
    runs_view = ToolRunsDeckView()
    calls_panel = AgentLLMCallsPanel()
    assert runs_view.expand_detail() is True
    assert runs_view.detail_level == ToolRunsDetailLevel.FULL
    assert calls_panel.detail_level.value == 0
    assert calls_panel.set_detail_level(2, rerender=False) is True
    assert runs_view.collapse_detail() is True
    assert runs_view.detail_level == ToolRunsDetailLevel.STANDARD
    assert calls_panel.detail_level.value == 2
