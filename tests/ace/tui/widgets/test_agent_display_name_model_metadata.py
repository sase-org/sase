"""Tests for agent display name and model metadata."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
    AgentHeaderRenderable,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_header_text,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_metadata_prefix,
    assert_span_covers,
)

_FAMILY_NAME = "family"
_ROOT_SUFFIX = "20260805130000"


def _family_root(
    *, role_suffix: str = "--plan", agent_family_role: str = "plan", **overrides: object
) -> Agent:
    return make_agent(
        agent_family=_FAMILY_NAME,
        agent_family_role=agent_family_role,
        plan_chain_root=True,
        raw_suffix=_ROOT_SUFFIX,
        role_suffix=role_suffix,
        **overrides,
    )


def _family_member(
    role_suffix: str, agent_family_role: str, **overrides: object
) -> Agent:
    return make_agent(
        agent_family=_FAMILY_NAME,
        agent_family_role=agent_family_role,
        parent_timestamp=_ROOT_SUFFIX,
        role_suffix=role_suffix,
        **overrides,
    )


def _family(root: Agent, *members: Agent) -> Agent:
    root.followup_agents = list(members)
    return root


class TestAgentNameMetadata:
    def test_unnamed_agent_renders_unassigned_name_first(self) -> None:
        agent = make_agent()

        header, _ = build_header_text(agent, cheap=True)

        assert header.plain.count("Name: ") == 1
        assert_metadata_prefix(header, "Name: unassigned")
        assert_span_covers(header, "unassigned", "dim")
        assert header.plain.index("Name: unassigned\n") < header.plain.index(
            "ChangeSpec:"
        )
        assert "Bead:" not in header.plain

    def test_named_agent_renders_name_first(self) -> None:
        agent = make_agent(agent_name="reviewer")

        header, _ = build_header_text(agent, cheap=True)

        assert header.plain.count("Name: ") == 1
        assert_metadata_prefix(header, "Name: reviewer")
        assert_span_covers(header, "reviewer", "#FFD700")
        assert header.plain.index("Name: reviewer\n") < header.plain.index(
            "ChangeSpec:"
        )

    def test_retry_chain_renders_name_before_retry_chain(self) -> None:
        agent = make_agent(
            agent_name="reviewer",
            retry_attempt=2,
            retry_error_category="rate_limit",
        )

        header, _ = build_header_text(agent, cheap=True)

        assert_metadata_prefix(header, "Name: reviewer")
        assert "Retry chain: ↻ attempt #2 (rate_limit)\n" in header.plain
        assert header.plain.index("Name: reviewer\n") < header.plain.index(
            "Retry chain:"
        )


class TestAgentModelMetadata:
    def test_non_agent_workflow_child_omits_model(self) -> None:
        agent = make_agent(
            agent_type=AgentType.WORKFLOW,
            parent_workflow="wf",
            step_name="diff",
            step_type="bash",
            step_index=0,
            total_steps=2,
            model="opus",
            llm_provider="claude",
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "Step: diff\n" in header.plain
        assert "Model:" not in header.plain

    def test_agent_workflow_child_renders_model(self) -> None:
        agent = make_agent(
            agent_type=AgentType.WORKFLOW,
            parent_workflow="wf",
            step_name="write",
            step_type="agent",
            step_index=1,
            total_steps=2,
            model="opus",
            llm_provider="claude",
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "Model: CLAUDE(opus)\n" in header.plain

    def test_top_level_agent_renders_model(self) -> None:
        agent = make_agent(model="opus", llm_provider="claude")

        header, _ = build_header_text(agent, cheap=True)

        assert "Model: CLAUDE(opus)\n" in header.plain


class TestFamilyModelMetadata:
    def test_family_container_header_shows_one_lane_per_member_in_order(self) -> None:
        agent = _family(
            _family_root(model="opus", llm_provider="claude", reasoning_effort="xhigh"),
            _family_member("--code", "code", model="sonnet", llm_provider="claude"),
            _family_member(
                "--reviewer", "reviewer", model="gpt-5.2", llm_provider="codex"
            ),
        )

        header, _ = build_header_text(agent, cheap=True)

        assert header.plain.count("Model: ") == 1
        assert "Model: --plan     · CLAUDE(opus) @ xhigh\n" in header.plain
        assert "       --code     · CLAUDE(sonnet)\n" in header.plain
        assert "       --reviewer · CODEX(gpt-5.2)\n" in header.plain
        model_index = header.plain.index("Model:")
        code_index = header.plain.index("--code")
        reviewer_index = header.plain.index("--reviewer")
        assert model_index < code_index < reviewer_index

    def test_model_still_sits_between_auto_and_xprompts_for_family_row(self) -> None:
        agent = _family(
            _family_root(approve=True, model="opus", llm_provider="claude"),
            _family_member("--code", "code", model="sonnet", llm_provider="claude"),
        )
        summary = DetailHeaderSummary(
            xprompts_used=[{"kind": "part", "name": "plan"}],
        )

        header, _ = build_header_text(agent, cheap=False, summary=summary)

        auto_index = header.plain.index("Auto:")
        model_index = header.plain.index("Model:")
        xprompts_index = header.plain.index("Xprompts:")
        assert auto_index < model_index < xprompts_index

    def test_non_family_agent_keeps_unchanged_single_line_model(self) -> None:
        agent = make_agent(model="opus", llm_provider="claude", followup_agents=[])

        header, _ = build_header_text(agent, cheap=True)

        assert header.plain.count("Model: ") == 1
        assert "Model: CLAUDE(opus)\n" in header.plain

    def test_family_projection_below_two_members_falls_back_to_single_line(
        self,
    ) -> None:
        agent = _family_root(model="opus", llm_provider="claude")

        header, _ = build_header_text(agent, cheap=True)

        assert header.plain.count("Model: ") == 1
        assert "Model: CLAUDE(opus)\n" in header.plain

    def test_family_header_is_renderable_with_full_lane_block_in_plain(self) -> None:
        agent = _family(
            _family_root(model="opus", llm_provider="claude"),
            _family_member("--code", "code", model="sonnet", llm_provider="claude"),
        )

        header, _ = build_header_text(agent, cheap=True)

        assert isinstance(header, AgentHeaderRenderable)
        assert "Model: --plan · CLAUDE(opus)\n" in header.plain
        assert "       --code · CLAUDE(sonnet)\n" in header.plain


class TestAgentAutoApproveMetadata:
    def test_plain_auto_approve_renders_plan_token(self) -> None:
        agent = make_agent(approve=True)

        header, _ = build_header_text(agent, cheap=True)

        assert "Auto: \u26a1 PLAN\n" in header.plain
        assert "Mode:" not in header.plain
        assert "Auto-Approve" not in header.plain
        assert "Epic Auto-Approve" not in header.plain
        assert_span_covers(header, "\u26a1 PLAN", "bold #5FD7FF")

    def test_tale_auto_approve_renders_tale_token(self) -> None:
        agent = make_agent(approve=True, auto_approve_plan_action="tale")

        header, _ = build_header_text(agent, cheap=True)

        assert "Auto: \u26a1 TALE\n" in header.plain
        assert "Mode:" not in header.plain
        assert "Auto-Approve" not in header.plain
        assert_span_covers(header, "\u26a1 TALE", "bold #FFD75F")

    def test_epic_auto_approve_renders_epic_token(self) -> None:
        agent = make_agent(approve=True, auto_approve_plan_action="epic")

        header, _ = build_header_text(agent, cheap=True)

        assert "Auto: \u26a1 EPIC\n" in header.plain
        assert "Mode:" not in header.plain
        assert "Auto-Approve" not in header.plain
        assert "Epic Auto-Approve" not in header.plain
        assert_span_covers(header, "\u26a1 EPIC", "bold #AF87FF")

    def test_disabled_auto_approve_omits_auto_field(self) -> None:
        agent = make_agent(approve=False)

        header, _ = build_header_text(agent, cheap=True)

        assert "Auto:" not in header.plain
        assert "Mode:" not in header.plain
        assert "Auto-Approve" not in header.plain

    def test_auto_field_renders_before_xprompts_without_model(self) -> None:
        # No-model agent: ``Model:`` is omitted, so ``Auto:`` is adjacent to
        # ``Xprompts:`` with nothing rendered between them.
        agent = make_agent(approve=True)
        summary = DetailHeaderSummary(
            xprompts_used=[{"kind": "part", "name": "plan"}],
        )

        header, _ = build_header_text(agent, cheap=False, summary=summary)

        assert "Auto: ⚡ PLAN\n" in header.plain
        assert "Xprompts:" in header.plain
        assert "Model:" not in header.plain
        auto_index = header.plain.index("Auto:")
        xprompts_index = header.plain.index("Xprompts:")
        assert auto_index < xprompts_index
        # Nothing renders between the Auto field and the Xprompts section.
        between = header.plain[auto_index:xprompts_index]
        assert between == "Auto: ⚡ PLAN\n"
        assert "Mode:" not in header.plain
        assert "Auto-Approve" not in header.plain

    def test_auto_model_xprompts_render_in_order(self) -> None:
        # With auto-approval, a renderable model, and xprompt metadata the
        # rows render as Auto: then Model: then Xprompts:.
        agent = make_agent(approve=True, model="opus", llm_provider="claude")
        summary = DetailHeaderSummary(
            xprompts_used=[{"kind": "part", "name": "plan"}],
        )

        header, _ = build_header_text(agent, cheap=False, summary=summary)

        assert "Auto: ⚡ PLAN\n" in header.plain
        assert "Model: CLAUDE(opus)\n" in header.plain
        assert "Xprompts:" in header.plain
        auto_index = header.plain.index("Auto:")
        model_index = header.plain.index("Model:")
        xprompts_index = header.plain.index("Xprompts:")
        assert auto_index < model_index < xprompts_index
        # Only the Model row renders between Auto and Xprompts.
        between = header.plain[auto_index:xprompts_index]
        assert between == "Auto: ⚡ PLAN\nModel: CLAUDE(opus)\n"
        assert "Mode:" not in header.plain
        assert "Auto-Approve" not in header.plain

    def test_model_renders_before_xprompts_without_auto(self) -> None:
        # Without auto-approval, ``Model:`` still renders before the
        # ``Xprompts:`` section.
        agent = make_agent(model="opus", llm_provider="claude")
        summary = DetailHeaderSummary(
            xprompts_used=[{"kind": "part", "name": "plan"}],
        )

        header, _ = build_header_text(agent, cheap=False, summary=summary)

        assert "Auto:" not in header.plain
        assert "Model: CLAUDE(opus)\n" in header.plain
        assert "Xprompts:" in header.plain
        model_index = header.plain.index("Model:")
        xprompts_index = header.plain.index("Xprompts:")
        assert model_index < xprompts_index
