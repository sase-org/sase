"""Tests for waited-for bead status badges in the metadata header."""

from __future__ import annotations

import pytest

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _waiting_line(agent: Agent, summary: DetailHeaderSummary | None = None) -> str:
    header, _ = build_header_text(agent, summary=summary)
    return next(line for line in header.plain.splitlines() if line.startswith("Wait: "))


@pytest.mark.parametrize(
    ("status", "glyph"),
    [
        ("closed", "✓"),
        ("in_progress", "▶"),
        ("claimed", "◐"),
        ("open", "⏳"),
    ],
)
def test_waited_for_bead_gets_status_badge(status: str, glyph: str) -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-9r.2"],
    )
    summary = DetailHeaderSummary(
        wait_bead_statuses=(("sase-9r.2", status),),
    )

    assert _waiting_line(agent, summary) == f"Wait: [beads] sase-9r.2 {glyph}"


def test_unknown_waited_for_bead_gets_unknown_badge() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-9r.2"],
    )
    summary = DetailHeaderSummary(
        wait_bead_statuses=(("sase-9r.2", None),),
    )

    assert _waiting_line(agent, summary) == "Wait: [beads] sase-9r.2 ?"


def test_no_summary_preserves_plain_first_paint() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-9r.2"],
    )

    assert _waiting_line(agent) == "Wait: [beads] sase-9r.2"


def test_multiple_waited_for_beads_keep_statuses_attached() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for_beads=["a", "b"],
    )
    summary = DetailHeaderSummary(
        wait_bead_statuses=(("a", "closed"), ("b", "open")),
    )

    assert _waiting_line(agent, summary) == "Wait: [beads] a ✓, b ⏳"


def test_mismatched_summary_degrades_to_unknown_badge() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for_beads=["current"],
    )
    summary = DetailHeaderSummary(
        wait_bead_statuses=(("stale", "closed"),),
    )

    assert _waiting_line(agent, summary) == "Wait: [beads] current ?"


def test_agent_only_wait_rendering_is_tagged() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder"],
    )

    assert _waiting_line(agent) == "Wait: [agents] coder"
