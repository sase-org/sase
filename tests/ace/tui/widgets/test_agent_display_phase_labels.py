"""Tests for agent display phase labels."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_panel._agent_display_parts import get_phase_label
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestGetPhaseLabel:
    def test_plan(self) -> None:
        agent = make_agent(role_suffix=".plan")
        assert get_phase_label(agent) == "PLANNER"

    def test_plan_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-plan")
        assert get_phase_label(agent) == "PLANNER"

    def test_code(self) -> None:
        agent = make_agent(role_suffix=".code")
        assert get_phase_label(agent) == "CODER"

    def test_code_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-code")
        assert get_phase_label(agent) == "CODER"

    def test_questions(self) -> None:
        agent = make_agent(role_suffix=".q")
        assert get_phase_label(agent) == "QUESTIONS"

    def test_questions_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-q")
        assert get_phase_label(agent) == "QUESTIONS"

    def test_epic(self) -> None:
        agent = make_agent(role_suffix=".epic")
        assert get_phase_label(agent) == "EPIC"

    def test_epic_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-epic")
        assert get_phase_label(agent) == "EPIC"

    def test_legend(self) -> None:
        agent = make_agent(role_suffix="-legend")
        assert get_phase_label(agent) == "LEGEND"

    def test_legacy_legend(self) -> None:
        agent = make_agent(role_suffix=".legend")
        assert get_phase_label(agent) == "LEGEND"

    def test_commit(self) -> None:
        agent = make_agent(role_suffix="-commit")
        assert get_phase_label(agent) == "COMMIT"

    def test_legacy_commit(self) -> None:
        agent = make_agent(role_suffix=".commit")
        assert get_phase_label(agent) == "COMMIT"

    def test_feedback_round_2(self) -> None:
        agent = make_agent(role_suffix=".2")
        assert get_phase_label(agent) == "PLANNER (round 2)"

    def test_new_feedback_round_2(self) -> None:
        agent = make_agent(role_suffix="--plan-0", agent_family_role="feedback")
        assert get_phase_label(agent) == "PLANNER (round 2)"

    def test_feedback_round_2_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-2")
        assert get_phase_label(agent) == "PLANNER (round 2)"

    def test_feedback_round_10(self) -> None:
        agent = make_agent(role_suffix=".10")
        assert get_phase_label(agent) == "PLANNER (round 10)"

    def test_feedback_round_10_hyphen_suffix(self) -> None:
        agent = make_agent(role_suffix="-10")
        assert get_phase_label(agent) == "PLANNER (round 10)"

    def test_root_question_numeric_label(self) -> None:
        agent = make_agent(role_suffix="--2", agent_family_role="q")
        assert get_phase_label(agent) == "QUESTIONS"

    def test_code_question_continuation_label(self) -> None:
        agent = make_agent(role_suffix="--code-0", agent_family_role="code")
        assert get_phase_label(agent) == "CODER"

    def test_no_suffix(self) -> None:
        agent = make_agent(role_suffix=None)
        assert get_phase_label(agent) == "AGENT"

    def test_unknown_suffix(self) -> None:
        agent = make_agent(role_suffix=".xyz")
        assert get_phase_label(agent) == "AGENT"
