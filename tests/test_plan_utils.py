"""Tests for shared plan utilities (_plan_utils.py)."""

from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._plan_utils import (
    handle_plan_approval,
    save_plan_to_sase,
)


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
