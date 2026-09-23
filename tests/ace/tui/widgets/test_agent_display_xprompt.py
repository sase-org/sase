"""Tests for terminal agent xprompt rendering."""

from __future__ import annotations

from pathlib import Path

from sase import project_display_names as pdn
from sase.ace.tui.util.lazy_syntax import MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
from sase.ace.tui.util.xprompt_syntax import XPROMPT_TOKEN_STYLES

from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_artifact_agent,
    plain_of,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_logical_section_is_compact,
    assert_rendered_section_is_compact,
)
from tests.ace.tui.widgets._agent_display_xprompt_helpers import (
    _header_text,
    _styles_at,
)


class TestAgentXPromptRendering:
    def test_done_agent_renders_raw_xprompt(self, tmp_path: Path) -> None:
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="DONE")

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "Launch from @src/raw.py" in plain
        assert "AGENT PROMPT" in plain
        assert "AGENT CHAT" in plain
        rendered = panel.captured[-1]
        assert_rendered_section_is_compact(
            rendered,
            "AGENT XPROMPT",
            "Launch from @src/raw.py",
        )
        assert_rendered_section_is_compact(
            rendered,
            "AGENT PROMPT",
            "Expanded prompt body",
        )
        assert_rendered_section_is_compact(
            rendered,
            "AGENT CHAT",
            "Final response body",
        )

    def test_failed_agent_renders_raw_xprompt(self, tmp_path: Path) -> None:
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="FAILED")

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "Launch from @src/raw.py" in plain
        assert "AGENT PROMPT" in plain
        assert "AGENT CHAT" in plain

    def test_agent_prompt_and_chat_use_logical_project_name(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
        monkeypatch.setattr(
            pdn,
            "_project_display_name_map_cached",
            lambda *_args, **_kwargs: {"gh_acme__widgets": "widgets"},
        )
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="DONE")
        Path(agent.artifacts_dir, "01_prompt.md").write_text(
            "Prompt says #gh:gh_acme__widgets inspect.\n",
            encoding="utf-8",
        )
        Path(agent.response_path).write_text(
            "Response echoes #gh:gh_acme__widgets now.\n",
            encoding="utf-8",
        )

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "Prompt says #gh:widgets inspect." in plain
        assert "Response echoes #gh:widgets now." in plain
        assert "#gh:gh_acme__widgets" not in plain

    def test_custom_family_reply_summaries_include_member_ids(
        self,
        tmp_path: Path,
    ) -> None:
        root_base = tmp_path / "root"
        followup_base = tmp_path / "followup"
        root_base.mkdir()
        followup_base.mkdir()
        root = make_artifact_agent(root_base, status="DONE")
        followup = make_artifact_agent(followup_base, status="DONE")
        root.role_suffix = "--0"
        root.agent_family_role = "root"
        root.plan_chain_root = False
        root.raw_suffix = "20240101142345-root"
        followup.role_suffix = "--bar"
        followup.agent_family_role = "bar"
        followup.raw_suffix = "20240101142345-bar"
        followup.parent_timestamp = root.raw_suffix
        root.followup_agents = [followup]

        panel = FakePromptPanel()
        panel.update_display(root)
        plain = plain_of(panel.captured[-1])

        assert "AGENT REPLY · 2" in plain
        assert "▾ AGENT REPLY" not in plain
        assert "AGENT (0) · ✓ DONE" in plain
        assert "AGENT (bar) · ✓ DONE" in plain
        assert "AGENT (q)" not in plain

    def test_running_reply_placeholders_are_compact(self, tmp_path: Path) -> None:
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="RUNNING")

        panel.update_display(agent)
        assert_rendered_section_is_compact(
            panel.captured[-1],
            "AGENT REPLY",
            "Waiting for agent response...",
        )

        panel.update_display_with_hints(agent)
        assert_logical_section_is_compact(
            panel.captured[-1],
            "AGENT REPLY",
            "Waiting for agent response...",
        )
        assert_rendered_section_is_compact(
            panel.captured[-1],
            "AGENT REPLY",
            "Waiting for agent response...",
        )

    def test_oversized_xprompt_falls_back_to_plain_text(
        self,
        tmp_path: Path,
    ) -> None:
        panel = FakePromptPanel()
        raw_xprompt = "#foo " + "x" * MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt=raw_xprompt,
        )

        panel.update_display(agent)

        header = _header_text(panel.captured[-1])
        assert raw_xprompt in header.plain
        assert XPROMPT_TOKEN_STYLES["invocation"] not in _styles_at(header, "#foo")
