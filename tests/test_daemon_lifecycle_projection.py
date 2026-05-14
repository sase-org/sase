"""Projection maintenance and restore tests for daemon lifecycle commands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sase.integrations import daemon_lifecycle as lifecycle
from sase.integrations.daemon_lifecycle import _DaemonLifecycleError
from tests._daemon_lifecycle_helpers import _args, _metadata


def test_rebuild_uses_live_daemon_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    socket_path = tmp_path / "daemon.sock"
    monkeypatch.setattr(
        lifecycle,
        "_inspect_daemon",
        lambda _args: lifecycle._DaemonInspection(
            state="running",
            paths=lifecycle._DaemonRuntimePaths(
                sase_home=tmp_path / "home",
                run_root=run_root,
                socket_path=socket_path,
                metadata_path=run_root / "daemon.lock.json",
            ),
            metadata=_metadata(1234, "host"),
            rpc={"available": True, "health": {"status": "ok"}},
        ),
    )

    class FakeClient:
        def __init__(self, socket_path_arg: Path, *, timeout: float) -> None:
            assert socket_path_arg == socket_path
            assert timeout == 3

        def rebuild(
            self,
            *,
            storage_reset_only: bool,
            surface: str,
            project_id: str | None,
        ) -> dict[str, Any]:
            assert storage_reset_only is False
            assert surface == "beads"
            assert project_id == "demo"
            return {"mode": "projection_storage_rebuild"}

        def health(self) -> dict[str, Any]:
            return {
                "details": {
                    "projection_db": {
                        "source_exports": {
                            "state": "ok",
                            "pending": 0,
                            "failed": 0,
                            "conflict": 0,
                        }
                    }
                }
            }

    monkeypatch.setattr("sase.daemon.client.LocalDaemonClient", FakeClient)

    payload = lifecycle._run_daemon_rebuild(  # noqa: SLF001
        _args(rebuild_timeout=3, surface="beads", project_id="demo")
    )

    assert payload == {
        "mode": "projection_storage_rebuild",
        "source": "live_daemon_rpc",
        "source_exports": {
            "state": "ok",
            "pending": 0,
            "failed": 0,
            "conflict": 0,
        },
    }


def test_projection_maintenance_uses_live_daemon_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    socket_path = tmp_path / "daemon.sock"
    monkeypatch.setattr(
        lifecycle,
        "_inspect_daemon",
        lambda _args: lifecycle._DaemonInspection(
            state="running",
            paths=lifecycle._DaemonRuntimePaths(
                sase_home=tmp_path / "home",
                run_root=run_root,
                socket_path=socket_path,
                metadata_path=run_root / "daemon.lock.json",
            ),
            metadata=_metadata(1234, "host"),
            rpc={"available": True, "health": {"status": "ok"}},
        ),
    )
    calls: list[tuple[str, Any]] = []

    class FakeClient:
        def __init__(self, socket_path_arg: Path, *, timeout: float) -> None:
            assert socket_path_arg == socket_path
            assert timeout == 3

        def checkpoint(self, *, mode: str) -> dict[str, Any]:
            calls.append(("checkpoint", mode))
            return {"report": {"mode": mode}}

        def backup(self, *, path: str | None) -> dict[str, Any]:
            calls.append(("backup", path))
            return {"report": {"path": path or "auto.sqlite"}}

        def list_backups(self, *, limit: int) -> dict[str, Any]:
            calls.append(("list", limit))
            return {"backups": {"backups": []}}

        def restore(
            self,
            *,
            path: str,
            live_recovery: bool,
            allow_host_mismatch: bool,
        ) -> dict[str, Any]:
            calls.append(("restore", (path, live_recovery, allow_host_mismatch)))
            return {"report": {"projection_only": True}}

    monkeypatch.setattr("sase.daemon.client.LocalDaemonClient", FakeClient)

    assert (
        lifecycle._run_daemon_checkpoint(  # noqa: SLF001
            _args(checkpoint_timeout=3, mode="truncate")
        )["source"]
        == "live_daemon_rpc"
    )
    assert (
        lifecycle._run_daemon_backup(  # noqa: SLF001
            _args(backup_timeout=3, backup_path="manual.sqlite")
        )["source"]
        == "live_daemon_rpc"
    )
    assert (
        lifecycle._run_daemon_list_backups(  # noqa: SLF001
            _args(list_backups_timeout=3, limit=7)
        )["source"]
        == "live_daemon_rpc"
    )
    assert (
        lifecycle._run_daemon_restore(  # noqa: SLF001
            _args(
                restore_timeout=3,
                path=str(run_root / "backups" / "manual.sqlite"),
                live_recovery=True,
                allow_host_mismatch=True,
            )
        )["source"]
        == "live_daemon_rpc"
    )

    assert calls == [
        ("checkpoint", "truncate"),
        ("backup", "manual.sqlite"),
        ("list", 7),
        ("restore", (str(run_root / "backups" / "manual.sqlite"), True, True)),
    ]


def test_live_restore_requires_explicit_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    monkeypatch.setattr(
        lifecycle,
        "_inspect_daemon",
        lambda _args: lifecycle._DaemonInspection(
            state="running",
            paths=lifecycle._DaemonRuntimePaths(
                sase_home=tmp_path / "home",
                run_root=run_root,
                socket_path=tmp_path / "daemon.sock",
                metadata_path=run_root / "daemon.lock.json",
            ),
            metadata=_metadata(1234, "host"),
            rpc={"available": True, "health": {"status": "ok"}},
        ),
    )

    with pytest.raises(_DaemonLifecycleError, match="--live-recovery"):
        lifecycle._run_daemon_restore(  # noqa: SLF001
            _args(path=str(run_root / "backups" / "manual.sqlite"))
        )


def test_offline_restore_copies_projection_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    backup = run_root / "backups" / "manual.sqlite"
    backup.parent.mkdir(parents=True)
    with sqlite3.connect(backup) as conn:
        conn.execute("CREATE TABLE event_log(seq INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO event_log(seq) VALUES (1)")
    backup.with_name(backup.name + ".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backup_format_version": 1,
                "host_identity": "test-host",
                "event_max_sequence": 1,
            }
        ),
        encoding="utf-8",
    )
    source_store = tmp_path / "home" / "projects" / "demo.sase"
    source_store.parent.mkdir(parents=True)
    source_store.write_text("NAME: source\n", encoding="utf-8")
    monkeypatch.setenv("HOSTNAME", "test-host")
    monkeypatch.setattr(
        lifecycle,
        "_inspect_daemon",
        lambda _args: lifecycle._DaemonInspection(
            state="stopped",
            paths=lifecycle._DaemonRuntimePaths(
                sase_home=tmp_path / "home",
                run_root=run_root,
                socket_path=tmp_path / "daemon.sock",
                metadata_path=run_root / "daemon.lock.json",
            ),
            message="not running",
        ),
    )

    payload = lifecycle._run_daemon_restore(  # noqa: SLF001
        _args(path=str(backup))
    )

    restored = run_root / "projections" / "projection.sqlite"
    assert payload["source"] == "offline_projection_restore"
    assert payload["report"]["projection_only"] is True
    assert restored.is_file()
    assert source_store.read_text(encoding="utf-8") == "NAME: source\n"
