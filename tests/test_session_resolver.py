"""Tests for sase.ace.tui.thinking.session_resolver."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.thinking.session_resolver import (
    _expand_linked_sessions,
    _find_jsonl_files_since,
    _find_most_recent_jsonl,
    _first_event_timestamp,
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


# --- _get_workspace_cwd ---


@patch("sase.running_field.get_workspace_directory")
def test_get_workspace_cwd_runtime_error(mock_gwd: object) -> None:
    mock_gwd.side_effect = RuntimeError("workspace not found")  # type: ignore[union-attr]
    agent = _make_agent()
    assert _get_workspace_cwd(agent) is None


# --- _find_most_recent_jsonl ---


def test_find_most_recent_jsonl_empty_dir(tmp_path: Path) -> None:
    assert _find_most_recent_jsonl(tmp_path) is None


def test_find_most_recent_jsonl_single(tmp_path: Path) -> None:
    only = tmp_path / "session.jsonl"
    only.write_text("{}\n")
    assert _find_most_recent_jsonl(tmp_path) == only


# --- resolve_agent_session end-to-end ---


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


# --- _first_event_timestamp ---


def test_first_event_timestamp_skips_empty_lines(tmp_path: Path) -> None:
    f = tmp_path / "session.jsonl"
    f.write_text(
        "\n\n"
        + json.dumps({"timestamp": "2026-01-15T12:30:00Z", "type": "user"})
        + "\n"
    )
    ts = _first_event_timestamp(f)
    assert ts is not None
    expected = datetime(2026, 1, 15, 12, 30, 0, tzinfo=UTC).timestamp()
    assert abs(ts - expected) < 0.01


def test_first_event_timestamp_returns_none_on_missing_timestamp(
    tmp_path: Path,
) -> None:
    f = tmp_path / "no_ts.jsonl"
    f.write_text(json.dumps({"type": "assistant"}) + "\n")
    assert _first_event_timestamp(f) is None


# --- _find_jsonl_files_since ---


def test_find_jsonl_files_since_single_file(tmp_path: Path) -> None:
    """Single candidate is returned directly, no session matching needed."""
    f = tmp_path / "session.jsonl"
    f.write_text(json.dumps({"timestamp": "2026-01-15T10:00:00Z"}) + "\n")
    since = datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)
    result = _find_jsonl_files_since(tmp_path, since)
    assert result == [f]


def test_find_jsonl_files_since_falls_back_on_unreadable(tmp_path: Path) -> None:
    """When timestamps can't be read, returns all candidates."""
    since = datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)

    a = tmp_path / "a.jsonl"
    a.write_text("not json\n")
    b = tmp_path / "b.jsonl"
    b.write_text("also not json\n")

    result = _find_jsonl_files_since(tmp_path, since)
    assert len(result) == 2
    assert set(result) == {a, b}


# --- _expand_linked_sessions ---


def test_expand_linked_sessions_missing_impl_jsonl(tmp_path: Path) -> None:
    """Sidecar points to a non-existent JSONL — gracefully ignored."""
    plan = tmp_path / "plan-uuid.jsonl"
    plan.write_text("{}\n")

    sidecar = tmp_path / "plan-uuid.impl_session"
    sidecar.write_text("missing-uuid")

    result = _expand_linked_sessions(tmp_path, [plan])
    assert result == [plan]
