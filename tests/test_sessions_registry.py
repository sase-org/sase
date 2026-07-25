"""Tests for the live SASE session registry (``sase.sessions.registry``)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.logs import toast_log
from sase.sessions import registry
from sase.sessions.registry import (
    SessionIdentity,
    SessionRefError,
    current_session_id,
    latest_session,
    live_sessions,
    register_session,
    resolve_session_ref,
    session_record_path,
    sessions_dir,
    unregister_session,
)
from tests.conftest import redirect_sase_home


@pytest.fixture(autouse=True)
def _sase_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Point ``~/.sase`` at a tmp dir and pin this process's session id."""
    home = redirect_sase_home(monkeypatch, tmp_path / "sase-home")
    toast_log._reset_current_toast_session(
        session_started_at="2026-07-25T12:00:00Z",
        pid=os.getpid(),
    )
    yield home
    toast_log._reset_current_toast_session()


def _write_record(session_id: str, **overrides: object) -> Path:
    record: dict[str, object] = {
        "session_id": session_id,
        "kind": "ace",
        "pid": os.getpid(),
        "started_at": "2026-07-25T12:00:00Z",
        "project": "sase",
        "workspace_num": 27,
        "cwd": "/tmp",
        "title": "sase ace",
    }
    record.update(overrides)
    path = session_record_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


# --- current_session_id ---


def test_current_session_id_matches_toast_session() -> None:
    assert current_session_id() == toast_log.current_toast_session().session_id


def test_current_session_id_is_stable_across_calls() -> None:
    assert current_session_id() == current_session_id()


# --- register/unregister round trip ---


def test_register_session_round_trip() -> None:
    identity = register_session(project="sase", workspace_num=27, title="ace")
    assert identity is not None
    assert identity.session_id == current_session_id()

    sessions = live_sessions()
    assert [item.session_id for item in sessions] == [identity.session_id]
    assert sessions[0].project == "sase"
    assert sessions[0].workspace_num == 27
    assert sessions[0].title == "ace"
    assert sessions[0].cwd == os.getcwd()


def test_register_session_records_process_identity() -> None:
    identity = register_session()
    assert identity is not None
    record = json.loads(
        session_record_path(identity.session_id).read_text(encoding="utf-8")
    )
    assert record["process_identity"]["start_ticks"] >= 0


def test_unregister_session_removes_the_record() -> None:
    identity = register_session()
    assert identity is not None
    assert unregister_session() is True
    assert not session_record_path(identity.session_id).exists()
    assert live_sessions() == []


def test_unregister_session_without_a_record_is_false() -> None:
    assert unregister_session() is False


def test_register_session_survives_a_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(path: Path, record: dict[str, object]) -> None:
        raise OSError("boom")

    monkeypatch.setattr(registry, "_write_record", _boom)
    assert register_session() is None


# --- liveness pruning ---


def test_live_sessions_drops_and_deletes_a_dead_pid() -> None:
    path = _write_record("20260725T110000Z-999999", pid=999999)
    assert live_sessions() == []
    assert not path.exists()


def test_live_sessions_drops_a_reused_pid() -> None:
    path = _write_record(
        "20260725T110000Z-1",
        process_identity={"start_ticks": 1, "boot_id": "stale"},
    )
    assert live_sessions() == []
    assert not path.exists()


def test_live_sessions_keeps_a_record_without_a_process_identity() -> None:
    _write_record("20260725T110000Z-2")
    assert [item.session_id for item in live_sessions()] == ["20260725T110000Z-2"]


def test_live_sessions_drops_malformed_records() -> None:
    path = sessions_dir() / "junk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")
    assert live_sessions() == []
    assert not path.exists()


def test_live_sessions_is_empty_without_a_registry_directory() -> None:
    assert live_sessions() == []


def test_live_sessions_are_newest_first() -> None:
    _write_record("20260725T110000Z-a", started_at="2026-07-25T11:00:00Z")
    _write_record("20260725T130000Z-b", started_at="2026-07-25T13:00:00Z")
    assert [item.session_id for item in live_sessions()] == [
        "20260725T130000Z-b",
        "20260725T110000Z-a",
    ]


def test_latest_session_returns_the_newest_live_session() -> None:
    _write_record("20260725T110000Z-a", started_at="2026-07-25T11:00:00Z")
    _write_record("20260725T130000Z-b", started_at="2026-07-25T13:00:00Z")
    newest = latest_session()
    assert newest is not None
    assert newest.session_id == "20260725T130000Z-b"


def test_latest_session_is_none_when_nothing_is_running() -> None:
    assert latest_session() is None


# --- resolve_session_ref ---


def test_resolve_session_ref_none_is_always_none() -> None:
    register_session()
    assert resolve_session_ref("none") is None


def test_resolve_session_ref_current_prefers_this_process() -> None:
    _write_record("20260725T130000Z-b", started_at="2026-07-25T13:00:00Z")
    identity = register_session()
    assert identity is not None
    resolved = resolve_session_ref("current")
    assert resolved is not None
    assert resolved.session_id == identity.session_id


def test_resolve_session_ref_defaults_to_current() -> None:
    identity = register_session()
    assert identity is not None
    resolved = resolve_session_ref(None)
    assert resolved is not None
    assert resolved.session_id == identity.session_id


def test_resolve_session_ref_current_falls_back_to_latest() -> None:
    _write_record("20260725T110000Z-a", started_at="2026-07-25T11:00:00Z")
    _write_record("20260725T130000Z-b", started_at="2026-07-25T13:00:00Z")
    resolved = resolve_session_ref("current")
    assert resolved is not None
    assert resolved.session_id == "20260725T130000Z-b"


def test_resolve_session_ref_current_falls_back_to_no_session() -> None:
    assert resolve_session_ref("current") is None


def test_resolve_session_ref_latest() -> None:
    _write_record("20260725T130000Z-b", started_at="2026-07-25T13:00:00Z")
    resolved = resolve_session_ref("latest")
    assert resolved is not None
    assert resolved.session_id == "20260725T130000Z-b"


def test_resolve_session_ref_full_id() -> None:
    _write_record("20260725T110000Z-a")
    resolved = resolve_session_ref("20260725T110000Z-a")
    assert resolved is not None
    assert resolved.session_id == "20260725T110000Z-a"


def test_resolve_session_ref_short_handle() -> None:
    from sase.sessions.display import short_session_handle

    _write_record("20260725T110000Z-a")
    handle = short_session_handle("20260725T110000Z-a")
    resolved = resolve_session_ref(handle.upper())
    assert resolved is not None
    assert resolved.session_id == "20260725T110000Z-a"


def test_resolve_session_ref_unique_prefix() -> None:
    _write_record("20260725T110000Z-a")
    _write_record("20260726T110000Z-b")
    resolved = resolve_session_ref("20260726")
    assert resolved is not None
    assert resolved.session_id == "20260726T110000Z-b"


def test_resolve_session_ref_ambiguous_prefix_lists_candidates() -> None:
    _write_record("20260725T110000Z-a")
    _write_record("20260725T110000Z-b")
    with pytest.raises(SessionRefError) as excinfo:
        resolve_session_ref("20260725")
    message = str(excinfo.value)
    assert "ambiguous" in message
    assert "20260725T110000Z-a" in message
    assert "20260725T110000Z-b" in message


def test_resolve_session_ref_unknown_ref_raises() -> None:
    _write_record("20260725T110000Z-a")
    with pytest.raises(SessionRefError) as excinfo:
        resolve_session_ref("nope")
    assert "no live session" in str(excinfo.value)
    assert "20260725T110000Z-a" in str(excinfo.value)


def test_resolve_session_ref_unknown_ref_without_sessions_says_so() -> None:
    with pytest.raises(SessionRefError) as excinfo:
        resolve_session_ref("nope")
    assert "no SASE sessions are running" in str(excinfo.value)


# --- record tolerance ---


def test_identity_from_record_rejects_incomplete_records() -> None:
    assert registry._identity_from_record({"pid": 1}) is None
    assert registry._identity_from_record({"session_id": "x"}) is None
    assert registry._identity_from_record({"session_id": "x", "pid": 0}) is None


def test_identity_from_record_tolerates_unknown_keys() -> None:
    identity = registry._identity_from_record(
        {
            "session_id": "x",
            "pid": 1,
            "started_at": "2026-07-25T12:00:00Z",
            "surprise": True,
            "workspace_num": "not an int",
        }
    )
    assert identity == SessionIdentity(
        session_id="x",
        kind="ace",
        pid=1,
        started_at="2026-07-25T12:00:00Z",
        workspace_num=None,
    )
