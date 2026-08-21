"""Tests for waited-for bead status badges in the metadata header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.wait_status_presentation import (
    WAIT_UNKNOWN_GLYPH_STYLE,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.ace.tui.widgets.prompt_panel._agent_wait_section import (
    ResponsiveWaitSection,
    build_wait_lanes,
)
from sase.bead_status_presentation import (
    bead_status_display_order,
    bead_status_presentation,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _waiting_header(agent: Agent, summary: DetailHeaderSummary | None = None) -> Text:
    header, _ = build_header_text(agent, summary=summary)
    return header


def _waiting_line(agent: Agent, summary: DetailHeaderSummary | None = None) -> str:
    header = _waiting_header(agent, summary)
    return next(line for line in header.plain.splitlines() if line.startswith("Wait: "))


def _styles_covering(text: Text, substring: str) -> set[str]:
    start = text.plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


def test_waited_for_bead_uses_every_canonical_status_token() -> None:
    for status in bead_status_display_order():
        presentation = bead_status_presentation(status)
        token = presentation.tui_glyph
        style = presentation.rich_style
        agent = make_agent(status="WAITING", waiting_for_beads=["sase-9r.2"])
        summary = DetailHeaderSummary(wait_bead_statuses=(("sase-9r.2", status),))
        header = _waiting_header(agent, summary)

        assert _waiting_line(agent, summary) == f"Wait: [beads] sase-9r.2 {token}"
        assert _styles_covering(header, token) == {style}


def test_unknown_waited_for_bead_gets_unknown_token() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-9r.2"],
    )
    summary = DetailHeaderSummary(
        wait_bead_statuses=(("sase-9r.2", None),),
    )
    header = _waiting_header(agent, summary)

    assert _waiting_line(agent, summary) == "Wait: [beads] sase-9r.2 ?"
    assert _styles_covering(header, "?") == {WAIT_UNKNOWN_GLYPH_STYLE}


def test_no_summary_preserves_plain_first_paint() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-9r.2"],
    )

    assert _waiting_line(agent) == "Wait: [beads] sase-9r.2"


def test_multiple_waited_for_beads_keep_status_tokens_attached() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for_beads=["a", "b"],
    )
    summary = DetailHeaderSummary(
        wait_bead_statuses=(("a", "closed"), ("b", "open")),
    )

    assert _waiting_line(agent, summary) == "Wait: [beads] a ●, b ○"


def test_mismatched_summary_degrades_to_unknown_token() -> None:
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


def test_wait_lanes_keep_agent_glyphs_and_status_bearing_bead_tokens() -> None:
    agent = make_agent(
        status="WAITING",
        waiting_for=["coder", "@epic"],
        waiting_for_beads=["run-bead"],
        wait_duration=300,
        wait_runners=2,
        slot_requested_at="2026-07-28T12:00:00Z",
        runner_slots_in_use=1,
    )
    text = ResponsiveWaitSection(
        build_wait_lanes(
            agent,
            agent_status_buckets={"coder": "Done"},
            clan_wait_member_statuses=None,
            tribe_wait_bindings=None,
            wait_bead_statuses=(("run-bead", "in_progress"),),
        )
    ).logical_text
    lines = text.plain.splitlines()

    assert lines[0].startswith("Wait: [agents]")
    assert "coder ✓" in lines[0]
    assert "[tribes]" in text.plain
    assert "run-bead ◐" in text.plain
    assert "[time]" in text.plain
    assert "[runners]" in text.plain
    assert _styles_covering(text, "✓") == {"bold #5FD75F"}
    assert _styles_covering(text, "◐") == {
        bead_status_presentation("in_progress").rich_style
    }
