"""Tests for agent PID liveness hardening."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import is_process_alive
from sase.core import process_identity


def _write_proc_entry(
    root: Path,
    pid: int,
    *,
    boot_id: str = "boot-a",
    start_ticks: int = 123,
    tgid: int | None = None,
    cmdline: bytes = b"python\0-m\0sase\0",
) -> None:
    (root / "sys/kernel/random").mkdir(parents=True, exist_ok=True)
    (root / "sys/kernel/random/boot_id").write_text(boot_id, encoding="utf-8")
    proc_dir = root / str(pid)
    proc_dir.mkdir(parents=True, exist_ok=True)
    stat_tail = ["S", *["0"] * 18, str(start_ticks)]
    (proc_dir / "stat").write_text(
        f"{pid} (python) {' '.join(stat_tail)}\n",
        encoding="utf-8",
    )
    (proc_dir / "status").write_text(
        "\n".join(
            (
                "Name:\tdconf worker",
                f"Tgid:\t{pid if tgid is None else tgid}",
                f"Pid:\t{pid}",
            )
        ),
        encoding="utf-8",
    )
    (proc_dir / "cmdline").write_bytes(cmdline)


def _artifact(tmp_path: Path, name: str = "20260827120000") -> Path:
    path = tmp_path / "artifacts" / "ace-run" / name
    path.mkdir(parents=True)
    return path


def _write_agent_meta(artifact_dir: Path, data: dict[str, object]) -> None:
    (artifact_dir / "agent_meta.json").write_text(json.dumps(data), encoding="utf-8")


def test_thread_pid_with_python_cmdline_is_dead(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(
        root,
        17549,
        tgid=17441,
        cmdline=b"/usr/bin/python3\0/usr/bin/blueman-applet\0",
    )
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)
    artifact_dir = _artifact(tmp_path)

    with patch("sase.ace.hooks.processes.is_process_running", return_value=True):
        assert not is_process_alive({"pid": 17549}, artifact_dir)


def test_recorded_identity_mismatch_is_dead(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(root, 1234, boot_id="boot-b", start_ticks=222)
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)
    artifact_dir = _artifact(tmp_path)
    _write_agent_meta(artifact_dir, {"pid": 1234, "process_identity": "boot-a:111"})

    with patch("sase.ace.hooks.processes.is_process_running", return_value=True):
        assert not is_process_alive({"pid": 1234}, artifact_dir)


def test_matching_recorded_identity_is_alive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(root, 1234, boot_id="boot-a", start_ticks=111)
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)
    artifact_dir = _artifact(tmp_path)

    with patch("sase.ace.hooks.processes.is_process_running", return_value=True):
        assert is_process_alive(
            {"pid": 1234, "process_identity": "boot-a:111"},
            artifact_dir,
        )


def test_legacy_record_started_before_current_boot_is_dead(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(root, 1234)
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)
    monkeypatch.setattr(
        process_identity,
        "current_boot_time_utc",
        lambda: datetime(2026, 8, 27, 10, 0, tzinfo=UTC),
    )
    artifact_dir = _artifact(tmp_path)

    with patch("sase.ace.hooks.processes.is_process_running", return_value=True):
        assert not is_process_alive(
            {"pid": 1234, "run_started_at": "2026-08-27T09:59:59Z"},
            artifact_dir,
        )


def test_legacy_record_started_after_current_boot_is_alive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(root, 1234)
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)
    monkeypatch.setattr(
        process_identity,
        "current_boot_time_utc",
        lambda: datetime(2026, 8, 27, 10, 0, tzinfo=UTC),
    )
    artifact_dir = _artifact(tmp_path)

    with patch("sase.ace.hooks.processes.is_process_running", return_value=True):
        assert is_process_alive(
            {"pid": 1234, "run_started_at": "2026-08-27T10:00:01Z"},
            artifact_dir,
        )


def test_absent_proc_keeps_legacy_liveness_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(process_identity, "_PROC_ROOT", tmp_path / "missing-proc")
    artifact_dir = _artifact(tmp_path)

    with patch("sase.ace.hooks.processes.is_process_running", return_value=True):
        assert is_process_alive({"pid": 1234}, artifact_dir)
