"""Tests for durable TUI toast history logging."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.logs import toast_log


@pytest.fixture(autouse=True)
def toast_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    toast_log.flush_toasts(timeout=1.0)
    monkeypatch.setattr(
        toast_log,
        "TUI_TOASTS_JSONL",
        str(tmp_path / "tui_toasts.jsonl"),
    )
    toast_log._reset_current_toast_session(
        session_started_at=datetime(2026, 7, 7, 9, 12, 33, tzinfo=UTC),
        pid=1234,
    )
    yield tmp_path / "tui_toasts.jsonl"
    toast_log.flush_toasts(timeout=1.0)
    toast_log._reset_current_toast_session()


def _record(
    idx: int,
    *,
    session_id: str = "session-a",
    pid: int = 100,
) -> dict[str, object]:
    timestamp = datetime(2026, 7, 7, 9, 0, tzinfo=UTC) + timedelta(seconds=idx)
    return {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "session_id": session_id,
        "session_started_at": "2026-07-07T09:00:00Z",
        "pid": pid,
        "severity": "information",
        "title": "",
        "message": f"toast {idx}",
    }


def test_path_override_and_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_path = tmp_path / "module.jsonl"
    env_path = tmp_path / "env.jsonl"

    monkeypatch.setattr(toast_log, "TUI_TOASTS_JSONL", str(module_path))
    monkeypatch.setenv(toast_log.ENV_TOASTS_PATH, str(env_path))
    assert toast_log.tui_toasts_jsonl_path() == module_path

    monkeypatch.setattr(toast_log, "TUI_TOASTS_JSONL", None)
    assert toast_log.tui_toasts_jsonl_path() == env_path


def test_current_session_is_memoized_and_resettable() -> None:
    first = toast_log.current_toast_session()
    assert toast_log.current_toast_session() == first

    second = toast_log._reset_current_toast_session(
        session_started_at=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
        pid=4321,
    )

    assert second is not None
    assert second != first
    assert second.session_id == "20260708T100000Z-4321"
    assert toast_log.current_toast_session() == second


def test_record_toast_enqueue_flush_round_trip(toast_log_path: Path) -> None:
    toast_log.record_toast("line one\nline two", title="Build", severity="warning")

    assert toast_log.flush_toasts(timeout=2.0)
    raw = toast_log_path.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 1
    data = json.loads(raw[0])
    assert data["session_id"] == "20260707T091233Z-1234"
    assert data["session_started_at"] == "2026-07-07T09:12:33Z"
    assert data["pid"] == 1234
    assert data["severity"] == "warning"
    assert data["title"] == "Build"
    assert data["message"] == "line one\nline two"
    assert data["timestamp"].endswith("Z")

    records = toast_log.read_recent_toasts()
    assert len(records) == 1
    assert records[0].message == "line one\nline two"


def test_compaction_keeps_exactly_last_100_after_slack(
    toast_log_path: Path,
) -> None:
    for idx in range(toast_log.TOAST_HISTORY_LIMIT + 50):
        toast_log._append_record(toast_log_path, _record(idx))

    assert len(toast_log_path.read_text(encoding="utf-8").splitlines()) == 150

    toast_log._append_record(toast_log_path, _record(150))
    lines = toast_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == toast_log.TOAST_HISTORY_LIMIT
    assert json.loads(lines[0])["message"] == "toast 51"
    assert json.loads(lines[-1])["message"] == "toast 150"


def test_size_rotation_uses_single_generation(
    toast_log_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_log_path.write_text(json.dumps(_record(1)) + "\n", encoding="utf-8")
    rotated = toast_log_path.with_name(f"{toast_log_path.name}.1")
    rotated.write_text("stale backup\n", encoding="utf-8")
    monkeypatch.setenv(toast_log.ENV_MAX_BYTES, "1")

    toast_log._append_record(toast_log_path, _record(2))

    assert json.loads(rotated.read_text(encoding="utf-8"))["message"] == "toast 1"
    assert json.loads(toast_log_path.read_text(encoding="utf-8"))["message"] == (
        "toast 2"
    )
    assert not toast_log_path.with_name(f"{toast_log_path.name}.2").exists()


def test_read_recent_toasts_skips_malformed_lines(toast_log_path: Path) -> None:
    toast_log_path.write_text(
        "\n".join(
            [
                "not json",
                json.dumps({"timestamp": "2026-07-07T09:00:00Z"}),
                json.dumps(_record(1)),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = toast_log.read_recent_toasts()

    assert len(records) == 1
    assert records[0].message == "toast 1"


def test_writer_never_raises_for_unwritable_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory_path = tmp_path / "directory-not-file"
    directory_path.mkdir()
    monkeypatch.setattr(toast_log, "TUI_TOASTS_JSONL", str(directory_path))

    toast_log.record_toast("cannot write here", severity="error")

    assert toast_log.flush_toasts(timeout=2.0)


def test_locked_appends_from_interleaved_sessions_do_not_corrupt_file(
    toast_log_path: Path,
) -> None:
    def writer(session_id: str, pid: int) -> None:
        for idx in range(25):
            toast_log._append_record(
                toast_log_path,
                _record(idx, session_id=session_id, pid=pid),
            )

    threads = [
        threading.Thread(target=writer, args=("session-a", 100)),
        threading.Thread(target=writer, args=("session-b", 200)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = toast_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    records = [json.loads(line) for line in lines]
    assert {record["session_id"] for record in records} == {"session-a", "session-b"}
