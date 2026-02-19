"""Tests for sase.ace.tui.thinking.session_resolver."""

import time
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.thinking.session_resolver import (
    _cwd_to_claude_project_dir,
    _find_most_recent_jsonl,
    _get_workspace_cwd,
    resolve_agent_session,
)


def _make_agent(
    project_file: str = "/home/user/.sase/projects/myproject/myproject.gp",
    workspace_num: int | None = 1,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="myproject",
        project_file=project_file,
        status="RUNNING",
        start_time=None,
        workspace_num=workspace_num,
    )


# --- _cwd_to_claude_project_dir ---


def test_cwd_to_claude_project_dir_standard() -> None:
    result = _cwd_to_claude_project_dir("/home/user/projects/myproject")
    assert (
        result == Path.home() / ".claude" / "projects" / "-home-user-projects-myproject"
    )


def test_cwd_to_claude_project_dir_double_underscore() -> None:
    """workspace__100 paths get double hyphens."""
    result = _cwd_to_claude_project_dir("/home/user/workspace__100")
    expected_hash = "-home-user-workspace--100"
    assert result == Path.home() / ".claude" / "projects" / expected_hash


# --- _get_workspace_cwd ---


@patch("sase.running_field.get_workspace_directory")
def test_get_workspace_cwd_with_workspace_num(mock_gwd: object) -> None:
    mock_gwd.return_value = "/home/user/projects/myproject"  # type: ignore[union-attr]
    agent = _make_agent(workspace_num=3)
    result = _get_workspace_cwd(agent)
    mock_gwd.assert_called_once_with("myproject", 3)  # type: ignore[union-attr]
    assert result == "/home/user/projects/myproject"


@patch("sase.running_field.get_workspace_directory")
def test_get_workspace_cwd_defaults_to_1(mock_gwd: object) -> None:
    mock_gwd.return_value = "/home/user/projects/myproject"  # type: ignore[union-attr]
    agent = _make_agent(workspace_num=None)
    result = _get_workspace_cwd(agent)
    mock_gwd.assert_called_once_with("myproject", 1)  # type: ignore[union-attr]
    assert result == "/home/user/projects/myproject"


@patch("sase.running_field.get_workspace_directory")
def test_get_workspace_cwd_runtime_error(mock_gwd: object) -> None:
    mock_gwd.side_effect = RuntimeError("workspace not found")  # type: ignore[union-attr]
    agent = _make_agent()
    assert _get_workspace_cwd(agent) is None


@patch("sase.running_field.get_workspace_directory")
def test_get_workspace_cwd_trailing_slash(mock_gwd: object) -> None:
    mock_gwd.return_value = "/home/user/projects/myproject/"  # type: ignore[union-attr]
    agent = _make_agent()
    result = _get_workspace_cwd(agent)
    assert result == "/home/user/projects/myproject"


# --- _find_most_recent_jsonl ---


def test_find_most_recent_jsonl_multiple(tmp_path: Path) -> None:
    old = tmp_path / "old.jsonl"
    old.write_text("{}\n")
    time.sleep(0.05)
    new = tmp_path / "new.jsonl"
    new.write_text("{}\n")
    assert _find_most_recent_jsonl(tmp_path) == new


def test_find_most_recent_jsonl_empty_dir(tmp_path: Path) -> None:
    assert _find_most_recent_jsonl(tmp_path) is None


def test_find_most_recent_jsonl_single(tmp_path: Path) -> None:
    only = tmp_path / "session.jsonl"
    only.write_text("{}\n")
    assert _find_most_recent_jsonl(tmp_path) == only


# --- resolve_agent_session end-to-end ---


@patch("sase.ace.tui.thinking.session_resolver._find_most_recent_jsonl")
@patch("sase.ace.tui.thinking.session_resolver._cwd_to_claude_project_dir")
@patch("sase.ace.tui.thinking.session_resolver._get_workspace_cwd")
def test_resolve_success(
    mock_cwd: object, mock_dir: object, mock_jsonl: object, tmp_path: Path
) -> None:
    mock_cwd.return_value = "/home/user/projects/myproject"  # type: ignore[union-attr]
    claude_dir = tmp_path / "claude_projects"
    claude_dir.mkdir()
    mock_dir.return_value = claude_dir  # type: ignore[union-attr]
    expected = tmp_path / "session.jsonl"
    mock_jsonl.return_value = expected  # type: ignore[union-attr]

    agent = _make_agent()
    result = resolve_agent_session(agent)
    assert result == expected


@patch("sase.ace.tui.thinking.session_resolver._get_workspace_cwd")
def test_resolve_workspace_failure(mock_cwd: object) -> None:
    mock_cwd.return_value = None  # type: ignore[union-attr]
    assert resolve_agent_session(_make_agent()) is None


@patch("sase.ace.tui.thinking.session_resolver._cwd_to_claude_project_dir")
@patch("sase.ace.tui.thinking.session_resolver._get_workspace_cwd")
def test_resolve_missing_claude_dir(mock_cwd: object, mock_dir: object) -> None:
    mock_cwd.return_value = "/home/user/projects/myproject"  # type: ignore[union-attr]
    mock_dir.return_value = Path("/nonexistent/path")  # type: ignore[union-attr]
    assert resolve_agent_session(_make_agent()) is None


@patch("sase.ace.tui.thinking.session_resolver._find_most_recent_jsonl")
@patch("sase.ace.tui.thinking.session_resolver._cwd_to_claude_project_dir")
@patch("sase.ace.tui.thinking.session_resolver._get_workspace_cwd")
def test_resolve_no_jsonl(
    mock_cwd: object, mock_dir: object, mock_jsonl: object, tmp_path: Path
) -> None:
    mock_cwd.return_value = "/home/user/projects/myproject"  # type: ignore[union-attr]
    claude_dir = tmp_path / "claude_projects"
    claude_dir.mkdir()
    mock_dir.return_value = claude_dir  # type: ignore[union-attr]
    mock_jsonl.return_value = None  # type: ignore[union-attr]
    assert resolve_agent_session(_make_agent()) is None
