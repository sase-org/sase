"""Predicate tests for row-owned settlement notification matching."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._notification_utils import (
    agent_row_notification_matches_agent,
    _agent_settlement_notification_matches_agent,
)

_CL_NAME = "gh_sase-org__sase"
_RAW_SUFFIX = "20260920082910"


def _notification(
    *,
    sender: str = "epic-launch",
    action: Any = None,
    action_data: dict[str, Any] | None = None,
    dismissed: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="n-settlement",
        sender=sender,
        action=action,
        action_data=(
            {"cl_name": _CL_NAME, "raw_suffix": _RAW_SUFFIX}
            if action_data is None
            else action_data
        ),
        dismissed=dismissed,
    )


def _matches(notification: SimpleNamespace) -> bool:
    return _agent_settlement_notification_matches_agent(
        notification, cl_name=_CL_NAME, raw_suffix=_RAW_SUFFIX
    )


def test_exact_epic_launch_match() -> None:
    assert _matches(_notification())


def test_exact_monitor_settlement_match() -> None:
    assert _matches(_notification(sender="monitor-settlement"))


def test_wrong_raw_suffix_does_not_match() -> None:
    notification = _notification(
        action_data={"cl_name": _CL_NAME, "raw_suffix": "other"}
    )
    assert not _matches(notification)


def test_missing_raw_suffix_does_not_match() -> None:
    notification = _notification(action_data={"cl_name": _CL_NAME})
    assert not _matches(notification)


def test_empty_raw_suffix_does_not_match() -> None:
    notification = _notification(action_data={"cl_name": _CL_NAME, "raw_suffix": ""})
    assert not _matches(notification)


def test_missing_cl_name_does_not_match() -> None:
    notification = _notification(action_data={"raw_suffix": _RAW_SUFFIX})
    assert not _matches(notification)


def test_dismissed_row_does_not_match() -> None:
    assert not _matches(_notification(dismissed=True))


def test_non_settlement_sender_does_not_match() -> None:
    assert not _matches(_notification(sender="axe", action="JumpToAgent"))
    assert not _matches(_notification(sender="user-agent", action="JumpToAgent"))


def test_row_predicate_covers_completion_and_settlement() -> None:
    completion = _notification(sender="user-agent", action="JumpToAgent")
    settlement = _notification()
    unrelated = _notification(sender="axe")

    assert agent_row_notification_matches_agent(
        completion, cl_name=_CL_NAME, raw_suffix=_RAW_SUFFIX
    )
    assert agent_row_notification_matches_agent(
        settlement, cl_name=_CL_NAME, raw_suffix=_RAW_SUFFIX
    )
    assert not agent_row_notification_matches_agent(
        unrelated, cl_name=_CL_NAME, raw_suffix=_RAW_SUFFIX
    )
