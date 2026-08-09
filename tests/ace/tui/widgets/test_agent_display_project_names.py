"""Tests for agent display project name rendering."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import grouping_keys_for_agents
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._workflow_render import (
    build_workflow_detail_renderable,
)
from sase.ace.tui.widgets.prompt_panel._workflow_types import WorkflowDetailSnapshot
from tests.ace.tui.widgets._agent_display_helpers import make_agent, plain_of


def _project_agent(project_display_name: str | None = "widgets") -> Agent:
    return make_agent(
        cl_name="gh_acme__widgets",
        project_file="/tmp/gh_acme__widgets/gh_acme__widgets.sase",
        project_display_name=project_display_name,
    )


class TestProjectDisplayNameRendering:
    def test_project_agent_row_uses_logical_project_name(self) -> None:
        agent = _project_agent()

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "widgets" in left.plain
        assert "gh_acme__widgets" not in left.plain

    def test_project_agent_row_falls_back_to_directory_key(self) -> None:
        agent = _project_agent(project_display_name=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "gh_acme__widgets" in left.plain

    def test_project_agent_header_uses_logical_project_name(self) -> None:
        agent = _project_agent()

        header, _ = build_header_text(agent, cheap=True)

        assert "Project: widgets" in header.plain
        assert "Project: gh_acme__widgets" not in header.plain

    def test_xprompt_args_use_logical_project_name(self) -> None:
        agent = _project_agent()
        summary = DetailHeaderSummary(
            xprompts_used=[
                {
                    "kind": "workflow",
                    "name": "gh",
                    "positional": ["gh_acme__widgets", "--flag"],
                    "named": {"project": "gh_acme__widgets"},
                }
            ],
        )

        header, _ = build_header_text(agent, summary=summary)

        assert "Xprompts:" in header.plain
        assert "widgets" in header.plain
        assert "gh_acme__widgets" not in header.plain
        assert "--flag" in header.plain

    def test_xprompt_args_fall_back_to_directory_key(self) -> None:
        agent = _project_agent(project_display_name=None)
        summary = DetailHeaderSummary(
            xprompts_used=[
                {
                    "kind": "workflow",
                    "name": "gh",
                    "positional": ["gh_acme__widgets", "literal"],
                }
            ],
        )

        header, _ = build_header_text(agent, summary=summary)

        assert "gh_acme__widgets" in header.plain
        assert "literal" in header.plain

    def test_meta_project_header_uses_logical_project_name(self) -> None:
        agent = _project_agent()
        agent.step_output = {"meta_project": "gh_acme__widgets"}

        header, _ = build_header_text(agent, cheap=True)

        assert "Project: widgets" in header.plain
        assert "Project: gh_acme__widgets" not in header.plain

    def test_workflow_meta_project_header_uses_logical_project_name(self) -> None:
        agent = _project_agent()
        agent.agent_type = AgentType.WORKFLOW
        agent.workflow = "status"
        snapshot = WorkflowDetailSnapshot(
            artifacts_path=None,
            workflow_state=None,
            inputs=None,
            meta_raw={"meta_project": "gh_acme__widgets"},
            meta_fields=[],
            steps=[],
            error=None,
            traceback=None,
            prompt_content=None,
            embedded_markers={},
            embedded_meta={},
        )

        plain = plain_of(build_workflow_detail_renderable(agent, snapshot))

        assert "Project: widgets" in plain
        assert "Project: gh_acme__widgets" not in plain

    def test_workflow_prompt_uses_logical_project_name(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "sase.ace.tui.widgets.prompt_panel._workflow_render.humanize_vcs_refs_in_text",
            lambda text: text.replace("gh_acme__widgets", "widgets"),
        )
        agent = _project_agent()
        agent.agent_type = AgentType.WORKFLOW
        agent.workflow = "status"
        snapshot = WorkflowDetailSnapshot(
            artifacts_path=None,
            workflow_state=None,
            inputs=None,
            meta_raw={},
            meta_fields=[],
            steps=[],
            error=None,
            traceback=None,
            prompt_content="#gh:gh_acme__widgets inspect",
            embedded_markers={},
            embedded_meta={},
        )

        plain = plain_of(build_workflow_detail_renderable(agent, snapshot))

        assert "#gh:widgets inspect" in plain
        assert "#gh:gh_acme__widgets" not in plain

    def test_dotless_logical_project_name_keeps_empty_grouping_name_root(
        self,
    ) -> None:
        agent = _project_agent()

        keys = grouping_keys_for_agents([agent])

        assert keys[0].project == "widgets"
        assert keys[0].patch == ""
        assert keys[0].name_root == ""
