"""Truth-table tests for the propose-to-gate pending-review window predicate."""

import os

from sase.ace.tui.models._loaders._meta_enrichment_common import (
    pending_review_window_active,
)

# A PID that is guaranteed not to exist (beyond kernel PID_MAX_LIMIT).
_DEAD_PID = 99_999_999


def _open_window_kwargs() -> dict[str, object]:
    return {
        "plan_submitted": True,
        "plan_approved": False,
        "plan_action": None,
        "auto_approved": False,
        "gate_id": None,
        "gate_member_agent_name": None,
        "stopped_at": None,
        "has_done_marker": False,
        "pid": os.getpid(),
    }


def test_full_pre_gate_window_is_eligible() -> None:
    assert pending_review_window_active(**_open_window_kwargs()) is True


def test_plan_not_submitted_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["plan_submitted"] = False
    assert pending_review_window_active(**kwargs) is False


def test_plan_approved_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["plan_approved"] = True
    assert pending_review_window_active(**kwargs) is False


def test_plan_action_settled_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["plan_action"] = "tale"
    assert pending_review_window_active(**kwargs) is False


def test_auto_approved_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["auto_approved"] = True
    assert pending_review_window_active(**kwargs) is False


def test_creator_gate_id_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["gate_id"] = "gate-123"
    assert pending_review_window_active(**kwargs) is False


def test_creator_gate_member_agent_name_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["gate_member_agent_name"] = "sase-ws.3.g0"
    assert pending_review_window_active(**kwargs) is False


def test_stopped_at_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["stopped_at"] = "2026-09-05T11:16:34.061172+00:00"
    assert pending_review_window_active(**kwargs) is False


def test_done_marker_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["has_done_marker"] = True
    assert pending_review_window_active(**kwargs) is False


def test_missing_pid_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["pid"] = None
    assert pending_review_window_active(**kwargs) is False


def test_dead_pid_is_ineligible() -> None:
    kwargs = _open_window_kwargs()
    kwargs["pid"] = _DEAD_PID
    assert pending_review_window_active(**kwargs) is False
