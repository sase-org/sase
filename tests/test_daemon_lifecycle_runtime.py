"""Runtime inspection, start, stop, and status tests for daemon lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sase.integrations import daemon_lifecycle as lifecycle
from sase.integrations.daemon_lifecycle import _DaemonLifecycleError
from tests._daemon_lifecycle_helpers import _args, _metadata, _write_metadata


def test_inspect_daemon_stopped(tmp_path: Path) -> None:
    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(tmp_path / "run"))
    )

    assert inspection.state == "stopped"
    assert "no ownership metadata" in inspection.message


def test_inspect_daemon_running_from_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "running"
    assert inspection.metadata is not None
    assert inspection.metadata["pid"] == os.getpid()
    assert inspection.rpc is not None
    assert inspection.rpc["available"] is False


def test_inspect_daemon_stale_dead_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(4_294_967_000, "workstation.local"))

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "stale"
    assert "not live" in inspection.message


def test_inspect_daemon_reports_missing_metadata_stale_lock(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / lifecycle.LOCK_FILENAME).write_text("", encoding="utf-8")

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "stale"
    assert "without ownership metadata" in inspection.message


def test_inspect_daemon_reports_malformed_metadata_as_stale(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / lifecycle.LOCK_FILENAME).write_text("", encoding="utf-8")
    (run_root / lifecycle.LOCK_METADATA_FILENAME).write_text(
        "{not-json",
        encoding="utf-8",
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "stale"
    assert "failed to parse ownership metadata" in inspection.message


def test_inspect_daemon_live_pid_mismatched_executable_is_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(1234, "workstation.local"))
    monkeypatch.setattr(lifecycle, "_process_is_live", lambda _pid: True)
    monkeypatch.setattr(
        lifecycle,
        "_executable_matches_metadata",
        lambda _pid, _metadata: False,
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )

    assert inspection.state == "conflict"
    assert "executable does not match" in inspection.message


def test_stop_refuses_mismatched_host_without_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "this-host")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(1234, "other-host"))
    signals: list[tuple[int, int]] = []

    with pytest.raises(_DaemonLifecycleError, match="refusing to stop"):
        lifecycle._run_daemon_stop(  # noqa: SLF001
            _args(sase_home=str(tmp_path / "home"), run_root=str(run_root)),
            kill=lambda pid, sig: signals.append((pid, sig)),
            sleep=lambda _seconds: None,
        )

    assert signals == []


def test_stop_signals_matching_live_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOSTNAME", "this-host")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(1234, "this-host"))
    signals: list[tuple[int, int]] = []
    live_checks = iter([True, False])
    monkeypatch.setattr(
        lifecycle,
        "_process_is_live",
        lambda _pid: next(live_checks, False),
    )
    monkeypatch.setattr(
        lifecycle,
        "_executable_matches_metadata",
        lambda _pid, _metadata: True,
    )

    code = lifecycle._run_daemon_stop(  # noqa: SLF001
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root)),
        kill=lambda pid, sig: signals.append((pid, sig)),
        sleep=lambda _seconds: None,
    )

    assert code == 0
    assert signals == [(1234, lifecycle.signal.SIGTERM)]
    assert "Stopped SASE daemon pid 1234" in capsys.readouterr().out


def test_background_start_reports_metadata_without_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOSTNAME", "this-host")
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(1234, "this-host"))
    monkeypatch.setattr(lifecycle, "_process_is_live", lambda _pid: True)

    class FakeProcess:
        def poll(self) -> int | None:
            return None

    popen_calls: list[dict[str, Any]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> FakeProcess:
        popen_calls.append({"argv": argv, **kwargs})
        return FakeProcess()

    code = lifecycle._run_daemon_start(  # noqa: SLF001
        _args(
            sase_home=str(tmp_path / "home"),
            run_root=str(run_root),
            daemon_command="sase_gateway",
            disable_mobile_http=True,
            startup_timeout=1,
        ),
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )

    assert code == 0
    assert popen_calls[0]["argv"] == [
        "sase_gateway",
        "daemon",
        "--sase-home",
        str(tmp_path / "home"),
        "--run-root",
        str(run_root),
        "--disable-mobile-http",
    ]
    assert popen_calls[0]["start_new_session"] is True
    assert "RPC health is unavailable" in capsys.readouterr().out


def test_status_json_includes_log_path_and_metrics_endpoint(
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
                "details": {"metrics": {"endpoint": "http://127.0.0.1:7629/metrics"}}
            },
        },
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = lifecycle._inspection_to_dict(inspection)

    assert payload["log_path"] == str(run_root / "daemon.log")
    assert payload["projection_db_path"] == str(
        run_root / "projections" / "projection.sqlite"
    )
    assert payload["storage_layout"]["run_root"]["path_kind"] == "host_local_override"
    assert (
        str(run_root / "daemon.lock.json") in payload["storage_layout"]["runtime_files"]
    )
    assert payload["metrics_endpoint"] == "http://127.0.0.1:7629/metrics"
