"""Tests for agent-list wait dependency status indicators."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rich.text import Text

from sase.ace.tui.agent_completion import (
    WaitAgentStatusCounts,
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _styles_covering(text: Text, substring: str) -> set[str]:
    plain = text.plain
    start = plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


class TestMissingWaitTargetIndicator:
    def test_waiting_row_renders_known_status_counts_with_styles(self) -> None:
        agent = make_agent(status="WAITING", waiting_for=["coder", "reviewer"])

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(running=2, done=1)
            ),
        )

        assert left.plain.endswith("test_cl (WAITING ▶2 ✓1)")
        assert "bold #FFD700" in _styles_covering(left, "▶2")
        assert "bold #5FD75F" in _styles_covering(left, "✓1")

    def test_waiting_row_renders_one_amber_bold_count(self) -> None:
        agent = make_agent(status="WAITING", waiting_for=["ghost_deploy"])

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(unknown=1)
            ),
        )

        assert left.plain.endswith("test_cl (WAITING ?1)")
        assert "bold #FFAF5F" in _styles_covering(left, "?")

    def test_waiting_row_counts_multiple_missing_targets(
        self,
    ) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["first_missing", "second_missing"],
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(unknown=2)
            ),
        )

        assert left.plain.count("?") == 1
        assert left.plain.endswith("test_cl (WAITING ?2)")

    @pytest.mark.parametrize(
        "agent",
        [
            make_agent(
                status="WAITING",
                waiting_for_beads=["sase-87.2"],
            ),
            make_agent(status="WAITING", wait_duration=300),
            make_agent(
                status="WAITING",
                wait_runners=3,
                slot_requested_at="2026-07-12T12:00:00Z",
                runner_slots_in_use=4,
            ),
            make_agent(status="RUNNING", waiting_for=["ghost_deploy"]),
        ],
    )
    def test_marker_is_absent_for_waits_without_counts(
        self,
        agent: Agent,
    ) -> None:
        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
        )

        assert "?" not in left.plain

    def test_counts_do_not_render_on_non_waiting_rows(self) -> None:
        agent = make_agent(status="RUNNING", waiting_for=["ghost_deploy"])

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(unknown=1),
                beads=WaitBeadStatusCounts(in_progress=1, unknown=1),
            ),
        )

        assert "?" not in left.plain
        assert "◐1" not in left.plain
        assert "WAITING" not in left.plain

    def test_unsatisfied_dependency_without_slot_request_stays_waiting(self) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["ghost_deploy"],
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(unknown=1)
            ),
        )

        assert left.plain.endswith("test_cl (WAITING ?1)")

    def test_marker_precedes_relative_duration_annotation(self) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["ghost_deploy"],
            wait_duration=300,
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(unknown=1)
            ),
        )

        assert left.plain.endswith("test_cl (WAITING ?1 +5m)")

    def test_marker_precedes_absolute_time_annotation(self) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        agent = make_agent(
            status="WAITING",
            waiting_for=["ghost_deploy"],
            wait_until=wait_until,
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            now=now,
            wait_deps_satisfied=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(unknown=1)
            ),
        )

        assert left.plain.endswith("test_cl (WAITING ?1 (until 14:15, 1m29s))")

    def test_waiting_row_renders_bead_only_counts_after_warmup(self) -> None:
        agent = make_agent(status="WAITING", waiting_for_beads=["run-bead"])

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                beads=WaitBeadStatusCounts(in_progress=1)
            ),
        )

        assert left.plain.endswith("test_cl (WAITING ◐1)")
        assert "bold #FFD700" in _styles_covering(left, "◐1")

    def test_waiting_row_renders_mixed_domains_before_annotations(self) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["builder", "@default"],
            waiting_for_beads=["done-bead"],
            wait_duration=300,
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(running=1),
                beads=WaitBeadStatusCounts(closed=1),
            ),
            has_unresolvable_wait_target=True,
        )

        assert left.plain.endswith("test_cl (WAITING ▶1 ●1 ! +5m)")
        assert "bold #FFD700" in _styles_covering(left, "▶1")
        assert "bold #5FD787" in _styles_covering(left, "●1")

    def test_waiting_row_keeps_unknown_agent_and_bead_tokens_distinct(
        self,
    ) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["ghost"],
            waiting_for_beads=["missing-bead"],
            wait_duration=300,
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_dependency_counts=WaitDependencyStatusCounts(
                agents=WaitAgentStatusCounts(unknown=1),
                beads=WaitBeadStatusCounts(unknown=2),
            ),
        )

        assert left.plain.endswith("test_cl (WAITING ?1 ?2 +5m)")
