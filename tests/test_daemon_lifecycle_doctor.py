"""Doctor and repair tests for daemon lifecycle commands."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.integrations import daemon_lifecycle as lifecycle
from sase.integrations.daemon_lifecycle import _DaemonLifecycleError
from tests._daemon_lifecycle_helpers import _args, _metadata, _write_metadata


def test_doctor_reports_unsafe_storage_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    home = tmp_path / "home"
    run_root = home / "projects" / "demo" / "run"

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(home), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    layout_check = [
        check
        for check in payload["doctor"]["checks"]
        if check["name"] == "storage_layout"
    ][0]
    assert layout_check["state"] == "error"
    assert "run_root_under_source_root" in layout_check["message"]
    assert payload["storage_layout"]["run_root"]["path_kind"] == "source_root"
    assert [action["id"] for action in payload["repair_actions"]] == ["move_run_root"]


def test_doctor_reports_stable_repair_actions_for_stale_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(4_294_967_000, "workstation.local"))

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    assert payload["repair_actions"] == payload["doctor"]["repair_actions"]
    remove_stale_lock = payload["repair_actions"][0]
    assert remove_stale_lock["id"] == "remove_stale_lock"
    assert remove_stale_lock["risk"] == "runtime_only"
    assert "--repair-stale-lock" in remove_stale_lock["command"]


def test_doctor_human_output_prints_exact_repair_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(4_294_967_000, "workstation.local"))

    code = lifecycle.handle_daemon_doctor(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "Repair actions:" in out
    assert "- remove_stale_lock: runtime_only" in out
    assert "Command: sase daemon doctor" in out
    assert "--repair-stale-lock" in out


def test_doctor_repair_stale_lock_removes_runtime_only_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    socket_path = run_root / "sase-daemon.sock"
    _write_metadata(run_root, _metadata(4_294_967_000, "workstation.local"))
    (run_root / lifecycle.LOCK_FILENAME).write_text("", encoding="utf-8")
    socket_path.write_text("stale socket", encoding="utf-8")

    payload = lifecycle._repair_stale_lock(  # noqa: SLF001
        _args(
            sase_home=str(tmp_path / "home"),
            run_root=str(run_root),
            socket_path=str(socket_path),
        )
    )

    assert payload["action"] == "remove_stale_lock"
    assert not (run_root / lifecycle.LOCK_FILENAME).exists()
    assert not (run_root / lifecycle.LOCK_METADATA_FILENAME).exists()
    assert not socket_path.exists()


def test_doctor_repair_stale_lock_refuses_host_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "this-host")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(4_294_967_000, "other-host"))

    with pytest.raises(_DaemonLifecycleError, match="refusing stale-lock repair"):
        lifecycle._repair_stale_lock(  # noqa: SLF001
            _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
        )


def test_doctor_distinguishes_degraded_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "status": "degraded",
                "details": {
                    "projection_db": {
                        "state": "degraded",
                        "schema_initialized": True,
                        "migrations_applied": True,
                        "repair_needed": True,
                        "gap_count": 1,
                        "recovery_issue_count": 0,
                        "message": "projection replay needs repair",
                    }
                },
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    assert payload["doctor"]["state"] == "degraded"
    projection = [
        check
        for check in payload["doctor"]["checks"]
        if check["name"] == "projection_db"
    ][0]
    assert projection["state"] == "degraded"
    assert projection["message"] == "projection replay needs repair"


def test_health_rpc_keeps_liveness_when_detailed_diagnostics_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_path = tmp_path / "sase-daemon.sock"
    socket_path.write_text("", encoding="utf-8")

    class FakeClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def health(
            self,
            *,
            include_capabilities: bool = True,
            timeout: float | None = None,
        ) -> dict[str, object]:
            if not include_capabilities:
                return {
                    "status": "ok",
                    "details": {"projection_db": {"state": "ok"}},
                }
            raise TimeoutError(f"detailed health timed out after {timeout}")

    monkeypatch.setattr("sase.daemon.client.LocalDaemonClient", FakeClient)

    rpc = lifecycle._try_health_rpc(socket_path)

    assert rpc["available"] is True
    assert rpc["health"] == {
        "status": "ok",
        "details": {"projection_db": {"state": "ok"}},
    }
    assert rpc["diagnostics"]["available"] is False
    assert "detailed health timed out" in rpc["diagnostics"]["message"]


def test_doctor_marks_slow_detailed_diagnostics_unknown_not_rpc_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "status": "ok",
                "details": {"projection_db": {"state": "ok"}},
            },
            "diagnostics": {
                "available": False,
                "message": "detailed health timed out",
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001
    checks = {check["name"]: check for check in payload["doctor"]["checks"]}

    assert checks["socket_rpc_health"]["state"] == "ok"
    assert "detailed diagnostics unavailable" in checks["socket_rpc_health"]["message"]
    assert checks["source_exports"]["state"] == "unknown"
    assert checks["scheduler"]["state"] == "unknown"


def test_doctor_reports_source_export_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "status": "degraded",
                "details": {
                    "projection_db": {
                        "state": "degraded",
                        "schema_initialized": True,
                        "migrations_applied": True,
                        "repair_needed": True,
                        "gap_count": 0,
                        "recovery_issue_count": 1,
                        "source_exports": {
                            "state": "degraded",
                            "message": "1 source export(s) still need repair",
                            "pending": 0,
                            "failed": 0,
                            "conflict": 1,
                        },
                    }
                },
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    source_exports = [
        check
        for check in payload["doctor"]["checks"]
        if check["name"] == "source_exports"
    ][0]
    assert source_exports["state"] == "degraded"
    assert source_exports["message"] == "1 source export(s) still need repair"


def test_doctor_reports_scheduler_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "status": "degraded",
                "details": {
                    "scheduler": {
                        "state": "degraded",
                        "queue_depth": 3,
                        "running_tasks": 2,
                        "starting_tasks": 1,
                        "blocked_tasks": 0,
                        "stale_starts": 1,
                        "host_bridge": {"available": True},
                        "projection_lag": {"pending_events": 0},
                    }
                },
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._doctor_payload(inspection)  # noqa: SLF001

    scheduler = [
        check for check in payload["doctor"]["checks"] if check["name"] == "scheduler"
    ][0]
    assert scheduler["state"] == "degraded"
    assert "queued=3" in scheduler["message"]
    assert "stale_starts=1" in scheduler["message"]
