"""Tests for plan approval responses and notification metadata."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.llm_provider._plan_utils import PlanApprovalResult, handle_plan_approval

from tests.conftest import redirect_sase_home
from tests.plan_validation_helpers import VALID_EPIC_PLAN


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


def test_handle_plan_approval_reads_host_epic_launch_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_file = str(tmp_path / "epic.md")
    Path(plan_file).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    def _fake_notify(**kwargs: object) -> None:
        response_dir = Path(str(kwargs["response_dir"]))
        (response_dir / "plan_response.json").write_text(
            json.dumps(
                {"action": "epic", "epic_launch_owner": "host"},
            ),
            encoding="utf-8",
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
        patch("sase.main.plan_approve_handler.get_tmux_prefix", return_value=""),
    ):
        result = handle_plan_approval(plan_file, "host-owned-epic")

    assert result is not None
    assert result.action == "epic"
    assert result.epic_launch_owner == "host"


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
