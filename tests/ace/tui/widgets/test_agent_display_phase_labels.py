"""Tests for agent display phase labels."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_panel._agent_display_parts import get_phase_label
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestGetPhaseLabel:
    def test_plan(self) -> None:
        agent = make_agent(role_suffix=".plan")
        assert get_phase_label(agent) == "AGENT (plan)"

    def test_plan_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-plan")
        assert get_phase_label(agent) == "AGENT (plan)"

    def test_code(self) -> None:
        agent = make_agent(role_suffix=".code")
        assert get_phase_label(agent) == "AGENT (code)"

    def test_code_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-code")
        assert get_phase_label(agent) == "AGENT (code)"

    def test_questions(self) -> None:
        agent = make_agent(role_suffix=".q")
        assert get_phase_label(agent) == "AGENT (q)"

    def test_questions_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-q")
        assert get_phase_label(agent) == "AGENT (q)"

    def test_epic(self) -> None:
        agent = make_agent(role_suffix=".epic")
        assert get_phase_label(agent) == "AGENT (epic)"

    def test_epic_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-epic")
        assert get_phase_label(agent) == "AGENT (epic)"

    def test_commit(self) -> None:
        agent = make_agent(role_suffix="-commit")
        assert get_phase_label(agent) == "AGENT (commit)"

    def test_legacy_commit(self) -> None:
        agent = make_agent(role_suffix=".commit")
        assert get_phase_label(agent) == "AGENT (commit)"

    def test_monitor(self) -> None:
        agent = make_agent(role_suffix="--mon")
        assert get_phase_label(agent) == "MONITOR"

    def test_monitor_numbered_suffix(self) -> None:
        agent = make_agent(role_suffix="--mon-1")
        assert get_phase_label(agent) == "MONITOR"

    def test_monitor_stored_role_unrecognized_suffix(self) -> None:
        agent = make_agent(role_suffix="--weird", agent_family_role="monitor")
        assert get_phase_label(agent) == "MONITOR"

    def test_gate(self) -> None:
        agent = make_agent(
            role_suffix="--gate",
            agent_family_role="gate",
            gate_id="g123",
        )
        assert get_phase_label(agent) == "GATE"

    def test_feedback_round_2(self) -> None:
        agent = make_agent(role_suffix=".2")
        assert get_phase_label(agent) == "AGENT (plan round 2)"

    def test_new_feedback_round_2(self) -> None:
        agent = make_agent(role_suffix="--plan-0", agent_family_role="feedback")
        assert get_phase_label(agent) == "AGENT (plan round 2)"

    def test_feedback_round_2_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-2")
        assert get_phase_label(agent) == "AGENT (plan round 2)"

    def test_feedback_round_10(self) -> None:
        agent = make_agent(role_suffix=".10")
        assert get_phase_label(agent) == "AGENT (plan round 10)"

    def test_feedback_round_10_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-10")
        assert get_phase_label(agent) == "AGENT (plan round 10)"

    def test_root_question_numeric_label(self) -> None:
        agent = make_agent(role_suffix="--2", agent_family_role="q")
        assert get_phase_label(agent) == "AGENT (q)"

    def test_promoted_root_question_fallback_label(self) -> None:
        agent = make_agent(
            role_suffix="--q",
            agent_family_role="root",
            plan_chain_root=False,
        )
        assert get_phase_label(agent) == "AGENT (q)"

    def test_custom_member_label_includes_suffix_token(self) -> None:
        agent = make_agent(role_suffix="--bar", agent_family_role="bar")
        assert get_phase_label(agent) == "AGENT (bar)"

    def test_custom_named_member_label_includes_suffix_token(self) -> None:
        agent = make_agent(role_suffix="--reviewer", agent_family_role="reviewer")
        assert get_phase_label(agent) == "AGENT (reviewer)"

    def test_promoted_bare_root_uses_suffix_token(self) -> None:
        agent = make_agent(
            role_suffix="--0",
            agent_family_role="root",
            plan_chain_root=False,
        )
        assert get_phase_label(agent) == "AGENT (0)"

    def test_promoted_bare_root_one_uses_suffix_token(self) -> None:
        agent = make_agent(
            role_suffix="--1",
            agent_family_role="root",
            plan_chain_root=False,
        )
        assert get_phase_label(agent) == "AGENT (1)"

    def test_plan_chain_root_still_uses_phase_label(self) -> None:
        agent = make_agent(
            role_suffix="--plan",
            agent_family_role="root",
            plan_chain_root=True,
        )
        assert get_phase_label(agent) == "AGENT (plan)"

    def test_genuine_question_member_still_uses_question_label(self) -> None:
        agent = make_agent(role_suffix="--0", agent_family_role="q")
        assert get_phase_label(agent) == "AGENT (q)"

    def test_code_question_continuation_label(self) -> None:
        agent = make_agent(role_suffix="--code-0", agent_family_role="code")
        assert get_phase_label(agent) == "AGENT (code)"

    def test_no_suffix(self) -> None:
        agent = make_agent(role_suffix=None)
        assert get_phase_label(agent) == "AGENT"

    def test_unknown_suffix(self) -> None:
        agent = make_agent(role_suffix=".xyz")
        assert get_phase_label(agent) == "AGENT (xyz)"
