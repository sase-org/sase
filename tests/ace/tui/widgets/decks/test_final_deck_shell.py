"""Shell coverage for the ⊛ FINAL deck (epic sase-1b2, bead sase-1b2.14).

Covers registration (spec, gated cycle, chrome, subtitle), the no-I/O
availability probe, the off-thread loader's signature cache and stale
rejection, the default-card rule, sticky per-deck cards, persistence, and
the cross-epic deck-view exclusions (FINAL is permanently AUTO: no badge,
no ``P``, no persisted view key).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.decks.availability import (
    DeckAvailability,
    probe_final_deck,
)
from sase.ace.tui.widgets.decks.final.document import (
    FINAL_OVERVIEW_CARD_ID,
    build_final_deck_document,
    decide_final_mode,
    final_default_card,
    final_instance_card_id,
)
from sase.ace.tui.widgets.decks.final.loader import (
    FinalDeckLoadResult,
    clear_final_cache,
    load_final_deck,
)
from sase.ace.tui.widgets.decks.model import (
    DeckId,
    DeckView,
    DeckViewPolicies,
    RenderMode,
    with_preferred_card,
    SINGLE,
)
from sase.ace.tui.widgets.decks.titles import (
    deck_subtitle,
    deck_title,
    final_switcher_segment,
)
from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping


def _agent(*, status: str = "RUNNING", summary: dict | None = None) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-code",
        project_file="/tmp/p.sase",
        status=status,
        start_time=datetime(2026, 9, 27, 7, 30, 0),
        raw_suffix="20260927073000-code",
    )
    agent.finalizer_status = (
        finalizer_status_from_mapping(summary) if summary is not None else None
    )
    return agent


_EXECUTING = {
    "schema_version": 1,
    "phase": "executing",
    "instances": [{"id": "commit", "status": "running"}],
}

_SETTLED = {
    "schema_version": 1,
    "phase": "settled",
    "instances": [
        {"id": "commit", "status": "success"},
        {"id": "check", "status": "failed"},
    ],
}

_SKIPPED = {"schema_version": 1, "phase": "skipped", "instances": []}


def _node_view(
    *,
    status: str = "failed",
    glyph: str = "✗",
    instances: list[dict] | None = None,
    trouble: bool = True,
    attention: str | None = "check",
) -> SimpleNamespace:
    rows = [
        SimpleNamespace(
            instance_id=item["id"],
            status=item["status"],
            provider_ref=None,
            selection_reason="default",
        )
        for item in (
            instances
            if instances is not None
            else [{"id": "check", "status": "failed"}]
        )
    ]
    return SimpleNamespace(
        status=status,
        glyph=glyph,
        run_level_trouble=trouble,
        instances=rows,
        unselected=[],
        attention_instance_id=attention,
    )


# -- Registration ------------------------------------------------------


def test_final_picker_key_is_n_and_free() -> None:
    from sase.ace.tui.widgets.decks.spec import deck_spec
    from sase.ace.tui.widgets.decks.titles import (
        DECK_PICKER_KEYS,
        DECK_PICKER_RESERVED_KEYS,
    )

    assert deck_spec(DeckId.FINAL).picker_key == "n"
    assert DECK_PICKER_KEYS[DeckId.FINAL] == "n"
    assert "n" not in DECK_PICKER_RESERVED_KEYS


def test_final_joins_picker_rows() -> None:
    from sase.ace.tui.widgets.decks.picker import (
        DeckPickerState,
        build_deck_picker_rows,
    )

    availability = {
        DeckId.MAIN: DeckAvailability(True, 1),
        DeckId.FILES: DeckAvailability(False, 0),
        DeckId.TOOLS: DeckAvailability(False, 0),
        DeckId.FINAL: DeckAvailability(False, 0),
    }
    accents = dict.fromkeys(DeckId, "")
    state = DeckPickerState(
        panel_index=0,
        panel_label="deck",
        current=DeckId.MAIN,
        other=None,
        availability=availability,
        accents=accents,
    )
    rows = build_deck_picker_rows(state)
    assert [row.deck for row in rows] == [
        DeckId.MAIN,
        DeckId.FILES,
        DeckId.TOOLS,
        DeckId.FINAL,
    ]
    final_row = rows[-1]
    assert final_row.key == "n"
    assert final_row.has_content is False


# -- Deck-view exclusions (cross-epic R1/R2) -----------------------------


def test_final_has_no_view_policy() -> None:
    policies = DeckViewPolicies()
    assert policies.for_deck(DeckId.FINAL) is DeckView.AUTO
    with pytest.raises(ValueError):
        policies.with_deck(DeckId.FINAL, DeckView.SPREAD)
    with pytest.raises(ValueError):
        policies.with_deck(DeckId.FINAL, DeckView.AUTO)


def test_final_offers_no_view_layouts() -> None:
    from sase.ace.tui.widgets.decks.view_policy import ViewContent, _distinct_layouts

    assert _distinct_layouts(ViewContent(DeckId.FINAL, 3, 2)) == ()


def test_headless_final_panel_reports_no_view_cycle() -> None:
    from sase.ace.tui.widgets.decks.panel import DeckPanel

    panel = DeckPanel(0)
    panel._deck = DeckId.FINAL
    assert panel.view_policy(DeckId.FINAL) is DeckView.AUTO
    assert panel.next_view() is None
    assert panel.deck_view_cycle_available is False
    assert panel.view_content(DeckId.FINAL).card_count == 0


def test_view_cycle_on_main_does_not_disturb_final_sticky() -> None:
    state = with_preferred_card(SINGLE, 0, "reply", DeckId.MAIN)
    state = with_preferred_card(state, 0, "instance:check", DeckId.FINAL)
    assert state.panels[0].preferred_card_for(DeckId.MAIN) == "reply"
    assert state.panels[0].preferred_card_for(DeckId.FINAL) == "instance:check"
    moved = with_preferred_card(state, 0, "context", DeckId.MAIN)
    assert moved.panels[0].preferred_card_for(DeckId.MAIN) == "context"
    assert moved.panels[0].preferred_card_for(DeckId.FINAL) == "instance:check"


# -- Default-card rule ---------------------------------------------------


def test_final_default_card_order() -> None:
    ids = ("overview", "instance:commit", "instance:check")
    assert (
        final_default_card(
            ids,
            "instance:check",
            attention_instance_id="commit",
            run_level_trouble=True,
        )
        == "instance:check"
    )
    assert (
        final_default_card(
            ids, None, attention_instance_id="commit", run_level_trouble=True
        )
        == "instance:commit"
    )
    assert (
        final_default_card(
            ids, "instance:gone", attention_instance_id=None, run_level_trouble=True
        )
        == "overview"
    )
    assert (
        final_default_card(
            ids, None, attention_instance_id=None, run_level_trouble=False
        )
        == "instance:commit"
    )
    assert (
        final_default_card((), None, attention_instance_id=None, run_level_trouble=True)
        is None
    )


def test_decide_final_mode_spreads_lone_cards() -> None:
    assert decide_final_mode(0) is RenderMode.SPREAD
    assert decide_final_mode(1) is RenderMode.SPREAD
    assert decide_final_mode(3) is RenderMode.PAGED


# -- Document builder ----------------------------------------------------


def test_final_document_has_overview_plus_instance_cards() -> None:
    document = build_final_deck_document(_node_view(), subject="agent:1", digest="sig")
    assert document.card_ids == ("overview", "instance:check")
    overview = document.card("overview")
    assert overview is not None
    assert overview.title == "Overview"
    check = document.card("instance:check")
    assert check is not None
    assert check.title == "check ✗"


def test_final_document_empty_without_subject_or_view() -> None:
    assert (
        build_final_deck_document(_node_view(), subject=None, digest=None).cards == ()
    )
    assert build_final_deck_document(None, subject="agent:1", digest=None).cards == ()


# -- Availability probe --------------------------------------------------


def test_probe_final_counts_selected_instances() -> None:
    assert probe_final_deck(
        _agent(summary=_SETTLED), attempt_number=None
    ) == DeckAvailability(True, 2)


def test_probe_final_counts_skipped_runs() -> None:
    assert probe_final_deck(
        _agent(summary=_SKIPPED), attempt_number=None
    ) == DeckAvailability(True, 0)


def test_probe_final_legacy_run_is_unavailable() -> None:
    assert probe_final_deck(
        _agent(status="DONE", summary=None), attempt_number=None
    ) == DeckAvailability(False, 0)


def test_probe_final_active_run_without_summary_is_unknown() -> None:
    assert probe_final_deck(
        _agent(status="RUNNING", summary=None), attempt_number=None
    ) == DeckAvailability(None, None)


def test_probe_final_follows_pinned_attempt_summaries() -> None:
    assert probe_final_deck(
        _agent(summary=_EXECUTING), attempt_number=2
    ) == DeckAvailability(True, 1)


# -- Chrome: tabs and subtitle -------------------------------------------


def test_final_tabs_double_as_status_strip() -> None:
    from sase.ace.tui.widgets.decks.panel import DeckPanel

    panel = DeckPanel(0)
    document = build_final_deck_document(
        _node_view(
            instances=[
                {"id": "commit", "status": "success"},
                {"id": "check", "status": "failed"},
            ]
        ),
        subject="agent:1",
        digest="sig",
    )
    panel.show_final_document(document, None, status="failed", glyph="✗")
    tabs = panel._final_tabs()
    assert [(tab.card_id, tab.title) for tab in tabs] == [
        ("overview", "Overview"),
        ("instance:commit", "commit ✓"),
        ("instance:check", "check ✗"),
    ]
    assert panel._final_switcher is not None
    assert panel._final_switcher.plain == "final ✗"


def test_final_switcher_segment_colors() -> None:
    assert final_switcher_segment("failed", "✗").plain == "final ✗"
    assert "bold" in str(final_switcher_segment("failed", "✗").style)
    assert final_switcher_segment(None, None).plain == "final ⊛"
    assert final_switcher_segment("bogus", None).plain == "final ⊛"


def test_subtitle_shows_final_status_segment() -> None:
    availability = {
        DeckId.MAIN: DeckAvailability(True, 1),
        DeckId.FILES: DeckAvailability(False, 0),
        DeckId.TOOLS: DeckAvailability(False, 0),
        DeckId.FINAL: DeckAvailability(True, 1),
    }
    accents = {
        DeckId.MAIN: "red",
        DeckId.FILES: "green",
        DeckId.TOOLS: "#87D7FF",
        DeckId.FINAL: "#FF87D7",
    }
    rendered = deck_subtitle(
        DeckId.MAIN,
        availability,
        status=None,
        width=80,
        accent_for=accents,
        status_segments={DeckId.FINAL: final_switcher_segment("failed", "✗")},
    )
    assert "final ✗" in rendered.plain
    assert "final 1" not in rendered.plain


def test_final_title_uses_compact_rungs_over_four_tabs() -> None:
    from sase.ace.tui.widgets.decks.titles import CardTab

    tabs = tuple(CardTab(f"instance:{i}", f"c{i} ✓") for i in range(6))
    wide = deck_title(DeckId.FINAL, tabs, 0, width=200, accent="red", focused=True)
    assert "1/6" in wide.plain and "c0 ✓" in wide.plain and "c5 ✓" not in wide.plain
    narrow = deck_title(DeckId.FINAL, tabs, 0, width=40, accent="red", focused=True)
    assert "1/6" in narrow.plain
    few = tuple(CardTab(f"instance:{i}", f"c{i} ✓") for i in range(4))
    full = deck_title(DeckId.FINAL, few, 0, width=200, accent="red", focused=True)
    assert "c0 ✓" in full.plain and "c3 ✓" in full.plain


# -- Loader: signature cache and stale rejection --------------------------


def test_loader_signature_cache_skips_reprojection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.widgets.decks.final.loader as loader_module

    clear_final_cache()
    calls = 0

    def _fake_project(targets: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return _node_view()

    monkeypatch.setattr(loader_module, "project_node_view", _fake_project)
    first = load_final_deck(
        (), subject="agent:1", subject_identity="agent:1", generation=3
    )
    second = load_final_deck(
        (), subject="agent:1", subject_identity="agent:1", generation=4
    )
    assert calls == 1
    assert isinstance(first, FinalDeckLoadResult)
    assert second.generation == 4
    assert second.signature == first.signature
    assert second.document.card_ids == ("overview", "instance:check")
    assert second.default_card == final_instance_card_id("check")
    clear_final_cache()


def test_final_view_rejects_stale_subject_and_generation() -> None:
    from sase.ace.tui.widgets.decks.final.view import FinalDeckView

    view = FinalDeckView()
    view._current_subject_identity = "agent:1"
    view._current_generation = 7
    stale_subject = SimpleNamespace(subject_identity="agent:2", generation=7)
    stale_generation = SimpleNamespace(subject_identity="agent:1", generation=6)
    current = SimpleNamespace(subject_identity="agent:1", generation=7)
    assert view._is_stale_result(stale_subject) is True
    assert view._is_stale_result(stale_generation) is True
    assert view._is_stale_result(current) is False


# -- Persistence -----------------------------------------------------------


def test_final_panel_round_trips(tmp_path) -> None:
    from sase.ace.tui.models.agent_deck_persistence import (
        load_agents_deck_state,
        save_agents_deck_state,
    )

    import json

    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [
                    {
                        "deck": "final",
                        "preferred_cards": {
                            "main": "reply",
                            "final": "instance:check",
                        },
                        "views": {"main": "auto", "files": "auto"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].deck is DeckId.FINAL
    assert loaded.panels[0].preferred_cards == {
        DeckId.MAIN: "reply",
        DeckId.FINAL: "instance:check",
    }
    save_agents_deck_state(loaded, path)
    assert load_agents_deck_state(path) == loaded


# -- Receipt hint ------------------------------------------------------------


def test_receipt_shows_open_hint() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_finalizer_receipt import (
        finalizer_receipt_text,
    )

    agent = _agent(summary=_SETTLED)
    receipt = finalizer_receipt_text(agent)
    assert receipt is not None
    assert "p n  open FINAL deck" in receipt.plain


def test_instance_card_id_prefix_avoids_overview_collision() -> None:
    assert final_instance_card_id("overview") == "instance:overview"
    assert final_instance_card_id("overview") != FINAL_OVERVIEW_CARD_ID


def test_loaded_message_updates_panel_tabs_and_switcher() -> None:
    from sase.ace.tui.widgets.decks.final.view import FinalDeckLoaded
    from sase.ace.tui.widgets.decks.panel import DeckPanel

    panel = DeckPanel(0)
    panel._deck = DeckId.FINAL
    document = build_final_deck_document(_node_view(), subject="agent:1", digest="sig")
    message = FinalDeckLoaded(
        document,
        status="failed",
        glyph="✗",
        signature="sig",
        active_card="instance:check",
    )
    panel.handle_final_deck_loaded(message)
    assert panel._final_document is document
    assert panel._final_switcher is not None
    assert panel._final_switcher.plain == "final ✗"
    tabs = panel._final_tabs()
    assert [tab.title for tab in tabs] == ["Overview", "check ✗"]
