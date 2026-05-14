"""Hermetic sync-chaos fixtures for daemon lifecycle recovery states."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sase.integrations import daemon_lifecycle as lifecycle


def _args(**overrides: Any) -> argparse.Namespace:
    values = {
        "sase_home": None,
        "run_root": None,
        "socket_path": None,
        "json_output": False,
        "repair_stale_lock": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@dataclass(frozen=True)
class ChaosHost:
    identity: str
    run_root: Path

    @property
    def socket_path(self) -> Path:
        return self.run_root / "sase-daemon.sock"


@dataclass(frozen=True)
class SyncChaosFixture:
    sase_home: Path
    host_a: ChaosHost
    host_b: ChaosHost
    shared_run_root: Path
    source_marker: Path

    @classmethod
    def create(cls, root: Path) -> SyncChaosFixture:
        home = root / "sase-home"
        host_a = ChaosHost("host-a", home / "run" / "host-a")
        host_b = ChaosHost("host-b", home / "run" / "host-b")
        shared_run_root = home / "run" / "shared"
        source_marker = home / "projects" / "demo.sase"
        _write_source_stores(home)
        return cls(home, host_a, host_b, shared_run_root, source_marker)

    def args_for(self, host: ChaosHost, **overrides: Any) -> argparse.Namespace:
        values = {
            "sase_home": str(self.sase_home),
            "run_root": str(host.run_root),
            "socket_path": str(host.socket_path),
        }
        values.update(overrides)
        return _args(**values)


def _write_source_stores(home: Path) -> None:
    project_dir = home / "projects"
    project_dir.mkdir(parents=True)
    (project_dir / "demo.sase").write_text(
        "NAME: demo\nSTATUS: WIP\n",
        encoding="utf-8",
    )

    notifications_dir = home / "notifications"
    notifications_dir.mkdir()
    (notifications_dir / "notifications.jsonl").write_text(
        json.dumps(
            {
                "id": "notif-chaos",
                "timestamp": "2026-05-14T00:00:00+00:00",
                "sender": "test",
                "notes": ["sync chaos"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    beads_dir = home / "projects" / "demo" / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text("{}", encoding="utf-8")
    (beads_dir / "issues.jsonl").write_text("", encoding="utf-8")

    xprompts_dir = home / "projects" / "demo" / "xprompts"
    xprompts_dir.mkdir(parents=True)
    (xprompts_dir / "helper.md").write_text("# Helper\n", encoding="utf-8")

    agent_dir = (
        home
        / "artifacts"
        / "projects"
        / "demo"
        / "artifacts"
        / "chaos"
        / "20260514000000"
    )
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent_meta.json").write_text('{"name":"chaos"}\n', encoding="utf-8")


def _write_metadata(run_root: Path, host: str, pid: int) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "pid": pid,
        "hostname": host,
        "boot_session_hint": "boot",
        "executable_path": str(Path("/proc") / str(pid) / "exe"),
        "socket_path": str(run_root / "sase-daemon.sock"),
        "started_at": "2026-05-14T00:00:00Z",
        "sase_home": str(run_root.parent.parent),
        "build_version": "test",
    }
    (run_root / lifecycle.LOCK_METADATA_FILENAME).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_two_hosts_share_sources_but_keep_runtime_files_host_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = SyncChaosFixture.create(tmp_path)
    _write_metadata(fixture.host_a.run_root, "host-a", os.getpid())
    _write_metadata(fixture.host_b.run_root, "host-b", os.getpid())

    monkeypatch.setenv("HOSTNAME", "host-a")
    host_a_paths = lifecycle._runtime_paths_from_args(  # noqa: SLF001
        _args(sase_home=str(fixture.sase_home))
    )
    host_a = lifecycle._inspect_daemon(fixture.args_for(fixture.host_a))  # noqa: SLF001

    monkeypatch.setenv("HOSTNAME", "host-b")
    host_b_paths = lifecycle._runtime_paths_from_args(  # noqa: SLF001
        _args(sase_home=str(fixture.sase_home))
    )
    host_b = lifecycle._inspect_daemon(fixture.args_for(fixture.host_b))  # noqa: SLF001

    assert host_a_paths.run_root == fixture.host_a.run_root
    assert host_b_paths.run_root == fixture.host_b.run_root
    assert host_a.projection_db_path != host_b.projection_db_path
    assert host_a.lock_path != host_b.lock_path
    assert host_a.state == "running"
    assert host_b.state == "running"
    assert (
        fixture.source_marker.read_text(encoding="utf-8") == "NAME: demo\nSTATUS: WIP\n"
    )


def test_corrupt_lock_metadata_repairs_runtime_only_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = SyncChaosFixture.create(tmp_path)
    monkeypatch.setenv("HOSTNAME", "host-a")
    fixture.host_a.run_root.mkdir(parents=True)
    (fixture.host_a.run_root / lifecycle.LOCK_FILENAME).write_text("", encoding="utf-8")
    (fixture.host_a.run_root / lifecycle.LOCK_METADATA_FILENAME).write_text(
        "{not-json",
        encoding="utf-8",
    )

    inspection = lifecycle._inspect_daemon(fixture.args_for(fixture.host_a))  # noqa: SLF001
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001
    repair = lifecycle._repair_stale_lock(fixture.args_for(fixture.host_a))  # noqa: SLF001

    assert inspection.state == "stale"
    assert payload["repair_actions"][0]["id"] == "remove_stale_lock"
    assert payload["repair_actions"][0]["risk"] == "runtime_only"
    assert repair["removed"] == [
        str(fixture.host_a.run_root / lifecycle.LOCK_METADATA_FILENAME),
        str(fixture.host_a.run_root / lifecycle.LOCK_FILENAME),
    ]
    assert (
        fixture.source_marker.read_text(encoding="utf-8") == "NAME: demo\nSTATUS: WIP\n"
    )


def test_shared_runtime_directory_is_reported_as_host_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = SyncChaosFixture.create(tmp_path)
    _write_metadata(fixture.shared_run_root, "host-a", 4_294_967_000)

    monkeypatch.setenv("HOSTNAME", "host-b")
    inspection = lifecycle._inspect_daemon(  # noqa: SLF001
        _args(
            sase_home=str(fixture.sase_home),
            run_root=str(fixture.shared_run_root),
            socket_path=str(fixture.shared_run_root / "sase-daemon.sock"),
        )
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    assert inspection.state == "conflict"
    assert "metadata belongs to host 'host-a'" in inspection.message
    assert payload["repair_actions"][0]["id"] == "inspect_host_conflict"
    assert payload["repair_actions"][0]["risk"] == "requires_manual_review"
    assert payload["storage_layout"]["run_root"]["path_kind"] == "host_local_override"
