"""Run-block coverage for the ⊛ FINAL deck (epic sase-1b2, bead sase-1b2.17).

Every FINAL card on a session container holds one ``CardBlock`` per
shell that ran finalizers, with roster-matched ``BlockMeta`` and the same
block ids Reply uses. Skipped and not-triggered shells appear only in the
ledger. The rail, ``[``/``]`` and newest landing work through the
generalized block host.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.decks.card_block import card_block_id
from sase.ace.tui.widgets.decks.final.document import build_final_deck_document
from sase.ace.tui.widgets.decks.final.run_blocks import (
    final_block_runs,
    _format_run_duration,
    is_final_block_run,
    run_block_header,
    run_block_meta,
    _run_status_bucket,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_agent_session import (
    AgentSessionTurnFacts,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
    PHASE_DIVIDER_ACCENT,
    render_phase_divider,
)
from sase.ace.tui.widgets.prompt_panel._agent_session_reply_blocks import (
    block_meta_for_session_turn,
    build_session_reply_blocks,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    DECK_BLOCK_META_KEY,
)
from sase.core.finalizer_run_view import (
    _RunViewAttempt,
    _RunViewDeclaration,
    _RunViewNodeInstance,
    RunViewRun,
    RunViewRunInstance,
)
from sase.monitor_state import MONITOR_GLYPH


def _turn(
    *,
    name: str = "sase-1b2--code",
    suffix: str | None = None,
    status: str = "DONE",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-code",
        project_file="/tmp/p.sase",
        status=status,
        start_time=datetime(2026, 9, 27, 7, 30, 0),
        raw_suffix=suffix or "20260927073000-code",
        agent_name=name,
    )


def _attempt(n: int, status: str, seconds: float = 10.0) -> _RunViewAttempt:
    return _RunViewAttempt(attempt=n, status=status, duration_seconds=seconds)


def _run_item(
    instance_id: str, status: str, *, seconds: float = 10.0, **extra: object
) -> RunViewRunInstance:
    payload: dict[str, object] = {
        "instance_id": instance_id,
        "status": status,
        "attempts": [_attempt(1, status, seconds)],
    }
    payload.update(extra)
    return RunViewRunInstance(**payload)  # type: ignore[arg-type]


def _session_view() -> SimpleNamespace:
    plan = _turn(suffix="20260927073000-plan", status="DONE")
    code = _turn(suffix="20260927073000-code", status="DONE")
    mon = _turn(name="sase-1b2--code", suffix="20260927073000-mon", status="DONE")
    try:
        mon.is_monitor = True  # type: ignore[attr-defined]
    except Exception:
        pass
    skipped = RunViewRun(
        run_id=card_block_id(plan.identity),
        number=0,
        label="--plan",
        kind="agent",
        disposition="skipped",
        reason="handoff:plan",
    )
    failed = RunViewRun(
        run_id=card_block_id(code.identity),
        number=1,
        label="--code",
        kind="agent",
        disposition="ran",
        result_status="failed",
        declarations=[
            _RunViewDeclaration(
                status="accepted",
                t=1727440000.0,
                code="ok",
                payload_count=2,
            )
        ],
        instances=[
            _run_item("commit", "success", seconds=124.0),
            _run_item("check", "failed", seconds=220.0),
            _run_item("tasks", "not_run", seconds=0.0, blocked_by="check"),
        ],
    )
    active = RunViewRun(
        run_id=card_block_id(mon.identity),
        number=2,
        label="--code",
        kind="monitor",
        disposition="active",
        declarations=[
            _RunViewDeclaration(
                status="accepted",
                t=1727440100.0,
                code="ok",
                payload_count=1,
            )
        ],
        instances=[
            _run_item("commit", "success", seconds=30.0),
            _run_item("check", "not_triggered", seconds=0.0),
            _run_item("tasks", "not_run", seconds=0.0, blocked_by="check"),
        ],
    )
    node = SimpleNamespace(
        status="failed",
        glyph="✗",
        run_level_trouble=True,
        instances=[
            _RunViewNodeInstance(
                instance_id="commit",
                selection_reason="default",
                status="success",
                provider_ref="builtin@commit",
            ),
            _RunViewNodeInstance(
                instance_id="check",
                selection_reason="%final:check",
                status="failed",
                provider_ref="builtin@command",
                after=["commit"],
            ),
            _RunViewNodeInstance(
                instance_id="tasks",
                selection_reason="default",
                status="not_run",
                provider_ref="builtin@tasks",
            ),
        ],
        unselected=[],
        runs=[skipped, failed, active],
        attention_instance_id="check",
    )
    return SimpleNamespace(view=node, turns=(plan, code, mon))


def _plain(renderables: tuple[object, ...]) -> str:
    parts: list[str] = []
    for renderable in renderables:
        if isinstance(renderable, Text):
            parts.append(renderable.plain)
        else:
            parts.append(str(renderable))
    return "\n".join(parts)


# -- Disposition filter --------------------------------------------------


def test_only_active_ran_interrupted_earn_blocks() -> None:
    assert is_final_block_run(SimpleNamespace(disposition="active")) is True
    assert is_final_block_run(SimpleNamespace(disposition="ran")) is True
    assert is_final_block_run(SimpleNamespace(disposition="interrupted")) is True
    assert is_final_block_run(SimpleNamespace(disposition="skipped")) is False
    assert is_final_block_run(SimpleNamespace(disposition="not_reached")) is False
    assert is_final_block_run(SimpleNamespace(disposition="unavailable")) is False


def test_final_block_runs_keep_ledger_order() -> None:
    fixture = _session_view()
    assert [run.number for run in final_block_runs(fixture.view.runs)] == [1, 2]


# -- Overview blocks and ledger ------------------------------------------


def test_overview_holds_one_block_per_block_run() -> None:
    fixture = _session_view()
    document = build_final_deck_document(
        fixture.view, subject="session:1", digest="sig"
    )
    overview = document.card("overview")
    assert overview is not None
    assert overview.block_ids == (
        card_block_id(fixture.turns[1].identity),
        card_block_id(fixture.turns[2].identity),
    )


def test_skipped_run_appears_only_in_ledger() -> None:
    fixture = _session_view()
    document = build_final_deck_document(
        fixture.view, subject="session:1", digest="sig"
    )
    overview = document.card("overview")
    assert overview is not None
    body = _plain(tuple(overview.renderables))
    assert "--plan ○ skipped · plan handoff" in body
    assert "its successor lands the work" in body
    assert fixture.view.runs[0].run_id not in overview.block_ids


def test_blocks_are_trailing_and_contiguous() -> None:
    fixture = _session_view()
    document = build_final_deck_document(
        fixture.view, subject="session:1", digest="sig"
    )
    for card in document.cards:
        assert len(card.blocks) == len(card.block_ids)
        if card.blocks:
            assert card.has_block_navigation or len(card.blocks) == 1


# -- Rail parity with Reply ----------------------------------------------


def _reply_blocks(turns: tuple[Agent, ...]) -> list[object]:
    facts = tuple(
        AgentSessionTurnFacts(
            member=turn,
            label="--plan" if index == 0 else "--code",
            kind="monitor" if index == 2 else "agent",
            glyph=MONITOR_GLYPH if index == 2 else "",
            accent="#FF0000" if index == 2 else PHASE_DIVIDER_ACCENT,
            status_bucket="Done" if index == 0 else "Running",
        )
        for index, turn in enumerate(turns)
    )

    def _render(phase: Agent, block_id: str) -> list[object]:
        return [
            render_phase_divider(
                "--plan" if "plan" in block_id else "--code",
                None,
                block_id=block_id,
            )
        ]

    _, blocks = build_session_reply_blocks(turns, facts, render_phase=_render)
    return blocks


def test_final_block_ids_match_reply_rail() -> None:
    fixture = _session_view()
    document = build_final_deck_document(
        fixture.view, subject="session:1", digest="sig"
    )
    overview = document.card("overview")
    assert overview is not None
    reply_blocks = _reply_blocks(fixture.turns)
    reply_ids = [block.block_id for block in reply_blocks]
    # Reply numbers every concrete turn; FINAL blocks only block runs, so
    # FINAL ids are Reply's subsequence with the skipped shell gapped out.
    assert list(overview.block_ids) == [
        rid for rid in reply_ids if rid in set(overview.block_ids)
    ]
    assert overview.block_ids[0] == reply_ids[1]
    assert overview.block_ids[1] == reply_ids[2]
    metas = {block.block_id: block.meta for block in reply_blocks}
    for block in overview.blocks:
        assert block.meta.number == metas[block.block_id].number
        assert block.meta.label == metas[block.block_id].label
        assert block.meta.kind == metas[block.block_id].kind


def test_rail_cue_derives_from_block_mode() -> None:
    from sase.ace.tui.widgets.decks.document_rail import (
        DeckPanelDocumentRailMixin,
    )
    from sase.ace.tui.widgets.decks.block_rail import BlockRailEntry
    from sase.ace.tui.widgets.decks.model import DeckId, RenderMode

    fixture = _session_view()
    document = build_final_deck_document(
        fixture.view, subject="session:1", digest="sig"
    )
    overview = document.card("overview")
    assert overview is not None
    entries = [BlockRailEntry(block.block_id, block.meta) for block in overview.blocks]
    paged = SimpleNamespace(
        document_block_mode_for_active_card=lambda deck: RenderMode.PAGED
    )
    assert (
        DeckPanelDocumentRailMixin.document_block_rail_cue(
            paged, DeckId.FINAL, entries, entries[-1].block_id
        )
        == "page 2/2"
    )
    spread = SimpleNamespace(
        document_block_mode_for_active_card=lambda deck: RenderMode.SPREAD
    )
    assert (
        DeckPanelDocumentRailMixin.document_block_rail_cue(
            spread, DeckId.FINAL, entries, entries[-1].block_id
        )
        == "all 2"
    )


# -- BlockMeta and headers -------------------------------------------------


def test_block_meta_buckets_and_monitor_facts() -> None:
    fixture = _session_view()
    runs = fixture.view.runs
    failed_meta = run_block_meta(runs[1])
    assert (failed_meta.number, failed_meta.label, failed_meta.kind) == (
        "1",
        "--code",
        "agent",
    )
    assert failed_meta.glyph == ""
    assert failed_meta.status_bucket == "Failed"
    active_meta = run_block_meta(runs[2])
    assert active_meta.kind == "monitor"
    assert active_meta.glyph == MONITOR_GLYPH
    assert active_meta.status_bucket == "Running"
    assert _run_status_bucket(SimpleNamespace(disposition="ran")) == "Done"
    assert (
        _run_status_bucket(SimpleNamespace(disposition="ran", result_status="refused"))
        == "Failed"
    )
    assert _run_status_bucket(SimpleNamespace(disposition="interrupted")) == "Stopped"


def test_block_header_carries_anchor_and_duration() -> None:
    fixture = _session_view()
    run = fixture.view.runs[1]
    header = run_block_header(run)
    assert "--code" in header.plain
    total = 124.0 + 220.0
    assert _format_run_duration(total) in header.plain
    assert header.spans, "expected the block anchor meta span"
    found = False
    for span in header.spans:
        meta = getattr(span.style, "meta", None) or {}
        if meta.get(DECK_BLOCK_META_KEY) == run.run_id:
            found = True
    assert found


# -- Instance cards --------------------------------------------------------


def test_instance_cards_only_block_runs_where_instance_ran() -> None:
    fixture = _session_view()
    document = build_final_deck_document(
        fixture.view, subject="session:1", digest="sig"
    )
    commit = document.card("instance:commit")
    check = document.card("instance:check")
    tasks = document.card("instance:tasks")
    assert commit is not None and check is not None and tasks is not None
    run_ids = [run.run_id for run in final_block_runs(fixture.view.runs)]
    assert commit.block_ids == tuple(run_ids)
    assert check.block_ids == (run_ids[0],)
    # tasks never ran: block-less, calm like the flat card.
    assert tasks.block_ids == ()
    assert "not run" in _plain(tuple(tasks.renderables))


def test_single_run_node_shows_no_rail() -> None:
    fixture = _session_view()
    run = fixture.view.runs[1]
    node = SimpleNamespace(
        status="failed",
        glyph="✗",
        run_level_trouble=True,
        instances=list(fixture.view.instances),
        unselected=[],
        runs=[run],
        attention_instance_id="check",
    )
    document = build_final_deck_document(node, subject="agent:1", digest="sig")
    for card in document.cards:
        assert card.block_ids == ()
        assert card.has_block_navigation is False


# -- Navigation and stickiness ----------------------------------------------


def test_bracket_cursor_steps_and_lands_newest() -> None:
    from sase.ace.tui.widgets.decks.final.view import FinalDeckView

    fixture = _session_view()
    document = build_final_deck_document(
        fixture.view, subject="session:1", digest="sig"
    )
    overview = document.card("overview")
    assert overview is not None
    view = FinalDeckView()
    view._reconcile_block_cursors(document, new_subject=True, enabled=True)
    cursor = view._block_cursor_for("overview")
    assert cursor is not None
    assert cursor.block_id == overview.newest_block_id
    stepped = view.step_block_cursor(overview, -1)
    assert stepped is not None
    assert stepped.block_id == overview.block_ids[0]
    selected = view.select_block_cursor(overview, overview.block_ids[1])
    assert selected is not None and selected.block_id == overview.block_ids[1]
    landed = view.land_block_cursor(overview)
    assert landed is not None and landed.block_id == overview.newest_block_id
    page = overview.block_page(overview.newest_block_id)
    assert _plain(tuple(page)).strip() != ""


def test_panel_block_keys_route_by_deck(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sase.ace.tui.widgets.decks.model import DeckId
    from sase.ace.tui.widgets.decks.panel import DeckPanel

    panel = DeckPanel(0)
    calls: list[tuple[str, object]] = []

    def _cycle(deck: object, direction: int) -> bool:
        calls.append(("cycle", deck))
        return True

    def _select(deck: object, block_id: object) -> bool:
        calls.append(("select", deck))
        return True

    monkeypatch.setattr(panel, "cycle_document_block", _cycle)
    monkeypatch.setattr(panel, "select_document_block", _select)
    panel._deck = DeckId.FINAL
    assert panel.cycle_block(1) is True
    assert panel.select_block("b") is True
    assert calls == [("cycle", DeckId.FINAL), ("select", DeckId.FINAL)]
    panel._deck = DeckId.MAIN
    assert panel.cycle_block(1) is True
    assert calls[-1] == ("cycle", DeckId.MAIN)


def test_block_navigation_sticks_final_card() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId
    from sase.ace.tui.widgets.decks.panel import DeckPanel

    fixture = _session_view()
    document = build_final_deck_document(
        fixture.view, subject="session:1", digest="sig"
    )
    panel = DeckPanel(0)
    panel._deck = DeckId.FINAL
    panel._final_document = document
    panel._store_document_active(DeckId.FINAL, "instance:check")
    panel._store_document_active(DeckId.MAIN, "reply")
    assert panel.active_deck_card() == "instance:check"
