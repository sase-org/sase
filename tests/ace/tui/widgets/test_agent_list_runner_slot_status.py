"""Tests for agent-list runner-slot status rendering."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _styles_covering(text: Text, substring: str) -> set[str]:
    plain = text.plain
    start = plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


class TestRunnerSlotWaitRendering:
    def test_queued_row_renders_only_status_and_admission_rank(self) -> None:
        agent = make_agent(
            status="QUEUED",
            wait_runners=9,
            wait_runners_explicit=False,
            waiting_for=["completed-dependency"],
            wait_duration=300,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=10,
            runner_slot_queue_position=2,
            runner_slot_queue_size=3,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)
        header, _ = build_header_text(agent, cheap=True)

        assert "test_cl (QUEUED #2/3)" in left.plain
        assert "▶" not in left.plain
        assert "bold #5F87FF" in _styles_covering(left, "QUEUED")
        assert _styles_covering(left, "#2/3") == {"#5F87FF"}
        assert "Queue: #2 of 3 · " in header.plain
        assert " in queue" in header.plain
        assert "requested " not in header.plain
        assert "10/10 runners" not in header.plain
        assert "completed-dependency" not in header.plain

    def test_explicit_threshold_and_priority_render_on_queued_row(self) -> None:
        agent = make_agent(
            status="QUEUED",
            wait_runners=9,
            wait_runners_explicit=True,
            wait_priority=20,
            wait_priority_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=10,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "test_cl (QUEUED ▶10→9 p20)" in left.plain
        assert "dim #5F87FF" in _styles_covering(left, "p20")

    def test_implicit_priority_and_threshold_are_hidden_on_queued_row(self) -> None:
        agent = make_agent(
            status="QUEUED",
            wait_runners=9,
            wait_runners_explicit=False,
            wait_priority=20,
            wait_priority_explicit=False,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=10,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "test_cl (QUEUED)" in left.plain
        assert "▶" not in left.plain
        assert "p20" not in left.plain

    def test_explicit_drain_barrier_is_queued_and_unambiguous(self) -> None:
        agent = make_agent(
            status="QUEUED",
            wait_runners=0,
            wait_runners_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=3,
            runner_slot_queue_position=2,
            runner_slot_queue_size=2,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)
        header, _ = build_header_text(agent, cheap=True)

        assert "test_cl (QUEUED #2/2 ▶3→0)" in left.plain
        assert "dim #5F87FF" in _styles_covering(left, "▶3→0")
        assert (
            "Wait: [runners] ≤ 0 (drain barrier) · 3 runners still running"
            " · queue #2 of 2"
        ) in header.plain

    def test_explicit_wait_queue_position_is_labeled(self) -> None:
        agent = make_agent(
            status="QUEUED",
            wait_runners=3,
            wait_runners_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=3,
            runner_slot_queue_position=2,
            runner_slot_queue_size=3,
        )

        header, _ = build_header_text(agent, cheap=True)

        assert " · queue #2 of 3" in header.plain

    def test_explicit_priority_renders_in_detail_wait_line(self) -> None:
        agent = make_agent(
            status="QUEUED",
            wait_runners=9,
            wait_runners_explicit=False,
            wait_priority=20,
            wait_priority_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=10,
            runner_slot_queue_position=2,
            runner_slot_queue_size=3,
        )

        header, _ = build_header_text(agent, cheap=True)

        assert (
            "Wait: [runners] 10/10 in use · queue #2 of 3 · priority 20" in header.plain
        )
        assert "dim #AF87FF" in _styles_covering(header, "priority 20")

    def test_implicit_priority_is_hidden_in_detail_wait_line(self) -> None:
        agent = make_agent(
            status="QUEUED",
            wait_runners=9,
            wait_runners_explicit=False,
            wait_priority=20,
            wait_priority_explicit=False,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=10,
            runner_slot_queue_position=2,
            runner_slot_queue_size=3,
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "priority 20" not in header.plain
