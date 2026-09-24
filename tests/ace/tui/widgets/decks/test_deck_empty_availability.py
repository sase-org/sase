"""Empty-state and availability probe tests."""

from __future__ import annotations

from rich.align import Align
from rich.text import Text

from sase.ace.tui.widgets.decks.availability import (
    DeckAvailability,
    probe_files_deck,
    probe_tools_deck,
)
from sase.ace.tui.widgets.decks.empty_state import deck_empty_state
from sase.ace.tui.widgets.decks.model import DeckId
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _render_text(renderable: object) -> str:
    if isinstance(renderable, Align):
        inner = renderable.renderable
        if isinstance(inner, Text):
            return inner.plain
    if isinstance(renderable, Text):
        return renderable.plain
    return str(renderable)


def test_empty_state_messages() -> None:
    assert "No agent selected" in _render_text(
        deck_empty_state(DeckId.MAIN, subject_kind="none", hint=None)
    )
    assert "No files for this agent" in _render_text(
        deck_empty_state(DeckId.FILES, subject_kind="agent", hint=None)
    )
    assert "node" in _render_text(
        deck_empty_state(DeckId.FILES, subject_kind="node", hint=None)
    )
    assert "tribe" in _render_text(
        deck_empty_state(DeckId.FILES, subject_kind="tribe", hint=None)
    )
    assert "attempt" in _render_text(
        deck_empty_state(DeckId.FILES, subject_kind="attempt", hint=None)
    )
    assert "No LLM calls for this agent" in _render_text(
        deck_empty_state(DeckId.TOOLS, subject_kind="agent", hint=None)
    )
    assert "attempt" in _render_text(
        deck_empty_state(DeckId.TOOLS, subject_kind="attempt", hint=None)
    )


def test_files_probe_empty_kinds() -> None:
    from sase.ace.tui.models.agent import AgentType

    agent = make_agent(status="RUNNING")
    assert probe_files_deck(agent, attempt_number=1) == DeckAvailability(False, 0)
    clan = make_agent(status="RUNNING", is_clan_container=True)
    assert clan.is_clan_container
    assert probe_files_deck(clan, attempt_number=None) == DeckAvailability(False, 0)
    proc = make_agent(status="RUNNING", agent_type=AgentType.PROC_SHELL)
    assert proc.is_proc_shell
    assert probe_files_deck(proc, attempt_number=None) == DeckAvailability(False, 0)


def test_files_probe_no_io(monkeypatch) -> None:
    import os
    from pathlib import Path

    def _raise(*args: object, **kwargs: object) -> object:
        raise AssertionError("probe performed I/O")

    monkeypatch.setattr(os, "stat", _raise)
    monkeypatch.setattr("builtins.open", _raise)
    monkeypatch.setattr(Path, "read_text", _raise)
    agent = make_agent(status="RUNNING")
    probe_files_deck(agent, attempt_number=None)
    probe_tools_deck(agent, attempt_number=None)


def test_tools_probe_empty_kinds() -> None:
    agent = make_agent(status="RUNNING")
    assert probe_tools_deck(agent, attempt_number=1) == DeckAvailability(False, 0)
    clan = make_agent(status="RUNNING", is_clan_container=True)
    assert probe_tools_deck(clan, attempt_number=None) == DeckAvailability(False, 0)
