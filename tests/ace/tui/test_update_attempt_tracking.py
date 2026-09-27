"""Adapter mapping update-lane procs to journal attempts."""

from __future__ import annotations

from typing import Any

from sase.ace.tui._proc_observer_models import ObservedProc
from sase.ace.tui.actions._proc_action_types import TrackedProcResult
from sase.ace.tui.update_attempt_tracking import (
    settle_update_attempt_for_result,
    update_attempt_for,
)
from sase.core.time import local_now


def _row(proc_type: str, **kwargs: Any) -> ObservedProc:
    return ObservedProc(
        proc_id="proc-1",
        proc_type=proc_type,
        cl_name="sase",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
        **kwargs,
    )


def test_non_update_rows_return_none() -> None:
    assert update_attempt_for(_row("sync")) is None


def test_update_preview_maps_to_plan_stage() -> None:
    attempt = update_attempt_for(_row("update-preview"))

    assert attempt is not None
    assert attempt.stage == "plan"
    assert attempt.proc_type == "update-preview"


def test_comprehensive_update_maps_to_apply_stage() -> None:
    attempt = update_attempt_for(_row("comprehensive-update"))

    assert attempt is not None
    assert attempt.stage == "apply"


def test_attempt_carries_label_and_start() -> None:
    row = _row("sase-update", display_name="sase update")
    attempt = update_attempt_for(row)

    assert attempt is not None
    assert attempt.label == "sase update"
    assert attempt.started_at == row.started_at.timestamp()


def test_durable_plugin_update_is_an_attempt() -> None:
    assert update_attempt_for(_row("plugin.update")) is not None


def test_settle_skips_collisions_without_touching_journal(
    monkeypatch: Any,
) -> None:
    import sase.ace.tui.update_attempt_tracking as tracking

    calls: list[str] = []
    monkeypatch.setattr(
        tracking,
        "settle_update_attempt",
        lambda *args, **kwargs: calls.append("settle"),
    )
    attempt = update_attempt_for(_row("comprehensive-update"))
    assert attempt is not None

    view = settle_update_attempt_for_result(
        attempt,
        TrackedProcResult(success=True, message="dup", collision=True),
        output="out",
    )

    assert view is None
    assert calls == []


def test_settle_prefers_error_over_message(monkeypatch: Any) -> None:
    import sase.ace.tui.update_attempt_tracking as tracking

    seen: dict[str, Any] = {}

    def _fake_settle(attempt: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "view"

    monkeypatch.setattr(tracking, "settle_update_attempt", _fake_settle)
    attempt = update_attempt_for(_row("comprehensive-update"))
    assert attempt is not None

    assert (
        settle_update_attempt_for_result(
            attempt,
            TrackedProcResult(success=False, message="msg", error="boom"),
            output="out",
        )
        == "view"
    )
    assert seen == {"success": False, "error": "boom", "output": "out"}


def test_settle_falls_back_to_message_for_error(monkeypatch: Any) -> None:
    import sase.ace.tui.update_attempt_tracking as tracking

    seen: dict[str, Any] = {}

    def _fake_settle(attempt: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "view"

    monkeypatch.setattr(tracking, "settle_update_attempt", _fake_settle)
    attempt = update_attempt_for(_row("comprehensive-update"))
    assert attempt is not None

    settle_update_attempt_for_result(
        attempt,
        TrackedProcResult(success=False, message="msg", error=None),
        output="out",
    )

    assert seen["error"] == "msg"
    assert seen["success"] is False
