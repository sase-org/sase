"""Tests for shared plan utilities (_plan_utils.py)."""

from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._plan_utils import (
    PlanApprovalResult,
    add_create_time_frontmatter,
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


def test_add_create_time_frontmatter_no_existing() -> None:
    """Prepends frontmatter when the content has none."""
    dt = datetime(2026, 3, 20, 14, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    result = add_create_time_frontmatter("# My Plan\nDetails", dt)
    assert (
        result
        == "---\ncreate_time: 2026-03-20 14:30:00\nstatus: wip\n---\n# My Plan\nDetails"
    )


def test_add_create_time_frontmatter_existing_frontmatter() -> None:
    """Inserts create_time into existing frontmatter."""
    content = "---\ntitle: foo\n---\n# Plan"
    dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    result = add_create_time_frontmatter(content, dt)
    assert (
        result
        == "---\ntitle: foo\ncreate_time: 2026-01-01 00:00:00\nstatus: wip\n---\n# Plan"
    )


def test_add_create_time_frontmatter_overwrites_existing_field() -> None:
    """Overwrites an existing create_time field and adds status if missing."""
    content = "---\ncreate_time: 2025-01-01\n---\n# Plan"
    dt = datetime(2026, 3, 20, 14, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    result = add_create_time_frontmatter(content, dt)
    assert result == "---\ncreate_time: 2026-03-20 14:30:00\nstatus: wip\n---\n# Plan"


def test_add_create_time_frontmatter_no_duplicate_status() -> None:
    """Does not duplicate status when it already exists in frontmatter."""
    content = "---\nstatus: wip\n---\n# Plan"
    dt = datetime(2026, 3, 20, 14, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    result = add_create_time_frontmatter(content, dt)
    assert result == "---\nstatus: wip\ncreate_time: 2026-03-20 14:30:00\n---\n# Plan"
    # Exactly one status field
    assert result.count("status:") == 1


def test_handle_plan_approval_auto_approve() -> None:
    """Test that handle_plan_approval returns plan_file when auto-approve is active."""
    with patch(
        "sase.main.plan_approve_handler.is_auto_approve_active", return_value=True
    ):
        result = handle_plan_approval("/path/to/plan.md", "session-123")
    assert result == PlanApprovalResult(action="approve", plan_file="/path/to/plan.md")


def test_handle_plan_approval_commit(tmp_path: Path) -> None:
    """Test that handle_plan_approval accepts 'commit' action from response file."""
    import json

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    session_id = "test-commit-session"
    response_dir = tmp_path / ".sase" / "plan_approval" / session_id

    def _fake_notify(**_kwargs: object) -> None:
        # Write the response file after handle_plan_approval has cleared
        # any stale response and is about to enter the poll loop.
        (response_dir / "plan_response.json").write_text(
            json.dumps({"action": "commit"})
        )

    with (
        patch(
            "sase.main.plan_approve_handler.is_auto_approve_active",
            return_value=False,
        ),
        patch(
            "sase.notifications.senders.notify_plan_approval",
            side_effect=_fake_notify,
        ),
        patch("sase.main.plan_approve_handler.send_desktop_notification"),
        patch("sase.main.plan_approve_handler.ring_tmux_bell"),
        patch(
            "sase.main.plan_approve_handler.get_tmux_prefix",
            return_value="",
        ),
        patch.object(Path, "home", return_value=tmp_path),
    ):
        result = handle_plan_approval(plan_file, session_id)
    assert result == PlanApprovalResult(action="commit", plan_file=plan_file)


def test_handle_plan_approval_none_plan_file() -> None:
    """Test that handle_plan_approval returns None when plan_file is None."""
    with patch(
        "sase.main.plan_approve_handler.is_auto_approve_active", return_value=False
    ):
        result = handle_plan_approval(None, "session-123")
    assert result is None
