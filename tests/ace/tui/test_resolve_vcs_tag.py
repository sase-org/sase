"""Tests for _resolve_vcs_tag helper in agent interaction actions."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents import _fork_scope
from sase.ace.tui.actions.agents._fork_scope import (
    _ForkVcsMember,
    _resolve_vcs_tag_consensus,
)
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
        project_file=f"/tmp/{project_dir}/.sase",
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

    def test_project_agent_tag_uses_display_project_name(
        self, monkeypatch: Any
    ) -> None:
        """Project agent prefill tags use the configured display project name."""
        monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"git"})
        monkeypatch.setattr(
            "sase.project_display_names._project_display_name_map_cached",
            lambda _projects_root=None: {"gh_acme__widgets": "widgets"},
        )
        agent = _make_agent(
            cl_name="gh_acme__widgets",
            project_dir="gh_acme__widgets",
            raw_content="#git:gh_acme__widgets do stuff",
        )

        result = _resolve_vcs_tag(agent, "agentname")

        assert result == "#git:widgets "

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

    def test_embedded_tag_second_line_project_agent(self) -> None:
        """VCS tag embedded on line 2 is recovered for project agents."""
        agent = _make_agent(
            cl_name="my_project",
            project_dir="my_project",
            raw_content="some intro line\n#git:my_project do stuff",
        )
        result = _resolve_vcs_tag(agent, "agentname")
        assert result == "#git:my_project "

    def test_embedded_tag_mid_line_branch_substitution(self) -> None:
        """VCS tag embedded mid-line is recovered and branch substitution applies."""
        agent = _make_agent(
            cl_name="my_feature_branch",
            project_dir="my_project",
            raw_content="tweak #git:my_project quickly",
        )
        result = _resolve_vcs_tag(agent, "agentname")
        assert result is not None
        assert "my_feature_branch" in result
        assert "#git:my_project " not in result


class TestResolveVcsTagConsensus:
    """Tests for strict group VCS inheritance."""

    def test_colon_and_parenthesized_tags_compare_canonically(self) -> None:
        colon = _make_agent(
            raw_content="#git:my_project do stuff",
        )
        paren = _make_agent(
            raw_content="#git(my_project) do other stuff",
        )

        result = _resolve_vcs_tag_consensus(
            (
                _ForkVcsMember(colon, "colon"),
                _ForkVcsMember(paren, "paren"),
            ),
            (colon, paren),
        )

        assert result == "#git:my_project "

    def test_different_branches_omit_group_prefix(self) -> None:
        first = _make_agent(
            cl_name="branch_one",
            raw_content="#git:my_project do stuff",
        )
        second = _make_agent(
            cl_name="branch_two",
            raw_content="#git:my_project do stuff",
        )

        assert (
            _resolve_vcs_tag_consensus(
                (
                    _ForkVcsMember(first, "first"),
                    _ForkVcsMember(second, "second"),
                ),
                (first, second),
            )
            is None
        )

    def test_tagged_and_untagged_members_omit_group_prefix(self) -> None:
        tagged = _make_agent(raw_content="#git:my_project do stuff")
        untagged = _make_agent(raw_content="do stuff")

        assert (
            _resolve_vcs_tag_consensus(
                (
                    _ForkVcsMember(tagged, "tagged"),
                    _ForkVcsMember(untagged, "untagged"),
                ),
                (tagged, untagged),
            )
            is None
        )

    def test_mixed_workflow_types_omit_group_prefix(self, monkeypatch: Any) -> None:
        first = _make_agent(cl_name="first")
        second = _make_agent(cl_name="second")
        monkeypatch.setattr(
            _fork_scope,
            "_raw_vcs_tag",
            lambda agent, _name, _agents: (
                "#git:shared " if agent is first else "#gh:shared "
            ),
        )
        monkeypatch.setattr(
            "sase.workspace_provider.get_workflow_names",
            lambda: {"git", "gh"},
        )

        assert (
            _resolve_vcs_tag_consensus(
                (
                    _ForkVcsMember(first, "first"),
                    _ForkVcsMember(second, "second"),
                ),
                (first, second),
            )
            is None
        )

    def test_pr_smart_refs_that_diverge_by_member_omit_prefix(self) -> None:
        first = _make_agent(raw_content="#git:my_project #pr do stuff")
        second = _make_agent(raw_content="#git:my_project #pr do stuff")

        assert (
            _resolve_vcs_tag_consensus(
                (
                    _ForkVcsMember(first, "alice"),
                    _ForkVcsMember(second, "bob"),
                ),
                (first, second),
            )
            is None
        )


class TestCoderFollowupSuffix:
    """Tests for plan-done resume coder follow-up classification."""

    def test_canonical_coder_suffix(self) -> None:
        assert _is_coder_followup_suffix(".code") is True
        assert _is_coder_followup_suffix("--code") is True

    def test_non_coder_suffix(self) -> None:
        assert _is_coder_followup_suffix("--code-0") is False
        assert _is_coder_followup_suffix(".coder") is False
        assert _is_coder_followup_suffix(".epic") is False
