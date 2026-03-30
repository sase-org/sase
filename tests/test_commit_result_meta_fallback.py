"""Tests for commit_result.json metadata fallback in artifact loaders."""

import json
from pathlib import Path

from sase.ace.tui.models._loaders._artifact_loaders import (
    _enrich_agent_from_prompt_markers,
    meta_from_commit_result,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent() -> Agent:
    """Create a minimal Agent for testing."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
    )


# --- meta_from_commit_result tests ---


class TestMetaFromCommitResult:
    def test_derives_all_fields(self, tmp_path: Path) -> None:
        data = {
            "method": "create_commit",
            "result": "abc123",
            "message": "feat: add feature",
            "name": "my_cl",
            "changespec_name": "proj_feat_1",
        }
        (tmp_path / "commit_result.json").write_text(json.dumps(data))

        meta = meta_from_commit_result(str(tmp_path))

        assert meta == {
            "meta_new_commit": "abc123",
            "meta_commit_message": "feat: add feature",
            "meta_changespec": "proj_feat_1",
        }

    def test_changespec_falls_back_to_name(self, tmp_path: Path) -> None:
        data = {
            "method": "create_commit",
            "result": "abc123",
            "message": "fix: bug",
            "name": "my_cl",
            "changespec_name": "",
        }
        (tmp_path / "commit_result.json").write_text(json.dumps(data))

        meta = meta_from_commit_result(str(tmp_path))

        assert meta["meta_changespec"] == "my_cl"

    def test_omits_empty_fields(self, tmp_path: Path) -> None:
        data = {
            "method": "create_commit",
            "result": None,
            "message": "",
            "name": "",
            "changespec_name": None,
        }
        (tmp_path / "commit_result.json").write_text(json.dumps(data))

        meta = meta_from_commit_result(str(tmp_path))

        assert meta == {}

    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        meta = meta_from_commit_result(str(tmp_path))
        assert meta == {}

    def test_returns_empty_on_malformed_json(self, tmp_path: Path) -> None:
        (tmp_path / "commit_result.json").write_text("not json")

        meta = meta_from_commit_result(str(tmp_path))

        assert meta == {}

    def test_returns_empty_on_non_dict(self, tmp_path: Path) -> None:
        (tmp_path / "commit_result.json").write_text('"just a string"')

        meta = meta_from_commit_result(str(tmp_path))

        assert meta == {}


# --- _enrich_agent_from_prompt_markers fallback tests ---


class TestEnrichAgentCommitResultFallback:
    def test_stop_hook_scenario_no_prompt_steps(self, tmp_path: Path) -> None:
        """commit_result.json exists but no prompt_step files — meta synthesized."""
        data = {
            "method": "create_commit",
            "result": "def456",
            "message": "fix: stop-hook commit",
            "name": "",
            "changespec_name": "proj_fix_1",
        }
        (tmp_path / "commit_result.json").write_text(json.dumps(data))

        agent = _make_agent()
        _enrich_agent_from_prompt_markers(agent, str(tmp_path))

        assert agent.step_output is not None
        assert agent.step_output["meta_commit_message"] == "fix: stop-hook commit"
        assert agent.step_output["meta_new_commit"] == "def456"
        assert agent.step_output["meta_changespec"] == "proj_fix_1"

    def test_prompt_step_meta_takes_precedence(self, tmp_path: Path) -> None:
        """Explicit meta from prompt_step is NOT overwritten by commit_result."""
        step_data = {
            "output": {
                "meta_commit_message": "from prompt step",
                "meta_other": "value",
            }
        }
        (tmp_path / "prompt_step_001.json").write_text(json.dumps(step_data))

        commit_data = {
            "method": "create_commit",
            "result": "abc123",
            "message": "from commit result",
            "name": "",
            "changespec_name": "cs1",
        }
        (tmp_path / "commit_result.json").write_text(json.dumps(commit_data))

        agent = _make_agent()
        _enrich_agent_from_prompt_markers(agent, str(tmp_path))

        assert agent.step_output is not None
        # Prompt step value wins
        assert agent.step_output["meta_commit_message"] == "from prompt step"
        # Other fields from prompt step preserved
        assert agent.step_output["meta_other"] == "value"
        # Fallback fills in missing keys
        assert agent.step_output["meta_new_commit"] == "abc123"
        assert agent.step_output["meta_changespec"] == "cs1"

    def test_no_commit_result_no_prompt_steps(self, tmp_path: Path) -> None:
        """Neither commit_result.json nor prompt_step files — no step_output."""
        agent = _make_agent()
        _enrich_agent_from_prompt_markers(agent, str(tmp_path))

        assert agent.step_output is None

    def test_existing_step_output_preserved(self, tmp_path: Path) -> None:
        """Pre-existing step_output on agent is extended, not replaced."""
        data = {
            "method": "create_commit",
            "result": "xyz",
            "message": "commit msg",
            "name": "",
            "changespec_name": "",
        }
        (tmp_path / "commit_result.json").write_text(json.dumps(data))

        agent = _make_agent()
        agent.step_output = {"existing_key": "existing_value"}
        _enrich_agent_from_prompt_markers(agent, str(tmp_path))

        assert agent.step_output["existing_key"] == "existing_value"
        assert agent.step_output["meta_commit_message"] == "commit msg"
