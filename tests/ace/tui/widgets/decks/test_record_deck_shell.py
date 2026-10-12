"""Shell coverage for the ≡ RECORD deck (epic sase-1jm.4.2, ``shell``).

Covers registration (spec last in cycle, chrome, subtitle), the
always-available probe, the off-thread loader's signature cache and
stale rejection, the default-card rule, sticky per-deck cards,
persistence (plus a state without it), never auto-choosing RECORD on
split, and a RECORD header never showing other decks' content.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.decks.availability import (
    DeckAvailability,
    probe_record_deck,
)
from sase.ace.tui.widgets.decks.layout import choose_new_panel
from sase.ace.tui.widgets.decks.model import (
    DeckId,
    DeckView,
    DeckViewPolicies,
    RenderMode,
    with_preferred_card,
    SINGLE,
)
from sase.ace.tui.widgets.decks.record.document import (
    RECORD_LIFECYCLE_CARD_ID,
    build_record_document,
    decide_record_mode,
    record_default_card,
)
from sase.ace.tui.widgets.decks.record.loader import (
    RecordDeckLoadResult,
    clear_record_cache,
    load_record_deck,
)
from sase.ace.tui.widgets.decks.record.model import (
    RecordSubject,
    live_related_names,
    record_subject_from_agent,
)


def _agent(**overrides: object) -> Agent:
    kwargs: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "demo-code",
        "project_file": "/tmp/p.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 9, 27, 7, 30, 0),
        "raw_suffix": "20260927073000-code",
    }
    kwargs.update(overrides)
    return Agent(**kwargs)  # type: ignore[arg-type]


def _subject(**overrides: object) -> RecordSubject:
    base = record_subject_from_agent(_agent())
    if not overrides:
        return base
    import dataclasses

    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


# -- Registration ------------------------------------------------------


def test_record_picker_key_is_r_and_free() -> None:
    from sase.ace.tui.widgets.decks.spec import deck_spec
    from sase.ace.tui.widgets.decks.titles import (
        DECK_PICKER_KEYS,
        DECK_PICKER_RESERVED_KEYS,
    )

    assert deck_spec(DeckId.RECORD).picker_key == "r"
    assert DECK_PICKER_KEYS[DeckId.RECORD] == "r"
    assert "r" not in DECK_PICKER_RESERVED_KEYS


def test_record_is_last_in_cycle() -> None:
    from sase.ace.tui.widgets.decks.spec import active_deck_cycle

    assert active_deck_cycle()[-1] is DeckId.RECORD
    assert active_deck_cycle() == (
        DeckId.MAIN,
        DeckId.FILES,
        DeckId.TOOLS,
        DeckId.FINAL,
        DeckId.RECORD,
    )


def test_record_joins_picker_rows_last() -> None:
    from sase.ace.tui.widgets.decks.picker import (
        DeckPickerState,
        build_deck_picker_rows,
    )

    availability = {
        DeckId.MAIN: DeckAvailability(True, 1),
        DeckId.FILES: DeckAvailability(False, 0),
        DeckId.TOOLS: DeckAvailability(False, 0),
        DeckId.FINAL: DeckAvailability(False, 0),
        DeckId.RECORD: DeckAvailability(True, None),
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
        DeckId.RECORD,
    ]
    record_row = rows[-1]
    assert record_row.key == "r"
    assert record_row.has_content is True
    assert record_row.count_label == ""


# -- Deck-view exclusions -------------------------------------------------


def test_record_has_no_view_policy() -> None:
    policies = DeckViewPolicies()
    assert policies.for_deck(DeckId.RECORD) is DeckView.AUTO
    with pytest.raises(ValueError):
        policies.with_deck(DeckId.RECORD, DeckView.SPREAD)
    with pytest.raises(ValueError):
        policies.with_deck(DeckId.RECORD, DeckView.AUTO)


def test_record_offers_no_view_layouts() -> None:
    from sase.ace.tui.widgets.decks.view_policy import ViewContent, _distinct_layouts

    assert _distinct_layouts(ViewContent(DeckId.RECORD, 4, 2)) == ()


def test_view_cycle_on_main_does_not_disturb_record_sticky() -> None:
    state = with_preferred_card(SINGLE, 0, "reply", DeckId.MAIN)
    state = with_preferred_card(state, 0, "relations", DeckId.RECORD)
    assert state.panels[0].preferred_card_for(DeckId.MAIN) == "reply"
    assert state.panels[0].preferred_card_for(DeckId.RECORD) == "relations"
    moved = with_preferred_card(state, 0, "context", DeckId.MAIN)
    assert moved.panels[0].preferred_card_for(DeckId.MAIN) == "context"
    assert moved.panels[0].preferred_card_for(DeckId.RECORD) == "relations"


# -- Never auto-choose RECORD --------------------------------------------


def test_new_split_never_auto_chooses_record() -> None:
    for current in DeckId:
        chosen = choose_new_panel(
            current,
            None,
            set(),
            dict.fromkeys(DeckId, True),
            ("context",),
        )
        assert chosen.deck is not DeckId.RECORD


def test_record_unreachable_only_explicitly_but_cyclable() -> None:
    from sase.ace.tui.widgets.decks.model import cycle_deck_id

    assert cycle_deck_id(DeckId.FINAL, 1) is DeckId.RECORD
    assert cycle_deck_id(DeckId.RECORD, 1) is DeckId.MAIN


# -- Default-card rule ---------------------------------------------------


def test_record_default_card_order() -> None:
    ids = ("lifecycle", "provenance", "relations", "links")
    assert record_default_card(ids, "relations") == "relations"
    assert record_default_card(ids, None) == "lifecycle"
    assert record_default_card(ids, "gone") == "lifecycle"
    assert record_default_card(("relations",), None) == "relations"
    assert record_default_card((), None) is None


def test_decide_record_mode_spreads_lone_cards() -> None:
    assert decide_record_mode(0) is RenderMode.SPREAD
    assert decide_record_mode(1) is RenderMode.SPREAD
    assert decide_record_mode(4) is RenderMode.PAGED


# -- Document builder ----------------------------------------------------


def test_record_document_has_four_cards_in_fixed_order() -> None:
    document = build_record_document(_subject(), None, None)
    assert document.card_ids == (
        "lifecycle",
        "provenance",
        "relations",
        "links",
    )
    assert [card.title for card in document.cards] == [
        "Lifecycle",
        "Provenance",
        "Relations",
        "Links",
    ]


def test_record_document_empty_without_subject() -> None:
    assert build_record_document(None, None, None).cards == ()


def test_stub_cards_carry_agent_facts() -> None:
    agent = _agent(agent_name="athena", status="DONE")
    document = build_record_document(record_subject_from_agent(agent), None, None)
    lifecycle = document.card("lifecycle")
    assert lifecycle is not None
    from sase.ace.tui.widgets.renderable_text import renderable_to_text
    from rich.console import Group

    text = renderable_to_text(Group(*lifecycle.renderables))
    assert "athena" in (text or "")
    assert "Inbox" in (text or "")
    assert "DONE" in (text or "")


# -- Availability probe --------------------------------------------------


def test_probe_record_always_available_without_counts() -> None:
    assert probe_record_deck(_agent(), attempt_number=None) == DeckAvailability(
        True, None
    )
    assert probe_record_deck(_agent(), attempt_number=3) == DeckAvailability(True, None)


def test_subject_capture_needs_no_attributes() -> None:
    subject = record_subject_from_agent(SimpleNamespace())
    assert subject.kind == "agent"
    assert subject.location == "inbox"
    assert subject.agent_name is None
    assert subject.retry_attempt == 0
    assert subject.related_live_names == ()


def test_live_related_names_resolve_from_memory_only() -> None:
    agents = [
        SimpleNamespace(raw_suffix="a", presented_agent_name="@agent:a-x"),
        SimpleNamespace(raw_suffix="b", agent_name="bee"),
    ]
    assert live_related_names(agents, ("a", "missing")) == (("a", "@agent:a-x"),)
    assert live_related_names(agents, ()) == ()
    assert live_related_names(None, ("a",)) == ()


# -- Chrome: tabs and subtitle -------------------------------------------


def test_record_tabs_list_four_cards() -> None:
    from sase.ace.tui.widgets.decks.panel import DeckPanel

    panel = DeckPanel(0)
    panel._deck = DeckId.RECORD
    document = build_record_document(_subject(), None, None)
    panel.show_record_document(document, None)
    tabs = panel._record_tabs()
    assert [tab.card_id for tab in tabs] == [
        "lifecycle",
        "provenance",
        "relations",
        "links",
    ]
    assert panel._deck_is_empty(DeckId.RECORD) is False


def test_subtitle_shows_bare_record_switcher() -> None:
    from sase.ace.tui.widgets.decks.titles import deck_subtitle

    availability = {
        DeckId.MAIN: DeckAvailability(True, 1),
        DeckId.FILES: DeckAvailability(False, 0),
        DeckId.TOOLS: DeckAvailability(False, 0),
        DeckId.FINAL: DeckAvailability(False, 0),
        DeckId.RECORD: DeckAvailability(True, None),
    }
    rendered = deck_subtitle(
        DeckId.RECORD,
        availability,
        status=None,
        width=80,
        accent_for=dict.fromkeys(DeckId, ""),
    )
    assert "record" in rendered.plain
    assert "RECORD" not in rendered.plain


# -- Loader: signature cache and stale rejection --------------------------


def test_loader_signature_cache_skips_rebuild() -> None:
    import sase.ace.tui.widgets.decks.record.loader as loader_module

    clear_record_cache()
    calls = 0
    relation_calls = 0
    original = loader_module.load_facts_extras
    original_relations = loader_module.load_relations_extras

    def _counting(subject: RecordSubject):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original(subject)

    def _counting_relations(subject: RecordSubject):  # type: ignore[no-untyped-def]
        nonlocal relation_calls
        relation_calls += 1
        return original_relations(subject)

    loader_module.load_facts_extras = _counting  # type: ignore[method-assign]
    loader_module.load_relations_extras = _counting_relations  # type: ignore[method-assign]
    try:
        subject = _subject()
        first = load_record_deck(subject, generation=3)
        second = load_record_deck(subject, generation=4)
    finally:
        loader_module.load_facts_extras = original  # type: ignore[method-assign]
        loader_module.load_relations_extras = original_relations  # type: ignore[method-assign]
        clear_record_cache()
    assert calls == 1
    assert relation_calls == 2
    assert isinstance(first, RecordDeckLoadResult)
    assert second.generation == 4
    assert second.signature == first.signature
    assert second.document.card_ids == (
        "lifecycle",
        "provenance",
        "relations",
        "links",
    )
    assert second.default_card == RECORD_LIFECYCLE_CARD_ID


def test_loader_invalidates_cached_document_when_relations_extras_change() -> None:
    import sase.ace.tui.widgets.decks.record.loader as loader_module
    from sase.ace.tui.widgets.decks.record.relations import (
        ArtifactLinkGroup,
        RelationsExtras,
    )
    from sase.ace.tui.widgets.renderable_text import renderable_to_text
    from rich.console import Group

    clear_record_cache()
    subject = _subject()
    source_key: tuple[object, ...] = (("project", 1, 2),)
    neighbor = "1"

    def _relations(_subject: RecordSubject) -> RelationsExtras:
        return RelationsExtras(
            link_groups=(
                ArtifactLinkGroup(
                    direction="outgoing",
                    relation="related",
                    label="related",
                    neighbor_refs=(f"file:{neighbor}",),
                ),
            ),
            snapshot_source_key=source_key,
        )

    original = loader_module.load_relations_extras
    loader_module.load_relations_extras = _relations  # type: ignore[method-assign]
    try:
        first = load_record_deck(subject, generation=1)
        first_links = first.document.card("links")
        assert first_links is not None
        assert "file:1" in (renderable_to_text(Group(*first_links.renderables)) or "")

        source_key = (("project", 2, 3),)
        neighbor = "2"
        second = load_record_deck(subject, generation=2)
        second_links = second.document.card("links")
        assert second_links is not None
        assert "file:2" in (renderable_to_text(Group(*second_links.renderables)) or "")
        assert second.signature == first.signature
        assert second.relations_signature != first.relations_signature
    finally:
        loader_module.load_relations_extras = original  # type: ignore[method-assign]
        clear_record_cache()


def test_record_view_rejects_stale_subject_and_generation() -> None:
    from sase.ace.tui.widgets.decks.record.view import RecordDeckView

    view = RecordDeckView()
    view._current_subject_identity = "agent:1"
    view._current_generation = 7
    stale_subject = SimpleNamespace(subject_identity="agent:2", generation=7)
    stale_generation = SimpleNamespace(subject_identity="agent:1", generation=6)
    current = SimpleNamespace(subject_identity="agent:1", generation=7)
    assert view._is_stale_result(stale_subject) is True
    assert view._is_stale_result(stale_generation) is True
    assert view._is_stale_result(current) is False


def test_loaded_message_updates_panel_tabs() -> None:
    from sase.ace.tui.widgets.decks.panel import DeckPanel
    from sase.ace.tui.widgets.decks.record.view import RecordDeckLoaded

    panel = DeckPanel(0)
    panel._deck = DeckId.RECORD
    document = build_record_document(_subject(), None, None)
    message = RecordDeckLoaded(document, signature="sig", active_card="lifecycle")
    panel.handle_record_deck_loaded(message)
    assert panel._record_document is document
    tabs = panel._record_tabs()
    assert [tab.title for tab in tabs] == [
        "Lifecycle",
        "Provenance",
        "Relations",
        "Links",
    ]


# -- Persistence -----------------------------------------------------------


def test_record_panel_round_trips(tmp_path) -> None:
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
                        "deck": "record",
                        "preferred_cards": {
                            "main": "reply",
                            "record": "relations",
                        },
                        "views": {"main": "auto", "files": "auto"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].deck is DeckId.RECORD
    assert loaded.panels[0].preferred_cards == {
        DeckId.MAIN: "reply",
        DeckId.RECORD: "relations",
    }
    save_agents_deck_state(loaded, path)
    assert load_agents_deck_state(path) == loaded


def test_state_without_record_still_loads() -> None:
    from sase.ace.tui.models.agent_deck_persistence import load_agents_deck_state

    import json

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decks.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "layout": "single",
                    "ratio": 50,
                    "focused": 0,
                    "nodes_collapsed": False,
                    "panels": [{"deck": "main"}],
                }
            ),
            encoding="utf-8",
        )
        loaded = load_agents_deck_state(path)
    assert loaded.panels[0].deck is DeckId.MAIN


# -- No cross-deck content -------------------------------------------------


def test_record_header_never_shows_other_decks_content() -> None:
    from sase.ace.tui.widgets.decks.card_documents import (
        is_card_document_deck,
        resolve_document_deck,
    )
    from sase.ace.tui.widgets.decks.panel import DeckPanel

    assert resolve_document_deck(DeckId.RECORD) is DeckId.RECORD
    assert is_card_document_deck(DeckId.RECORD) is True
    panel = DeckPanel(0)
    panel._deck = DeckId.RECORD
    document = build_record_document(_subject(), None, None)
    panel.show_record_document(document, None)
    assert panel.document_for(DeckId.RECORD) is document
    assert panel.document_for(DeckId.RECORD) is not panel._final_document
    assert panel.document_for(DeckId.RECORD) is not panel._main_document
    assert panel._stored_document_active(DeckId.RECORD) is None


def test_search_corpus_reads_record_text() -> None:
    from sase.ace.tui.widgets.decks.search_corpus import deck_search_corpus

    record_view = SimpleNamespace(get_record_text=lambda: "── Lifecycle ──\nx")
    panel = SimpleNamespace(deck=DeckId.RECORD, record_view=record_view)
    assert deck_search_corpus(panel) == "── Lifecycle ──\nx"
    broken = SimpleNamespace(deck=DeckId.RECORD, record_view=None)
    assert deck_search_corpus(broken) == ""
