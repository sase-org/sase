"""Tests for terminal agent xprompt rendering."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_artifact_agent,
    plain_of,
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

    def test_failed_agent_renders_raw_xprompt(self, tmp_path: Path) -> None:
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="FAILED")

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "Launch from @src/raw.py" in plain
        assert "AGENT PROMPT" in plain
        assert "AGENT CHAT" in plain

    def test_hint_mode_renders_raw_xprompt_for_terminal_agent(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
        )

        hint_mappings = panel.update_display_with_hints(agent)

        plain = plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "[1] @src/raw.py" in plain
        assert hint_mappings[1] == str(workspace_dir / "src/raw.py")

    def test_hint_mode_renders_timestamp_file_hints_before_body_hints(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
        )
        Path(agent.artifacts_dir, "01_prompt.md").write_text(
            "Expanded prompt mentions src/prompt.py\n",
            encoding="utf-8",
        )
        feedback_time = datetime(2024, 1, 1, 14, 25, 0)
        rejected_plan_path = (
            Path.home() / ".sase" / "plans" / "202605" / "wait_requires_success.md"
        )
        expected_hint_path = os.path.expanduser(
            "~/.sase/plans/202605/wait_requires_success.md"
        )
        agent.feedback_times = [feedback_time]
        agent.feedback_plan_paths = {feedback_time: str(rejected_plan_path)}

        hint_mappings = panel.update_display_with_hints(agent)

        plain = plain_of(panel.captured[-1])
        assert "[1] ~/.sase/plans/202605/wait_requires_success.md" in plain
        assert "[2] @src/raw.py" in plain
        assert "[3] src/prompt.py" in plain
        assert hint_mappings[1] == expected_hint_path
        assert hint_mappings[2] == str(workspace_dir / "src/raw.py")
        assert hint_mappings[3] == str(workspace_dir / "src/prompt.py")


# -- _get_phase_label ---------------------------------------------------------
