"""Tests for shared plan utilities (_plan_utils.py)."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.llm_provider._plan_utils import (
    append_plan_feedback_log,
    handle_plan_approval,
    read_plan_feedback,
    save_plan_to_sase,
    save_response_as_plan,
    write_plan_path_artifact,
)


def test_save_response_as_plan(tmp_path: Path) -> None:
    """Test that save_response_as_plan creates a plan file with correct content."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = save_response_as_plan("my plan text", "testprovider")

    plan_path = Path(result)
    assert plan_path.exists()
    assert plan_path.read_text() == "my plan text"
    assert plan_path.parent == tmp_path / ".testprovider" / "plans"


def test_save_plan_to_sase(tmp_path: Path) -> None:
    """Test that save_plan_to_sase copies to ~/.sase/plans/ with dedup counter."""
    src_file = tmp_path / "source_plan.md"
    src_file.write_text("plan content")

    with patch.object(Path, "home", return_value=tmp_path):
        dest1 = save_plan_to_sase(str(src_file))

    assert dest1.exists()
    assert dest1.read_text() == "plan content"
    assert dest1.parent == tmp_path / ".sase" / "plans"
    assert dest1.name == "source_plan.md"

    # Second copy should get dedup counter
    with patch.object(Path, "home", return_value=tmp_path):
        dest2 = save_plan_to_sase(str(src_file))

    assert dest2.exists()
    assert dest2.name == "source_plan_1.md"


def test_write_plan_path_artifact_with_env(tmp_path: Path) -> None:
    """Test that write_plan_path_artifact writes plan_path.json when env is set."""
    plan_path = Path("/some/plan.md")

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        write_plan_path_artifact(plan_path)

    artifact_file = tmp_path / "plan_path.json"
    assert artifact_file.exists()
    data = json.loads(artifact_file.read_text())
    assert data["plan_path"] == "/some/plan.md"


def test_write_plan_path_artifact_without_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that write_plan_path_artifact is a no-op without SASE_ARTIFACTS_DIR."""
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    write_plan_path_artifact(Path(tmp_path / "plan.md"))
    assert not (tmp_path / "plan_path.json").exists()


def test_read_plan_feedback_reject_with_feedback(tmp_path: Path) -> None:
    """Test that read_plan_feedback returns feedback string on rejection."""
    response = {"action": "reject", "feedback": "needs more detail"}
    (tmp_path / "plan_response.json").write_text(json.dumps(response))

    result = read_plan_feedback(tmp_path)
    assert result == "needs more detail"


def test_read_plan_feedback_approve(tmp_path: Path) -> None:
    """Test that read_plan_feedback returns None for approve action."""
    response = {"action": "approve"}
    (tmp_path / "plan_response.json").write_text(json.dumps(response))

    result = read_plan_feedback(tmp_path)
    assert result is None


def test_read_plan_feedback_missing_file(tmp_path: Path) -> None:
    """Test that read_plan_feedback returns None when file doesn't exist."""
    result = read_plan_feedback(tmp_path)
    assert result is None


def test_append_plan_feedback_log(tmp_path: Path) -> None:
    """Test that append_plan_feedback_log appends a JSONL record."""
    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        append_plan_feedback_log("fix the design", 1)

    log_path = tmp_path / "plan_feedback.jsonl"
    assert log_path.exists()
    record = json.loads(log_path.read_text().strip())
    assert record["round"] == 1
    assert record["feedback"] == "fix the design"
    assert "timestamp" in record


def test_handle_plan_approval_auto_approve() -> None:
    """Test that handle_plan_approval returns plan_file when auto-approve is active."""
    with patch(
        "sase.main.plan_approve_handler.is_auto_approve_active", return_value=True
    ):
        result = handle_plan_approval("/path/to/plan.md", "session-123")
    assert result == "/path/to/plan.md"


def test_handle_plan_approval_none_plan_file() -> None:
    """Test that handle_plan_approval returns None when plan_file is None."""
    with patch(
        "sase.main.plan_approve_handler.is_auto_approve_active", return_value=False
    ):
        result = handle_plan_approval(None, "session-123")
    assert result is None
