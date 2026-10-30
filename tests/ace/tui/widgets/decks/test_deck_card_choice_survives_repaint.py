"""Ctrl+J card choices survive background deck repaints.

Pressing Ctrl+J on FINAL, RECORD, or Tools sticks the choice in deck-area
state, but background repaints re-read a cached copy and snap back. These
tests prove the sticky choice wins through live ticks, worker completions,
and Runs-loaded notifications.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rich.text import Text
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.card_part import CardPart
from sase.ace.tui.widgets.decks.document_view import CardDocumentView
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.decks.panel import DeckPanel
from tests.ace.tui.visual._ace_agents_final_png_snapshot_shared import (
    deck_summary,
    goto_agents,
    make_agent,
    node_failed_check,
    patch_final_view,
    show_final,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_state,
    wait_for_visual_idle,
)

__all__ = [
    "test_final_live_tick_keeps_ctrl_j_card",
    "test_final_worker_completion_keeps_ctrl_j_card",
    "test_record_worker_completion_keeps_ctrl_j_card",
    "test_tools_runs_loaded_does_not_clobber_llm_calls",
    "test_tools_runs_loaded_stores_runs_when_nothing_stored",
    "test_headless_panel_sticky_card_raises",
    "test_unmounted_view_host_preferred_returns_fallback",
]


def _two_card_node() -> dict[str, Any]:
    """Return a failed-check node with a second commit instance appended."""
    payload = node_failed_check()
    payload = copy.deepcopy(payload)
    payload["instances"].append(
        {
            "instance_id": "commit",
            "selection_reason": "default",
            "status": "success",
            "provider_ref": "builtin@commit",
        }
    )
    check_run_instance = copy.deepcopy(payload["runs"][0]["instances"][0])
    check_run_instance["instance_id"] = "commit"
    check_run_instance["status"] = "success"
    payload["runs"][0]["instances"].append(check_run_instance)
    return payload


async def test_final_live_tick_keeps_ctrl_j_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """FINAL live tick keeps the Ctrl+J card instead of snapping back."""
    patch_final_view(monkeypatch, _two_card_node())
    agent = make_agent(
        tmp_path,
        name="repaint",
        suffix="deck-repaint",
        status="RUNNING",
        summary=deck_summary("check", "commit", status="failed", phase="executing"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_final(page)
        panel = detail.deck_area.panel(0)
        assert panel.final_view.active_card_id == "instance:check"
        await page.press("ctrl+j")
        await wait_for_state(
            page,
            lambda: panel.final_view.active_card_id == "instance:commit",
            description="FINAL Ctrl+J selects commit",
        )
        await panel.final_view._live_tick_run()
        await wait_for_visual_idle(page)
        assert panel.final_view.active_card_id == "instance:commit"
        assert panel._stored_document_active(DeckId.FINAL) == "instance:commit"
        assert (
            detail.deck_area.state.panels[0].preferred_card_for(DeckId.FINAL)
            == "instance:commit"
        )


async def test_final_worker_completion_keeps_ctrl_j_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """FINAL worker SUCCESS keeps the Ctrl+J card with a stale cached copy."""
    from sase.ace.tui.widgets.decks.final.loader import FinalDeckLoadResult

    patch_final_view(monkeypatch, _two_card_node())
    agent = make_agent(
        tmp_path,
        name="repaint-worker",
        suffix="deck-repaint-worker",
        status="RUNNING",
        summary=deck_summary("check", "commit", status="failed", phase="executing"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_final(page)
        panel = detail.deck_area.panel(0)
        view = panel.final_view
        await page.press("ctrl+j")
        await wait_for_state(
            page,
            lambda: view.active_card_id == "instance:commit",
            description="FINAL Ctrl+J selects commit",
        )
        result = FinalDeckLoadResult(
            subject_identity=view._current_subject_identity,
            generation=view._current_generation,
            signature="test-sig",
            document=panel._final_document,
            default_card="instance:check",
            status="failed",
            glyph="✗",
            attention_instance_id="check",
            run_level_trouble=True,
        )
        view._current_preferred = "instance:check"
        stub = SimpleNamespace(result=result)
        view._current_worker = stub  # type: ignore[assignment]
        event = SimpleNamespace(worker=stub, state=WorkerState.SUCCESS)
        view.on_worker_state_changed(event)  # type: ignore[arg-type]
        await wait_for_visual_idle(page)
        assert view.active_card_id == "instance:commit"


async def test_record_worker_completion_keeps_ctrl_j_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RECORD worker SUCCESS keeps the Ctrl+J card with a stale cached copy."""
    from sase.ace.tui.widgets.decks.record.loader import RecordDeckLoadResult

    patch_final_view(monkeypatch, _two_card_node())
    agent = make_agent(
        tmp_path,
        name="repaint-record",
        suffix="deck-repaint-record",
        status="RUNNING",
        summary=deck_summary("check", "commit", status="failed", phase="executing"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        detail.show_deck(0, DeckId.RECORD)
        panel = detail.deck_area.panel(0)
        await wait_for_state(
            page,
            lambda: bool(panel._record_document.cards),
            description="RECORD deck document loaded",
        )
        await wait_for_visual_idle(page)
        assert panel.record_view.active_card_id == "lifecycle"
        await page.press("ctrl+j")
        await wait_for_state(
            page,
            lambda: panel.record_view.active_card_id == "provenance",
            description="RECORD Ctrl+J selects provenance",
        )
        view = panel.record_view
        result = RecordDeckLoadResult(
            subject_identity=view._current_subject_identity,
            generation=view._current_generation,
            signature="test-sig",
            document=panel._record_document,
            default_card="lifecycle",
        )
        view._current_preferred = "lifecycle"
        stub = SimpleNamespace(result=result)
        view._current_worker = stub  # type: ignore[assignment]
        event = SimpleNamespace(worker=stub, state=WorkerState.SUCCESS)
        view.on_worker_state_changed(event)  # type: ignore[arg-type]
        await wait_for_visual_idle(page)
        assert view.active_card_id == "provenance"


def _runs_document() -> MainDeckDocument:
    """Return a one-card Runs document (the Runs view's only card)."""
    return MainDeckDocument(
        cards=(CardPart("runs", "Runs", Text("run output")),),
        subject="agent:1",
        partial=False,
        digest="sig",
    )


def _runs_loaded_message(
    document: MainDeckDocument, *, active_card: str | None = "runs"
) -> Any:
    """Return a ToolRunsDeckLoaded message for ``document``."""
    from sase.ace.tui.widgets.decks.tool_runs.messages import ToolRunsDeckLoaded

    return ToolRunsDeckLoaded(
        document,
        status="success",
        glyph="✓",
        signature="sig",
        active_card=active_card,
        n_runs=1,
        live=False,
        silent=False,
    )


def test_tools_runs_loaded_does_not_clobber_llm_calls() -> None:
    """Runs-loaded keeps a stored llm-calls Tools choice."""
    panel = DeckPanel(0)
    panel._deck = DeckId.TOOLS
    panel._store_document_active(DeckId.TOOLS, "llm-calls")
    panel.handle_tool_runs_deck_loaded(_runs_loaded_message(_runs_document()))
    assert panel._stored_document_active(DeckId.TOOLS) == "llm-calls"


def test_tools_runs_loaded_stores_runs_when_nothing_stored() -> None:
    """Runs-loaded records runs when no Tools card is stored yet."""
    panel = DeckPanel(0)
    panel._deck = DeckId.TOOLS
    assert panel._stored_document_active(DeckId.TOOLS) is None
    panel.handle_tool_runs_deck_loaded(_runs_loaded_message(_runs_document()))
    assert panel._stored_document_active(DeckId.TOOLS) == "runs"


def test_headless_panel_sticky_card_raises() -> None:
    """Headless panels raise LookupError so callers can tell no-host apart."""
    panel = DeckPanel(0)
    with pytest.raises(LookupError):
        panel.sticky_card_for(DeckId.FINAL)


def test_unmounted_view_host_preferred_returns_fallback() -> None:
    """Unmounted views fail open to the caller's fallback."""
    view = CardDocumentView(deck=DeckId.FINAL)
    assert view.host_preferred_card("fallback") == "fallback"
    assert view.host_preferred_card(None) is None
