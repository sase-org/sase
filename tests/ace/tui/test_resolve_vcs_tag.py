"""Tests for _resolve_vcs_tag helper in agent interaction actions."""

from __future__ import annotations

from sase.ace.tui.actions.agents._wait_resume import (
    _is_coder_followup_suffix,
    _resolve_vcs_tag,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent(
    *,
    cl_name: str = "my_project",
    project_dir: str = "my_project",
    raw_content: str | None = None,
) -> Agent:
    """Create a minimal Agent for testing _resolve_vcs_tag."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=f"/tmp/{project_dir}/.gp",
        status="DONE",
        start_time=None,
    )
    # Patch get_raw_xprompt_content to return controlled content
    agent.get_raw_xprompt_content = lambda: raw_content  # type: ignore[assignment]
    return agent


class TestResolveVcsTag:
    """Tests for _resolve_vcs_tag."""

    def test_no_raw_content(self) -> None:
        agent = _make_agent(raw_content=None)
        assert _resolve_vcs_tag(agent, "foo") is None

    def test_no_vcs_tag_in_content(self) -> None:
        agent = _make_agent(raw_content="just a plain prompt")
        assert _resolve_vcs_tag(agent, "foo") is None

    def test_branch_name_substitution(self) -> None:
        """Non-project agent uses cl_name as the ref."""
        agent = _make_agent(
            cl_name="my_feature_branch",
            project_dir="my_project",
            raw_content="#git:my_project do stuff",
        )
        result = _resolve_vcs_tag(agent, "agentname")
        assert result is not None
        assert "my_feature_branch" in result
        # Should NOT contain the original ref
        assert "#git:my_project " not in result

    def test_pr_agent_uses_at_name(self) -> None:
        """Project agent with #pr in prompt uses @<name>."""
        agent = _make_agent(
            cl_name="my_project",
            project_dir="my_project",
            raw_content="#git:my_project #pr do stuff",
        )
        result = _resolve_vcs_tag(agent, "agentname")
        assert result is not None
        assert "@agentname" in result

    def test_project_agent_no_pr_unchanged(self) -> None:
        """Project agent without #pr keeps VCS tag unchanged."""
        agent = _make_agent(
            cl_name="my_project",
            project_dir="my_project",
            raw_content="#git:my_project do stuff",
        )
        result = _resolve_vcs_tag(agent, "agentname")
        assert result is not None
        assert "#git:my_project " == result

    def test_paren_format_branch_substitution(self) -> None:
        """Parenthesized VCS tag format also gets branch substitution."""
        agent = _make_agent(
            cl_name="feature_x",
            project_dir="my_project",
            raw_content="#git(my_project) do stuff",
        )
        result = _resolve_vcs_tag(agent, "agentname")
        assert result is not None
        assert "feature_x" in result

    def test_paren_format_pr_substitution(self) -> None:
        """Parenthesized VCS tag with #pr uses @<name>."""
        agent = _make_agent(
            cl_name="my_project",
            project_dir="my_project",
            raw_content="#git(my_project) #pr do stuff",
        )
        result = _resolve_vcs_tag(agent, "bob")
        assert result is not None
        assert "@bob" in result


class TestCoderFollowupSuffix:
    """Tests for plan-done resume coder follow-up classification."""

    def test_canonical_coder_suffix(self) -> None:
        assert _is_coder_followup_suffix(".code") is True

    def test_non_coder_suffix(self) -> None:
        assert _is_coder_followup_suffix(".coder") is False
        assert _is_coder_followup_suffix(".epic") is False
