"""Tests for agent-list runner-slot status rendering."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.feature_flags import override_flags
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

    def test_queued_wait_display_source_renders_admission_rank(self) -> None:
        source = make_agent(
            cl_name="code",
            status="QUEUED",
            runner_slot_queue_position=1,
            runner_slot_queue_size=2,
        )
        root = make_agent(status="QUEUED")
        root.wait_display_source = source

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "test_cl (QUEUED #1/2)" in left.plain
        assert _styles_covering(left, "#1/2") == {"#5F87FF"}

    def test_explicit_capacity_and_priority_render_on_queued_row(self) -> None:
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

        assert "test_cl c9 (QUEUED p20)" in left.plain
        assert "▶" not in left.plain
        assert _styles_covering(left, "c9") == {"dim", "#87AFD7"}
        assert "dim #5F87FF" in _styles_covering(left, "p20")

    def test_explicit_threshold_legacy_display_stays_available(self) -> None:
        agent = make_agent(
            status="QUEUED",
            wait_runners=9,
            wait_runners_explicit=True,
            wait_priority=20,
            wait_priority_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=10,
        )

        with override_flags(queue_capacity_budget=False):
            left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "test_cl (QUEUED ▶10→9 p20)" in left.plain
        assert "c9" not in left.plain

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

        assert "test_cl c0 (QUEUED #2/2)" in left.plain
        assert "▶" not in left.plain
        assert _styles_covering(left, "c0") == {"dim", "#87AFD7"}
        assert (
            "Wait: [capacity] legacy capacity=0 "
            "(exact-weight drain budget) · queue #2 of 2"
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

        assert "Wait: [capacity] queue #2 of 3 · priority 20" in header.plain
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

    def test_non_default_weight_badge_renders_before_status(self) -> None:
        agent = make_agent(
            agent_name="epic.land",
            cl_name="epic.land",
            queue_weight=2.0,
            queue_weight_explicit=True,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)
        header, _ = build_header_text(agent, cheap=True)

        assert "epic.land w2 (RUNNING)" in left.plain
        assert _styles_covering(left, "w2") == {"dim", "#87D7D7"}
        assert "Weight: 2.0 capacity units" in header.plain

    def test_capacity_badge_accents_over_subscribed_budget(self) -> None:
        agent = make_agent(
            agent_name="epic.land",
            cl_name="epic.land",
            queue_weight=2.0,
            queue_weight_explicit=True,
            wait_runners=100,
            wait_runners_explicit=True,
            runner_effective_limit=10.0,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "epic.land w2 c100 (RUNNING)" in left.plain
        assert _styles_covering(left, "w2") == {"dim", "#87D7D7"}
        assert _styles_covering(left, "c100") == {"dim", "#FFD700"}

    def test_capacity_header_renders_authored_budget_with_default_weight(self) -> None:
        agent = make_agent(
            agent_name="epic.land",
            cl_name="epic.land",
            queue_weight=1.0,
            queue_weight_explicit=True,
            wait_runners=100,
            wait_runners_explicit=True,
            runner_effective_limit=10.0,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)
        header, _ = build_header_text(agent, cheap=True)

        assert "epic.land c100 (RUNNING)" in left.plain
        assert "Weight:" not in header.plain
        assert "Capacity: 100 capacity units" in header.plain
        assert _styles_covering(header, "100 capacity units") == {"#FFD700"}

    def test_capacity_badge_preserves_u32_budget_text(self) -> None:
        agent = make_agent(
            agent_name="wide.land",
            cl_name="wide.land",
            wait_runners=4294967295,
            wait_runners_explicit=True,
            runner_effective_limit=1.0,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)
        header, _ = build_header_text(agent, cheap=True)

        assert "wide.land c4294967295 (RUNNING)" in left.plain
        assert "Capacity: 4294967295 capacity units" in header.plain
        assert "4.294" not in left.plain
        assert "4.294" not in header.plain
        assert _styles_covering(left, "c4294967295") == {"dim", "#FFD700"}

    def test_default_and_synthetic_rows_hide_weight_badge(self) -> None:
        explicit_default = make_agent(
            agent_name="ordinary",
            cl_name="ordinary",
            queue_weight=1.0,
            queue_weight_explicit=True,
        )
        serial_child = make_agent(
            agent_name="epic.phase",
            cl_name="epic.phase",
            parent_timestamp="20260712120000",
            queue_weight=2.0,
            queue_weight_explicit=True,
        )

        explicit_default_left, _, _ = format_agent_option(
            explicit_default,
            0,
            is_selected=False,
        )
        serial_child_left, _, _ = format_agent_option(
            serial_child,
            0,
            is_selected=False,
        )
        explicit_default_header, _ = build_header_text(explicit_default, cheap=True)
        serial_child_header, _ = build_header_text(serial_child, cheap=True)

        assert "ordinary (RUNNING)" in explicit_default_left.plain
        assert "ordinary w1" not in explicit_default_left.plain
        assert "w2" not in serial_child_left.plain
        assert "Weight:" not in explicit_default_header.plain
        assert "Weight:" not in serial_child_header.plain

    def test_capacity_header_matches_row_suppression_and_family_member_rules(
        self,
    ) -> None:
        serial_child = make_agent(
            agent_name="epic.phase",
            cl_name="epic.phase",
            parent_timestamp="20260712120000",
            wait_runners=3,
            wait_runners_explicit=True,
        )
        parallel_child = make_agent(
            agent_name="epic.worker",
            cl_name="epic.worker",
            parent_timestamp="20260712120000",
            agent_family_parallel=True,
            wait_runners=3,
            wait_runners_explicit=True,
        )
        family_root = make_agent(
            agent_name="epic",
            cl_name="epic",
            agent_family="epic",
            agent_family_role="root",
            plan_chain_root=True,
            wait_runners=3,
            wait_runners_explicit=True,
        )
        family_root.followup_agents.append(serial_child)

        serial_header, _ = build_header_text(serial_child, cheap=True)
        parallel_header, _ = build_header_text(parallel_child, cheap=True)
        family_header, _ = build_header_text(family_root, cheap=True)

        assert "Capacity:" not in serial_header.plain
        assert "Capacity: 3 capacity units" in parallel_header.plain
        assert "Capacity: 3 capacity units" in family_header.plain

    def test_capacity_blocker_detail_distinguishes_weight_from_free_capacity(
        self,
    ) -> None:
        agent = make_agent(
            status="QUEUED",
            queue_weight=2.0,
            queue_weight_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_occupied_capacity=7.25,
            runner_effective_limit=8.0,
            runner_capacity_blockers=(
                {
                    "code": "insufficient-capacity",
                    "needed_capacity": 2.0,
                    "free_capacity": 0.75,
                },
            ),
            runner_slot_queue_position=2,
            runner_slot_queue_size=4,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)
        header, _ = build_header_text(agent, cheap=True)

        assert "test_cl w2 (QUEUED #2/4)" in left.plain
        assert "Wait: [capacity] needs 2.0 · 0.75 free · queue #2 of 4" in (
            header.plain
        )
