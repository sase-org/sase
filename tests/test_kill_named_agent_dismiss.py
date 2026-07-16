"""Tests for named-agent kill persistence and notification cleanup.

When the user kills an agent via the Telegram "Kill" button, gchat, or
``sase agent kill``, the agent ought to disappear from ``sase ace``'s
agents tab the same way an ``x`` press in the TUI does. The kill path
must therefore add the agent's identity to ``~/.sase/dismissed_agents.json``
and dismiss matching notifications after successful live or stale cleanup.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.names._common import NamedAgent
from sase.agent.running import kill_named_agent
from tests._kill_named_agent_dismiss_helpers import (
    _isolated_dismissed_index as _isolated_dismissed_index,
)
from tests._kill_named_agent_dismiss_helpers import (
    append_question as _append_question,
    notifications_by_id as _notifications_by_id,
    patch_home as _patch_home,
    setup_home_agent as _setup_home_agent,
    setup_nonhome_agent as _setup_nonhome_agent,
    successful_user_kill as _successful_user_kill,
)


def test_kill_named_root_dismisses_child_question_only(tmp_path: Path) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    response_dir = tmp_path / "question-response"
    response_dir.mkdir()
    _append_question(
        notification_id="matching-question",
        cl_name="feature_x",
        child_timestamp="20260510130001",
        root_timestamp="20260510130000",
        response_dir=response_dir,
    )
    _append_question(
        notification_id="unrelated-question",
        cl_name="feature_x",
        child_timestamp="20260510130002",
        root_timestamp="20260510139999",
    )
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=_successful_user_kill(),
        ),
        patch("sase.running_field.release_workspace"),
    ):
        result = kill_named_agent("my_agent")

    notifications = _notifications_by_id()
    assert result.success is True
    assert notifications["matching-question"].dismissed is True
    assert notifications["unrelated-question"].dismissed is False
    assert not (response_dir / "question_response.json").exists()


def test_kill_named_agent_writes_dismissal_for_nonhome_uses_claim_cl_name(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=_successful_user_kill(),
        ),
        patch("sase.running_field.release_workspace"),
        patch("sase.agent.running.sync_dismissed_agent_artifact_index") as sync_index,
    ):
        result = kill_named_agent("my_agent")

    assert result.success is True

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    dismissed = load_dismissed_agents()
    identity = (AgentType.RUNNING, "feature_x", "20260510130000")
    assert identity in dismissed
    sync_index.assert_called_once_with(dismissed, added={identity})


def test_kill_named_agent_writes_dismissal_for_home_uses_meta_cl_name(
    tmp_path: Path,
) -> None:
    artifacts_dir = _setup_home_agent(tmp_path, with_cl_name=True)
    found = NamedAgent(
        name="home_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=_successful_user_kill(),
        ),
        patch(
            "sase.agent.running.update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        result = kill_named_agent("home_agent")

    assert result.success is True
    update_index.assert_called_once_with(artifacts_dir)

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    dismissed = load_dismissed_agents()
    assert (AgentType.RUNNING, "home_feature", "20260510120000") in dismissed


def test_kill_named_agent_falls_back_to_unknown_cl_name_for_home_without_meta(
    tmp_path: Path,
) -> None:
    artifacts_dir = _setup_home_agent(tmp_path, with_cl_name=False)
    found = NamedAgent(
        name="home_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=_successful_user_kill(),
        ),
    ):
        result = kill_named_agent("home_agent")

    assert result.success is True

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    dismissed = load_dismissed_agents()
    assert (AgentType.RUNNING, "unknown", "20260510120000") in dismissed


def test_kill_named_agent_writes_dismissal_when_process_already_stopped(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=_successful_user_kill(status="already_stopped"),
        ),
        patch("sase.running_field.release_workspace"),
    ):
        result = kill_named_agent("my_agent")

    assert result.success is True
    assert result.status == "already_stopped"

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    assert (AgentType.RUNNING, "feature_x", "20260510130000") in load_dismissed_agents()


def test_kill_named_agent_index_write_failure_does_not_flip_success(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=_successful_user_kill(),
        ),
        patch("sase.running_field.release_workspace"),
        patch(
            "sase.ace.dismissed_agents.save_dismissed_agents",
            side_effect=RuntimeError("disk full"),
        ),
    ):
        result = kill_named_agent("my_agent")

    assert result.success is True


def test_kill_named_agent_permission_denied_keeps_question_active(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    _append_question(
        notification_id="live-question",
        cl_name="feature_x",
        child_timestamp="20260510130001",
        root_timestamp="20260510130000",
    )
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=SimpleNamespace(
                success=False,
                status="permission_denied",
            ),
        ),
    ):
        result = kill_named_agent("my_agent")

    assert result.success is False
    assert result.reason == "permission_denied"
    assert _notifications_by_id()["live-question"].dismissed is False


def test_kill_named_agent_notification_failure_does_not_flip_success(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=_successful_user_kill(),
        ),
        patch("sase.running_field.release_workspace"),
        patch(
            "sase.notifications.dismiss_notifications_matching_agents",
            side_effect=ValueError("invalid notification row"),
        ),
    ):
        result = kill_named_agent("my_agent")

    assert result.success is True


@pytest.mark.parametrize("home_or_nonhome", ["home", "nonhome"])
def test_kill_named_agent_dismissal_is_idempotent(
    tmp_path: Path, home_or_nonhome: str
) -> None:
    if home_or_nonhome == "home":
        artifacts_dir = _setup_home_agent(tmp_path, with_cl_name=True)
        ts = "20260510120000"
        cl_name = "home_feature"
    else:
        artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
        ts = "20260510130000"
        cl_name = "feature_x"

    found = NamedAgent(
        name="agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )
    _append_question(
        notification_id="question",
        cl_name=cl_name,
        child_timestamp=f"{ts}-child",
        root_timestamp=ts,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=_successful_user_kill(),
        ),
        patch("sase.running_field.release_workspace"),
    ):
        kill_named_agent("agent")
        kill_named_agent("agent")

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    dismissed = load_dismissed_agents()
    matching = [
        ident for ident in dismissed if ident == (AgentType.RUNNING, cl_name, ts)
    ]
    assert len(matching) == 1
    notifications = _notifications_by_id()
    assert list(notifications) == ["question"]
    assert notifications["question"].dismissed is True
