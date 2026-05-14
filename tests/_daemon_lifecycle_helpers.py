"""Shared helpers for daemon lifecycle tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _args(**overrides: Any) -> argparse.Namespace:
    values = {
        "sase_home": None,
        "run_root": None,
        "socket_path": None,
        "foreground": False,
        "tokio_console": False,
        "disable_mobile_http": False,
        "bind_address": None,
        "allow_non_loopback": False,
        "agent_bridge_command": None,
        "helper_bridge_command": None,
        "daemon_command": None,
        "startup_timeout": None,
        "stop_timeout": None,
        "rebuild_timeout": None,
        "checkpoint_timeout": None,
        "backup_timeout": None,
        "list_backups_timeout": None,
        "restore_timeout": None,
        "verify_timeout": None,
        "diff_timeout": None,
        "backup_path": None,
        "path": None,
        "live_recovery": False,
        "allow_host_mismatch": False,
        "surface": "all",
        "project_id": None,
        "storage_reset_only": False,
        "limit": 100,
        "cursor": None,
        "json_output": False,
        "repair_stale_lock": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _metadata(pid: int, host: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "pid": pid,
        "hostname": host,
        "boot_session_hint": "boot",
        "executable_path": str(Path("/proc") / str(pid) / "exe"),
        "socket_path": "/tmp/sase-daemon.sock",
        "started_at": "2026-05-13T00:00:00Z",
        "sase_home": "/tmp/sase",
        "build_version": "test",
    }
    payload.update(overrides)
    return payload


def _write_metadata(run_root: Path, payload: dict[str, Any]) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "daemon.lock.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
