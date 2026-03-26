"""Tests for @name agent reference resolution."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.names import _AgentRefError, _NamedAgent, resolve_agent_changespec
from sase.axe.run_agent_phases import resolve_agent_refs_in_prompt

_MOCK_WORKFLOW_NAMES = MagicMock(return_value={"gh", "git", "hg"})


@pytest.fixture(autouse=True)
def _mock_vcs_names():
    """Ensure VCS workflow names include 'gh' regardless of installed plugins."""
    with (
        patch("sase.workspace_provider.get_workflow_names", _MOCK_WORKFLOW_NAMES),
        patch(
            "sase.workspace_provider._registry.get_workflow_names",
            _MOCK_WORKFLOW_NAMES,
        ),
        patch("sase.xprompt._parsing._VCS_TAG_PATTERN", None),
        patch("sase.xprompt._parsing._VCS_UNDERSCORE_NORMALIZER", None),
    ):
        yield


# ---------------------------------------------------------------------------
# resolve_agent_changespec() tests
# ---------------------------------------------------------------------------


class TestResolveAgentChangespec:
    def test_agent_not_found(self) -> None:
        with patch("sase.agent.names.find_named_agent", return_value=None):
            with pytest.raises(_AgentRefError, match="No agent found with name 'x'"):
                resolve_agent_changespec("x")

    def test_agent_still_running(self) -> None:
        agent = _NamedAgent(
            name="a", artifacts_dir="/tmp/a", is_done=False, outcome=None
        )
        with patch("sase.agent.names.find_named_agent", return_value=agent):
            with pytest.raises(_AgentRefError, match="still running"):
                resolve_agent_changespec("a")

    def test_agent_failed(self) -> None:
        agent = _NamedAgent(
            name="a", artifacts_dir="/tmp/a", is_done=True, outcome="failed"
        )
        with patch("sase.agent.names.find_named_agent", return_value=agent):
            with pytest.raises(_AgentRefError, match="failed"):
                resolve_agent_changespec("a")

    def test_no_step_output(self, tmp_path: Path) -> None:
        art = tmp_path / "art"
        art.mkdir()
        (art / "done.json").write_text(json.dumps({"outcome": "completed"}))
        agent = _NamedAgent(
            name="a", artifacts_dir=str(art), is_done=True, outcome="completed"
        )
        with patch("sase.agent.names.find_named_agent", return_value=agent):
            with pytest.raises(_AgentRefError, match="no step output"):
                resolve_agent_changespec("a")

    def test_no_meta_changespec(self, tmp_path: Path) -> None:
        art = tmp_path / "art"
        art.mkdir()
        done = {"outcome": "completed", "step_output": {"other_key": "val"}}
        (art / "done.json").write_text(json.dumps(done))
        agent = _NamedAgent(
            name="a", artifacts_dir=str(art), is_done=True, outcome="completed"
        )
        with patch("sase.agent.names.find_named_agent", return_value=agent):
            with pytest.raises(_AgentRefError, match="did not create a PR/CL"):
                resolve_agent_changespec("a")

    def test_returns_changespec(self, tmp_path: Path) -> None:
        art = tmp_path / "art"
        art.mkdir()
        done = {
            "outcome": "completed",
            "step_output": {"meta_changespec": "feature/branch"},
        }
        (art / "done.json").write_text(json.dumps(done))
        agent = _NamedAgent(
            name="a", artifacts_dir=str(art), is_done=True, outcome="completed"
        )
        with patch("sase.agent.names.find_named_agent", return_value=agent):
            assert resolve_agent_changespec("a") == "feature/branch"

    def test_legacy_meta_new_cl(self, tmp_path: Path) -> None:
        art = tmp_path / "art"
        art.mkdir()
        done = {
            "outcome": "completed",
            "step_output": {"meta_new_cl": "my-branch (http://example.com)"},
        }
        (art / "done.json").write_text(json.dumps(done))
        agent = _NamedAgent(
            name="a", artifacts_dir=str(art), is_done=True, outcome="completed"
        )
        with patch("sase.agent.names.find_named_agent", return_value=agent):
            assert resolve_agent_changespec("a") == "my-branch"

    def test_done_json_unreadable(self, tmp_path: Path) -> None:
        art = tmp_path / "art"
        art.mkdir()
        (art / "done.json").write_text("not json")
        agent = _NamedAgent(
            name="a", artifacts_dir=str(art), is_done=True, outcome="completed"
        )
        with patch("sase.agent.names.find_named_agent", return_value=agent):
            with pytest.raises(_AgentRefError, match="Cannot read done marker"):
                resolve_agent_changespec("a")


# ---------------------------------------------------------------------------
# resolve_agent_refs_in_prompt() tests
# ---------------------------------------------------------------------------


class TestResolveAgentRefsInPrompt:
    def test_no_vcs_tag(self) -> None:
        prompt = "Fix the bug"
        result, tag = resolve_agent_refs_in_prompt(prompt)
        assert result == prompt
        assert tag is None

    def test_vcs_tag_without_at_name(self) -> None:
        prompt = "#gh:sase Fix tests"
        result, tag = resolve_agent_refs_in_prompt(prompt)
        assert result == prompt
        assert tag is not None

    def test_gh_colon_at_name(self) -> None:
        with patch(
            "sase.agent.names.resolve_agent_changespec", return_value="feature/branch"
        ):
            result, tag = resolve_agent_refs_in_prompt("#gh:@a Fix tests")
        assert "feature/branch" in result
        assert "@a" not in result
        assert tag is not None

    def test_gh_underscore_at_name(self) -> None:
        with patch(
            "sase.agent.names.resolve_agent_changespec", return_value="feature/branch"
        ):
            result, _tag = resolve_agent_refs_in_prompt("#gh_@a Fix tests")
        assert "feature/branch" in result
        assert "@a" not in result

    def test_gh_hitl_bang_at_name(self) -> None:
        with patch(
            "sase.agent.names.resolve_agent_changespec", return_value="feature/branch"
        ):
            result, _tag = resolve_agent_refs_in_prompt("#gh!!:@a Fix tests")
        assert "feature/branch" in result
        assert "#gh!!" in result
        assert "@a" not in result

    def test_gh_hitl_question_at_name(self) -> None:
        with patch(
            "sase.agent.names.resolve_agent_changespec", return_value="feature/branch"
        ):
            result, _tag = resolve_agent_refs_in_prompt("#gh??:@a Fix tests")
        assert "feature/branch" in result
        assert "#gh??" in result
        assert "@a" not in result

    def test_gh_paren_at_name(self) -> None:
        with patch(
            "sase.agent.names.resolve_agent_changespec", return_value="feature/branch"
        ):
            result, _tag = resolve_agent_refs_in_prompt("#gh(@a) Fix tests")
        assert "feature/branch" in result
        assert "@a" not in result

    def test_with_wait_directive(self) -> None:
        with patch(
            "sase.agent.names.resolve_agent_changespec", return_value="feature/branch"
        ):
            result, _tag = resolve_agent_refs_in_prompt("%wait:a #gh:@a Fix tests")
        assert "feature/branch" in result
        assert "Fix tests" in result
        assert "@a" not in result

    def test_at_mention_in_body_unchanged(self) -> None:
        with patch(
            "sase.agent.names.resolve_agent_changespec", return_value="feature/branch"
        ):
            result, _tag = resolve_agent_refs_in_prompt("#gh:@a Fix tests cc @someone")
        assert "@someone" in result
        assert "feature/branch" in result
