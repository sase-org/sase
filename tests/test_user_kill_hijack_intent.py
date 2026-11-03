"""Hijack-mode user-kill intent markers keep old plain-kill markers working."""

from __future__ import annotations

from pathlib import Path

from sase.agent._user_kill_intent import (
    ensure_user_kill_intent,
    has_hijack_intent,
    has_user_kill_intent,
    hijack_intent_id,
    pending_hijack_recovery,
    write_user_kill_intent,
)
from sase.finalizers.controller_context import should_skip_finalizers


def test_write_hijack_mode_intent(tmp_path: Path) -> None:
    path = write_user_kill_intent(
        tmp_path,
        pid=9,
        source="test",
        mode="hijack",
        hijack_id="h-42",
        reason="stalled",
    )
    assert path is not None
    assert has_user_kill_intent(tmp_path) is True
    assert has_hijack_intent(tmp_path) is True
    assert hijack_intent_id(tmp_path) == "h-42"
    assert pending_hijack_recovery(tmp_path) == {
        "state": "pending",
        "kind": "hijack",
        "hijack_id": "h-42",
    }


def test_old_format_intent_is_plain_kill(tmp_path: Path) -> None:
    write_user_kill_intent(tmp_path, pid=9, source="test")
    assert has_user_kill_intent(tmp_path) is True
    assert has_hijack_intent(tmp_path) is False
    assert hijack_intent_id(tmp_path) is None


def test_ensure_user_kill_intent_does_not_upgrade_plain_kill(tmp_path: Path) -> None:
    write_user_kill_intent(tmp_path, pid=9, source="test")
    ensure_user_kill_intent(
        tmp_path,
        pid=9,
        source="hijack",
        mode="hijack",
        hijack_id="h-1",
    )
    assert has_hijack_intent(tmp_path) is False
    assert hijack_intent_id(tmp_path) is None


def test_should_skip_finalizers_on_hijack_intent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260101120000")
    write_user_kill_intent(
        tmp_path,
        pid=9,
        source="test",
        mode="hijack",
        hijack_id="h-1",
    )
    assert should_skip_finalizers(str(tmp_path)) is True


def test_should_skip_finalizers_leaves_plain_kill_alone(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260101120000")
    write_user_kill_intent(tmp_path, pid=9, source="test")
    assert should_skip_finalizers(str(tmp_path)) is False
