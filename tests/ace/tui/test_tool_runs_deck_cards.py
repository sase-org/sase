"""Tests for the tools-deck-cards phase (epic sase-1bt, sase-1bt.6).

The Tools deck gains two card hosts (``⚒ Runs`` first, then the
unchanged ``LLM Calls``) with per-card availability, the sticky
default-card rule, a switcher status segment, per-card detail levels,
and outcome-line run blocks.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.tool_runs import summaries as _summaries_module
from sase.ace.tui.tool_runs.deck import (
    DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    TOOLS_LLM_CALLS_CARD_ID,
    TOOLS_RUNS_CARD_ID,
    ToolRunsDetailLevel,
    _tools_switcher_text,
    coerce_tool_runs_detail_level,
    probe_tool_runs_card,
    tool_run_outcome_line,
    tool_runs_card_search_text,
    tools_card_ids,
    tools_default_card,
    tools_picker_label,
    tools_switcher_segment,
    tools_tabs,
    tools_truncated_line,
)
from sase.ace.tui.tool_runs.snapshot import (
    _build_snapshot,
    _set_snapshot,
)
from sase.ace.tui.tool_runs import snapshot as _snapshot_module
from sase.ace.tui.widgets.decks.availability import probe_tools_deck
from sase.ace.tui.widgets.decks.card_documents import (
    CARD_DOCUMENT_DECKS,
    resolve_document_deck,
)
from sase.ace.tui.widgets.decks.model import (
    DeckId,
    DeckView,
    DeckViewPolicies,
    cycle_card_id,
)
from sase.ace.tui.widgets.decks.tool_runs.document import build_tool_runs_document
from sase.ace.tui.widgets.decks.tool_runs.view import ToolRunsDeckView
from sase.ace.tui.widgets.llm_calls_panel import AgentLLMCallsPanel
from sase.core.tool_run import (
    ToolRunBrief,
    ToolRunGlance,
    ToolRunNodeSummary,
    ToolRunVerdictSummary,
)


def _verdict(bucket: str, **counts: Any) -> ToolRunVerdictSummary:
    return ToolRunVerdictSummary(
        bucket=bucket,
        new=int(counts.get("new", 0)),
        known=int(counts.get("known", 0)),
        unknown=int(counts.get("unknown", 0)),
    )


def _brief(
    run_id: str,
    label: str = "check",
    bucket: str = "pass",
    *,
    state: str = "succeeded",
    created_ts: int = 1000,
    settled_ts: int | None = 1500,
    duration_ms: int | None = 252000,
    typical_ms: int | None = 253000,
    agent: str | None = "0t9--code",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    terminal_cause: str | None = None,
    **counts: Any,
) -> ToolRunBrief:
    return ToolRunBrief(
        run_id=run_id,
        label=label,
        state=state,
        created_ts=created_ts,
        verdict=_verdict(bucket, **counts),
        tool_name="check",
        agent=agent,
        owner_kind=owner_kind,
        owner_id=owner_id,
        terminal_cause=terminal_cause,
        settled_ts=settled_ts,
        duration_ms=duration_ms,
        typical_ms=typical_ms,
    )


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


def _node(
    *,
    agent_name: str | None = "0t9--code",
    monitor_id: str | None = None,
    proc_id: str | None = None,
    remote: bool = False,
    clan: bool = False,
    agent_entry: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_name=agent_name,
        monitor_id=monitor_id,
        proc_id=proc_id,
        is_monitor=monitor_id is not None,
        is_named_proc=proc_id is not None,
        is_agent_session_container_row=False,
        is_agent_entry=agent_entry,
        is_clan_container=clan,
        fleet_origin_alias="fleet-machine" if remote else None,
        followup_agents=(),
        runtime_children=(),
        start_time=None,
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


def _store(selector: Any, summary: ToolRunNodeSummary) -> None:
    _summaries_module._store_node_summary(selector, "test-token", summary)


# Default-card rule: sticky wins, Runs when present, else LLM Calls.


def test_default_card_sticky_wins() -> None:
    ids = (TOOLS_RUNS_CARD_ID, TOOLS_LLM_CALLS_CARD_ID)
    assert tools_default_card(ids, TOOLS_LLM_CALLS_CARD_ID) == TOOLS_LLM_CALLS_CARD_ID
    assert tools_default_card(ids, TOOLS_RUNS_CARD_ID) == TOOLS_RUNS_CARD_ID


def test_default_card_runs_first_without_preference() -> None:
    ids = (TOOLS_RUNS_CARD_ID, TOOLS_LLM_CALLS_CARD_ID)
    assert tools_default_card(ids, None) == TOOLS_RUNS_CARD_ID
    assert tools_default_card(ids, "unknown-card") == TOOLS_RUNS_CARD_ID


def test_default_card_llm_calls_when_no_runs() -> None:
    assert tools_default_card((TOOLS_LLM_CALLS_CARD_ID,), None) == (
        TOOLS_LLM_CALLS_CARD_ID
    )
    assert tools_default_card((), None) is None


def test_card_ids_runs_first() -> None:
    assert tools_card_ids(True, True) == (TOOLS_RUNS_CARD_ID, TOOLS_LLM_CALLS_CARD_ID)
    assert tools_card_ids(False, True) == (TOOLS_LLM_CALLS_CARD_ID,)
    assert tools_card_ids(True, False) == (TOOLS_RUNS_CARD_ID,)


# Tabs: a no-runs node keeps a single LLM Calls tab; a monitor with
# runs and no calls shows Runs only.


def test_no_runs_node_keeps_single_llm_calls_tab() -> None:
    tabs = tools_tabs(False, True)
    assert [(tab.card_id, tab.title) for tab in tabs] == [
        (TOOLS_LLM_CALLS_CARD_ID, "LLM Calls")
    ]


def test_runs_only_node_shows_runs_only() -> None:
    tabs = tools_tabs(True, False)
    assert [(tab.card_id, tab.title) for tab in tabs] == [
        (TOOLS_RUNS_CARD_ID, "⚒ Runs")
    ]


def test_both_cards_tab_order_runs_first() -> None:
    tabs = tools_tabs(True, True)
    assert [tab.card_id for tab in tabs] == [
        TOOLS_RUNS_CARD_ID,
        TOOLS_LLM_CALLS_CARD_ID,
    ]


# Switcher segment never contains " · ".


def test_switcher_segment_never_contains_separator() -> None:
    cases = [
        _tools_switcher_text(0),
        _tools_switcher_text(1, 0),
        _tools_switcher_text(2, 57),
        _tools_switcher_text(1, 1),
        _tools_switcher_text(12, 300),
    ]
    assert _tools_switcher_text(2, 57) == "tools ⚒2 57"
    assert _tools_switcher_text(2) == "tools ⚒2"
    for text in cases:
        assert " · " not in text
    for live, silent in ((False, False), (True, False), (False, True)):
        segment = tools_switcher_segment(2, 57, live=live, silent=silent)
        assert " · " not in segment.plain


def test_picker_label_counts() -> None:
    assert tools_picker_label(2, 57) == "2 runs · 57 calls"
    assert tools_picker_label(1, 1) == "1 run · 1 call"
    assert tools_picker_label(2, None) == "2 runs"
    assert tools_picker_label(1, 0) == "1 run"
    assert tools_picker_label(0, 0) == "0 runs"
    assert tools_picker_label(None, 57) == "57 calls"
    assert tools_picker_label(None, None) == ""


# Ctrl+J/K round trip over the two Tools cards.


def test_ctrl_j_k_round_trip() -> None:
    ids = (TOOLS_RUNS_CARD_ID, TOOLS_LLM_CALLS_CARD_ID)
    assert cycle_card_id(ids, TOOLS_RUNS_CARD_ID, 1) == TOOLS_LLM_CALLS_CARD_ID
    assert cycle_card_id(ids, TOOLS_LLM_CALLS_CARD_ID, 1) == TOOLS_RUNS_CARD_ID
    assert cycle_card_id(ids, TOOLS_LLM_CALLS_CARD_ID, -1) == TOOLS_RUNS_CARD_ID


# Exhaustive per-deck dispatch: every DeckId has an arm.


def test_every_deck_id_has_a_document_arm() -> None:
    assert resolve_document_deck(DeckId.MAIN) is DeckId.MAIN
    assert resolve_document_deck(DeckId.FINAL) is DeckId.FINAL
    assert resolve_document_deck(DeckId.TOOLS) is DeckId.TOOLS
    assert resolve_document_deck(DeckId.FILES) is DeckId.MAIN


def test_tools_is_a_card_document_deck() -> None:
    assert DeckId.TOOLS in CARD_DOCUMENT_DECKS
    assert (DeckId.MAIN, DeckId.FINAL) == CARD_DOCUMENT_DECKS[:2]


# Tools stays paged-only: P is a no-op.


def test_tools_has_no_view_policy() -> None:
    policies = DeckViewPolicies()
    assert policies.for_deck(DeckId.TOOLS) is DeckView.AUTO
    try:
        policies.with_deck(DeckId.TOOLS, DeckView.SPREAD)
    except ValueError:
        pass
    else:
        raise AssertionError("Tools deck must reject a view policy")


# Outcome-line blocks: ( / ) on two runs, no rail on one.


def test_two_runs_navigate_blocks() -> None:
    runs = (
        _brief("a" * 32, bucket="new_failures", new=3, known=1, created_ts=1000),
        _brief("b" * 32, bucket="known_only", known=2, created_ts=2000),
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
    runs = (_brief("a" * 32, bucket="pass", created_ts=1000),)
    document = build_tool_runs_document(runs, subject=object(), digest="sig")
    card = document.cards[0]
    assert card.blocks == ()
    assert card.has_block_navigation is False
    assert "✓" in tool_run_outcome_line(runs[0]).plain


def test_empty_document_without_subject_or_runs() -> None:
    assert build_tool_runs_document((), subject=object(), digest="s").cards == ()
    assert (
        build_tool_runs_document((_brief("a" * 32),), subject=None, digest="s").cards
        == ()
    )


def test_truncated_card_says_so() -> None:
    runs = (
        _brief("a" * 32, created_ts=1000),
        _brief("b" * 32, created_ts=2000),
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
    new_failures = _brief("a" * 32, bucket="new_failures", new=3, known=1)
    assert "3 NEW · 1 KNOWN" in tool_run_outcome_line(new_failures).plain
    known_only = _brief("b" * 32, bucket="known_only", known=2)
    assert "known only" in tool_run_outcome_line(known_only).plain
    killed = _brief(
        "c" * 32,
        bucket="killed",
        state="killed",
        terminal_cause="signal",
        duration_ms=540000,
    )
    assert "killed at 9m00s · signal" in tool_run_outcome_line(killed).plain
    undetermined = _brief("d" * 32, bucket="undetermined")
    assert "untriaged" in tool_run_outcome_line(undetermined).plain
    live = _live_glance("e" * 32)
    assert "running" in tool_run_outcome_line(live).plain


def test_outcome_line_duration_and_settle_time() -> None:
    brief = _brief("a" * 32, bucket="pass")
    plain = tool_run_outcome_line(brief).plain
    assert "4m12s (typ 4m13s)" in plain
    assert "·" in plain


def test_search_finds_block_text() -> None:
    runs = (
        _brief("ab12cd34" * 4, bucket="new_failures", new=2, known=0),
        _brief("ef56ab78" * 4, bucket="pass"),
    )
    document = build_tool_runs_document(runs, subject=object(), digest="s")
    assert len(document.cards) == 1
    text = tool_runs_card_search_text(document.cards[0].renderables)
    assert "2 NEW" in text
    assert "pass" in text
    assert tool_runs_card_search_text(()) == ""


def test_block_meta_rail_facts() -> None:
    from sase.ace.tui.tool_runs.deck import tool_run_block_meta

    meta = tool_run_block_meta(0, _brief("a" * 32, label="lint", bucket="killed"))
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


# Availability: per-card merge, monitor/proc opening, first-load None.


def test_probe_pinned_attempt_has_no_runs() -> None:
    assert probe_tool_runs_card(_node(), attempt_number=3) == (False, 0)


def test_probe_remote_and_clan_have_no_runs() -> None:
    assert probe_tool_runs_card(_node(remote=True)) == (False, 0)
    assert probe_tool_runs_card(_node(clan=True)) == (False, 0)


def test_probe_unknown_history_is_none_before_first_load() -> None:
    assert probe_tool_runs_card(_node()) == (None, 0)


def test_probe_reads_cached_history_without_io() -> None:
    from sase.ace.tui.tool_runs.summaries import selector_for_agent

    agent = _node()
    selector = selector_for_agent(agent)
    assert selector is not None
    _store(
        selector,
        ToolRunNodeSummary(
            key=selector.key,
            total_runs=2,
            runs=(
                _brief("a" * 32, created_ts=1000),
                _brief("b" * 32, created_ts=2000),
            ),
        ),
    )
    assert probe_tool_runs_card(agent) == (True, 2)


def test_probe_opens_for_monitor_owned_runs() -> None:
    agent = _node(agent_name=None, monitor_id="mon-1", agent_entry=False)
    from sase.ace.tui.tool_runs.summaries import selector_for_agent

    selector = selector_for_agent(agent)
    assert selector is not None
    assert selector.owners == (("monitor", "mon-1"),)
    _store(
        selector,
        ToolRunNodeSummary(
            key=selector.key,
            total_runs=1,
            runs=(
                _brief(
                    "c" * 32,
                    agent="starter-turn",
                    owner_kind="monitor",
                    owner_id="mon-1",
                ),
            ),
        ),
    )
    assert probe_tool_runs_card(agent) == (True, 1)
    availability = probe_tools_deck(agent, attempt_number=None)
    assert availability.has_content is True
    assert availability.runs_count == 1
    assert availability.calls_count == 0


def _deck_panel() -> object:
    from types import SimpleNamespace

    panel = SimpleNamespace()
    panel.selected: list[str] = []
    panel.cards_shown: list[str] = []
    panel.select_block = lambda block_id: panel.selected.append(block_id) or True  # type: ignore[attr-defined]
    panel._show_tools_card = lambda card_id: (
        panel.cards_shown.append(card_id) or card_id
    )  # type: ignore[attr-defined]
    panel._tool_runs_document = SimpleNamespace(cards=[SimpleNamespace(blocks=[1, 2])])
    panel._availability = {}
    return panel


def _deck_app(selected_identity: object) -> object:
    from types import SimpleNamespace

    app = SimpleNamespace()
    app._pending_tool_run_block = None
    selected = SimpleNamespace(identity=selected_identity)
    app._get_selected_agent = lambda: selected  # type: ignore[attr-defined]
    app._panels: list[object] = []
    app._test_tool_run_panels = app._panels
    app.action_show_tool_runs_card = lambda: None  # type: ignore[attr-defined]
    return app


def test_pending_selection_applies_after_document_loads() -> None:
    from sase.ace.tui.tool_runs.reveal import apply_pending_tool_run_select

    app = _deck_app(("agent", "a", ""))
    panel = _deck_panel()
    app._panels.append(panel)  # type: ignore[attr-defined]
    app._pending_tool_run_block = {"run_id": "a" * 32, "identity": ("agent", "a", "")}  # type: ignore[attr-defined]
    assert apply_pending_tool_run_select(app, panel, n_runs=2) is True
    assert panel.selected == ["a" * 32]  # type: ignore[attr-defined]
    assert app._pending_tool_run_block is None  # type: ignore[attr-defined]


def test_pending_selection_dropped_on_node_change() -> None:
    from sase.ace.tui.tool_runs.reveal import apply_pending_tool_run_select

    app = _deck_app(("agent", "b", ""))
    panel = _deck_panel()
    app._pending_tool_run_block = {"run_id": "a" * 32, "identity": ("agent", "a", "")}  # type: ignore[attr-defined]
    assert apply_pending_tool_run_select(app, panel, n_runs=2) is False
    assert app._pending_tool_run_block is None  # type: ignore[attr-defined]
    assert panel.selected == []  # type: ignore[attr-defined]


def test_single_run_document_counts_as_success() -> None:
    from sase.ace.tui.tool_runs.reveal import apply_pending_tool_run_select
    from types import SimpleNamespace

    app = _deck_app(("agent", "a", ""))
    panel = SimpleNamespace()
    panel.selected: list[str] = []
    panel.select_block = lambda block_id: False  # type: ignore[attr-defined]
    panel._show_tools_card = lambda card_id: card_id  # type: ignore[attr-defined]
    panel._tool_runs_document = SimpleNamespace(cards=[SimpleNamespace(blocks=[])])
    panel._availability = {}
    app._pending_tool_run_block = {"run_id": "a" * 32, "identity": ("agent", "a", "")}  # type: ignore[attr-defined]
    assert apply_pending_tool_run_select(app, panel, n_runs=1) is True
    assert app._pending_tool_run_block is None  # type: ignore[attr-defined]
