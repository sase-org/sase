"""Tests for shared plan utilities (_plan_utils.py)."""

from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.llm_provider._plan_utils import (
    PlanApprovalResult,
    add_create_time_frontmatter,
    handle_plan_approval,
    save_plan_to_sase,
)
from sase.main.plan_approve_handler import (
    get_auto_plan_approval_action,
    is_auto_approve_active,
)

from tests.conftest import redirect_sase_home


def test_save_plan_to_sase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that save_plan_to_sase copies to ~/.sase/plans/ with dedup counter."""
    src_file = tmp_path / "source_plan.md"
    src_file.write_text("plan content")

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    dest1 = save_plan_to_sase(str(src_file))

    assert dest1.exists()
    assert dest1.read_text() == "plan content"
    # Plans are sharded by YYYYMM; parent is <sase_home>/plans/<shard>.
    assert dest1.parent.parent == sase_home / "plans"
    assert dest1.name == "source_plan.md"

    # Second copy should get dedup counter
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
        "sase.main.plan_approve_handler.get_auto_plan_approval_action",
        return_value="approve",
    ):
        result = handle_plan_approval("/path/to/plan.md", "session-123")
    assert result == PlanApprovalResult(action="approve", plan_file="/path/to/plan.md")


def test_handle_plan_approval_auto_epic_skips_notification() -> None:
    """Plan-specific auto-epic enters the existing epic action path."""
    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value="epic",
        ),
        patch("sase.notifications.senders.notify_plan_approval") as notify,
    ):
        result = handle_plan_approval("/path/to/plan.md", "session-123")

    assert result == PlanApprovalResult(action="epic", plan_file="/path/to/plan.md")
    notify.assert_not_called()


def test_auto_plan_action_reads_epic_from_agent_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        '{"auto_approve_plan_action": "epic", "approve": true}'
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    assert get_auto_plan_approval_action() == "epic"
    assert is_auto_approve_active() is True


def test_handle_plan_approval_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that handle_plan_approval accepts 'commit' action from response file."""
    import json

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    session_id = "test-commit-session"
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    captured_response_dir: dict[str, Path] = {}

    def _fake_notify(**kwargs: object) -> None:
        # handle_plan_approval hands us the exact response_dir it created.
        response_dir = Path(str(kwargs["response_dir"]))
        captured_response_dir["dir"] = response_dir
        (response_dir / "plan_response.json").write_text(
            json.dumps({"action": "commit"})
        )

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value=None,
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
    ):
        result = handle_plan_approval(plan_file, session_id)

    assert result == PlanApprovalResult(
        action="approve", plan_file=plan_file, run_coder=False
    )
    # Session directory lives under a YYYYMM shard of plan_approval/.
    assert captured_response_dir["dir"].parent.parent == sase_home / "plan_approval"
    assert captured_response_dir["dir"].name == session_id


def test_handle_plan_approval_none_plan_file() -> None:
    """Test that handle_plan_approval returns None when plan_file is None."""
    with patch(
        "sase.main.plan_approve_handler.get_auto_plan_approval_action",
        return_value=None,
    ):
        result = handle_plan_approval(None, "session-123")
    assert result is None


def test_handle_plan_approval_approve_with_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test isinstance validation and whitespace trimming of approve-with-options fields."""
    import json

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    session_id = "test-options-session"
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    def _fake_notify(**kwargs: object) -> None:
        response_dir = Path(str(kwargs["response_dir"]))
        (response_dir / "plan_response.json").write_text(
            json.dumps(
                {
                    "action": "approve",
                    "commit_plan": False,
                    "run_coder": True,
                    "coder_prompt": "  #review+  ",
                }
            )
        )

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value=None,
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
    ):
        result = handle_plan_approval(plan_file, session_id)

    assert result is not None
    assert result.action == "approve"
    assert result.commit_plan is False
    assert result.run_coder is True
    assert result.coder_prompt == "#review+"  # whitespace trimmed


def test_handle_plan_approval_accepts_legend_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legend approval is returned as a first-class plan action."""
    import json

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    session_id = "test-legend-session"
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    def _fake_notify(**kwargs: object) -> None:
        response_dir = Path(str(kwargs["response_dir"]))
        (response_dir / "plan_response.json").write_text(
            json.dumps({"action": "legend"})
        )

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value=None,
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
    ):
        result = handle_plan_approval(plan_file, session_id)

    assert result == PlanApprovalResult(action="legend", plan_file=plan_file)
