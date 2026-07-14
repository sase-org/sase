"""Tests for shared plan utilities (_plan_utils.py)."""

from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.llm_provider._plan_utils import (
    _POLL_INTERVAL,
    PlanApprovalResult,
    add_create_time_frontmatter,
    handle_plan_approval,
    move_plan_to_sase,
)
from sase.main.plan_approve_handler import (
    get_auto_plan_approval_action,
    is_auto_approve_active,
)
from sase.plan_approval_actions import PlanApprovalValidationError

from tests.conftest import redirect_sase_home
from tests.plan_validation_helpers import VALID_EPIC_PLAN


def _only_plan_approval_response_dir(sase_home: Path, session_id: str) -> Path:
    matches = list((sase_home / "plan_approval").glob(f"*/{session_id}"))
    assert len(matches) == 1
    return matches[0]


def test_move_plan_to_sase_moves_and_strips_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sase_plan_*.md input is moved into the archive, renamed, and consumed."""
    src_file = tmp_path / "sase_plan_feature.md"
    src_file.write_text("plan content")

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    dest = move_plan_to_sase(str(src_file))

    assert dest.exists()
    assert dest.read_text() == "plan content"
    # Plans are sharded by YYYYMM; parent is <sase_home>/plans/<shard>.
    assert dest.parent.parent == sase_home / "plans"
    # The "sase_plan_" prefix is stripped from the archived name.
    assert dest.name == "feature.md"
    # The scratch source file was consumed by the move.
    assert not src_file.exists()


def test_move_plan_to_sase_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dedup counter still applies when the archive holds the target basename."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    first = tmp_path / "feature.md"
    first.write_text("first")
    dest1 = move_plan_to_sase(str(first))
    assert dest1.name == "feature.md"
    assert not first.exists()

    # A fresh scratch file with the same basename gets a dedup counter.
    second = tmp_path / "feature.md"
    second.write_text("second")
    dest2 = move_plan_to_sase(str(second))

    assert dest2.name == "feature_1.md"
    assert dest2.read_text() == "second"
    assert not second.exists()


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
    assert result == PlanApprovalResult(
        action="approve", plan_file="/path/to/plan.md", commit_plan=False
    )


def test_handle_plan_approval_auto_epic_skips_notification(tmp_path: Path) -> None:
    """Plan-specific auto-epic enters the existing epic action path."""
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value="epic",
        ),
        patch("sase.notifications.senders.notify_plan_approval") as notify,
    ):
        result = handle_plan_approval(str(plan), "session-123")

    assert result == PlanApprovalResult(action="epic", plan_file=str(plan))
    notify.assert_not_called()


def test_handle_plan_approval_auto_tale_skips_notification(tmp_path: Path) -> None:
    """Plan-specific auto-tale enters the auto-approval action path."""
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value="tale",
        ),
        patch("sase.notifications.senders.notify_plan_approval") as notify,
    ):
        result = handle_plan_approval(str(plan), "session-123")

    assert result == PlanApprovalResult(action="tale", plan_file=str(plan))
    notify.assert_not_called()


def test_invalid_auto_epic_does_not_consume_pending_action(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Invalid epic\n", encoding="utf-8")

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value="epic",
        ),
        patch(
            "sase.llm_provider._plan_utils._mark_auto_approved_plan_handled"
        ) as mark_handled,
        pytest.raises(PlanApprovalValidationError),
    ):
        handle_plan_approval(str(plan), "session-123", agent_name="planner")

    mark_handled.assert_not_called()


@pytest.mark.parametrize("auto_action", ["approve", "tale", "epic"])
def test_handle_plan_approval_rechecks_auto_approve_while_waiting(
    auto_action: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending plan unblocks when auto-approve is enabled after notification."""
    from sase.notifications import load_notifications, pending_actions

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text(VALID_EPIC_PLAN)
    session_id = f"waiting-auto-{auto_action}"
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "root-1")

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            side_effect=[None, None, auto_action],
        ) as get_auto_action,
        patch("sase.llm_provider._plan_utils.time.sleep") as sleep,
        patch("sase.main.plan_approve_handler.send_desktop_notification"),
        patch("sase.main.plan_approve_handler.ring_tmux_bell"),
        patch("sase.main.plan_approve_handler.get_tmux_prefix", return_value=""),
    ):
        result = handle_plan_approval(
            plan_file,
            session_id,
            agent_name="planner.agent",
        )

    assert result == PlanApprovalResult(
        action=auto_action,
        plan_file=plan_file,
        commit_plan=auto_action != "approve",
    )
    assert get_auto_action.call_count == 3
    sleep.assert_any_call(_POLL_INTERVAL)

    response_dir = _only_plan_approval_response_dir(sase_home, session_id)
    assert not (response_dir / "plan_response.json").exists()
    assert not (response_dir / "plan_request.json").exists()

    store = pending_actions.read_pending_action_store()
    [entry] = store["actions"].values()
    assert entry["state"] == "already_handled"
    assert entry["handled_source"] == "auto_approve"
    assert entry["handled_action"] == auto_action

    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].dismissed is True
    assert load_notifications() == []


def test_handle_plan_approval_killed_check_wins_over_waiting_auto_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kill during the wait returns None without consuming a later auto action."""
    from sase.notifications import load_notifications, pending_actions

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    session_id = "waiting-auto-killed"
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "root-1")

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            side_effect=[None, "approve"],
        ) as get_auto_action,
        patch("sase.llm_provider._plan_utils.time.sleep") as sleep,
        patch("sase.main.plan_approve_handler.send_desktop_notification"),
        patch("sase.main.plan_approve_handler.ring_tmux_bell"),
        patch("sase.main.plan_approve_handler.get_tmux_prefix", return_value=""),
    ):
        result = handle_plan_approval(
            plan_file,
            session_id,
            killed_check=lambda: True,
            agent_name="planner.agent",
        )

    assert result is None
    assert get_auto_action.call_count == 1
    sleep.assert_not_called()

    response_dir = _only_plan_approval_response_dir(sase_home, session_id)
    assert (response_dir / "plan_request.json").exists()
    assert not (response_dir / "plan_response.json").exists()

    store = pending_actions.read_pending_action_store()
    [entry] = store["actions"].values()
    assert entry["state"] == "available"

    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].dismissed is False


def test_handle_plan_approval_auto_marks_stale_telegram_action_handled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-approval dismisses a stale Telegram plan keyboard via shared state.

    A prior run left a registered PlanApproval action with a Telegram transport
    record. When the same plan/agent is auto-approved (no notification, no
    response file), the shared action must flip to ``already_handled`` so the
    Telegram inbound chop removes the inline keyboard.
    """
    from sase.notifications import pending_actions
    from sase.notifications.models import Notification

    store_path = tmp_path / "pending_actions" / "actions.json"
    plan_file = str(tmp_path / "plan.md")
    monkeypatch.setattr(pending_actions, "PENDING_ACTIONS_PATH", store_path)
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "root-1")

    stale = Notification(
        id="abcdef01-full",
        timestamp="2026-05-06T12:00:00+00:00",
        sender="plan",
        notes=["Plan ready"],
        files=[plan_file],
        action="PlanApproval",
        action_data={"response_dir": "x", "agent_root_timestamp": "root-1"},
    )
    pending_actions.register_notification(stale, now=10.0)
    pending_actions.merge_transport_record(
        stale.id, "telegram", {"chat_id": "chat", "message_id": 7}, now=10.0
    )

    with patch(
        "sase.main.plan_approve_handler.get_auto_plan_approval_action",
        return_value="approve",
    ):
        result = handle_plan_approval(plan_file, "session-xyz", agent_name="plan.agent")

    assert result == PlanApprovalResult(
        action="approve", plan_file=plan_file, commit_plan=False
    )
    store = pending_actions.read_pending_action_store()
    assert store["actions"]["abcdef01"]["state"] == "already_handled"
    assert store["actions"]["abcdef01"]["handled_action"] == "approve"


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


def test_auto_plan_action_reads_tale_from_agent_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text('{"auto_approve_plan_action": "tale"}')
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    assert get_auto_plan_approval_action() == "tale"


def test_normalize_plan_action_recognizes_tale() -> None:
    """_normalize_plan_action accepts tale alongside approve and epic."""
    from sase.main.plan_approve_handler import _normalize_plan_action

    assert _normalize_plan_action("tale") == "tale"
    assert _normalize_plan_action("  TALE  ") == "tale"
    assert _normalize_plan_action("epic") == "epic"
    assert _normalize_plan_action("approve") == "approve"
    assert _normalize_plan_action("bogus") is None
    assert _normalize_plan_action(None) is None


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


def test_handle_plan_approval_passes_agent_root_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan notifications include both phase and root routing timestamps."""
    import json

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260512094333")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20260512090000")
    captured_kwargs: dict[str, object] = {}

    def _fake_notify(**kwargs: object) -> None:
        captured_kwargs.update(kwargs)
        response_dir = Path(str(kwargs["response_dir"]))
        (response_dir / "plan_response.json").write_text(
            json.dumps({"action": "approve"})
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
        result = handle_plan_approval(plan_file, "session")

    assert result == PlanApprovalResult(action="approve", plan_file=plan_file)
    assert captured_kwargs["agent_timestamp"] == "20260512094333"
    assert captured_kwargs["agent_root_timestamp"] == "20260512090000"


def test_handle_plan_approval_forwards_agent_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan notifications include the planner elapsed runtime when provided."""
    import json

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    captured_kwargs: dict[str, object] = {}

    def _fake_notify(**kwargs: object) -> None:
        captured_kwargs.update(kwargs)
        response_dir = Path(str(kwargs["response_dir"]))
        (response_dir / "plan_response.json").write_text(
            json.dumps({"action": "approve"})
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
        result = handle_plan_approval(plan_file, "session", agent_runtime="4m32s")

    assert result == PlanApprovalResult(action="approve", plan_file=plan_file)
    assert captured_kwargs["agent_runtime"] == "4m32s"


def test_handle_plan_approval_forwards_agent_vcs_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan notifications include the planner's VCS workflow tag when provided."""
    import json

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    captured_kwargs: dict[str, object] = {}

    def _fake_notify(**kwargs: object) -> None:
        captured_kwargs.update(kwargs)
        response_dir = Path(str(kwargs["response_dir"]))
        (response_dir / "plan_response.json").write_text(
            json.dumps({"action": "approve"})
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
        result = handle_plan_approval(
            plan_file,
            "session",
            agent_vcs_tag="#gh:sase ",
        )

    assert result == PlanApprovalResult(action="approve", plan_file=plan_file)
    assert captured_kwargs["agent_vcs_tag"] == "#gh:sase "


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
    """Test isinstance validation and whitespace trimming of custom approval fields."""
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


def test_handle_plan_approval_remote_response_uses_request_member_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote responders can omit selected_member_ids and still apply defaults."""
    import json

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    member_payload = {
        "member_options": [
            {
                "id": "improve_plan",
                "label": "improve plan",
                "placement_after": "plan",
                "suffix": "--improve_plan",
                "auto": "skip",
                "default": True,
                "definition_default": False,
                "source_path": "/x/improve.yml",
                "config_id": "improve_plan",
                "config_hash": "abc",
            },
            {
                "id": "tester",
                "label": "tester",
                "placement_after": "code",
                "suffix": "--tester",
                "auto": "run",
                "default": False,
                "definition_default": False,
                "source_path": "/x/tester.yml",
                "config_id": "tester",
                "config_hash": "def",
            },
        ],
        "default_member_ids": ["improve_plan"],
    }

    def _fake_notify(**kwargs: object) -> None:
        response_dir = Path(str(kwargs["response_dir"]))
        request_data = json.loads((response_dir / "plan_request.json").read_text())
        assert request_data["default_member_ids"] == ["improve_plan"]
        assert kwargs["default_member_ids"] == ("improve_plan",)
        (response_dir / "plan_response.json").write_text(
            json.dumps({"action": "approve"})
        )

    with (
        patch(
            "sase.main.plan_approve_handler.get_auto_plan_approval_action",
            return_value=None,
        ),
        patch(
            "sase.llm_provider._plan_utils.plan_approval_member_request_payload",
            return_value=member_payload,
        ),
        patch(
            "sase.notifications.senders.notify_plan_approval",
            side_effect=_fake_notify,
        ),
        patch("sase.main.plan_approve_handler.send_desktop_notification"),
        patch("sase.main.plan_approve_handler.ring_tmux_bell"),
        patch("sase.main.plan_approve_handler.get_tmux_prefix", return_value=""),
    ):
        result = handle_plan_approval(plan_file, "remote-defaults-session")

    assert result is not None
    assert result.selected_member_ids == ("improve_plan",)
