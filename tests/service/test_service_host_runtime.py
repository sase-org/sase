"""Focused runtime tests for the Python service host."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from sase.procs import read_procs
from sase.procs.service_meta import SERVICE_PROC_MODE_DAEMON
from sase.service.config import (
    ServiceConfigComposition,
    ServiceEnablementSource,
    ServiceLauncher,
    ServiceProcConfig,
)
from sase.service.host import _ServiceHost
from sase.service.paths import service_proc_output_log_path
from sase.service.state import read_service_state


def test_service_host_launches_direct_child_and_settles_durable_row(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    entry = ServiceProcConfig(
        name="demo",
        available=True,
        source="user",
        declared_by="pytest",
        enabled=True,
        enablement=ServiceEnablementSource(explicit=True, layer="pytest"),
        mode="daemon",
        restart="on-failure",
        stop_signal="SIGTERM",
        stop_timeout_seconds=1.0,
        log_max_bytes=1024,
        launcher=ServiceLauncher(
            kind="command",
            command=[sys.executable, "-c", "print('service child', flush=True)"],
            argv=(sys.executable, "-c", "print('service child', flush=True)"),
        ),
        success_exit_codes=(0,),
    )
    config = ServiceConfigComposition(
        schema_version=1,
        fatal=False,
        procs=(entry,),
        diagnostics=(),
        ignored_layers=(),
    )
    host = _ServiceHost()

    host._launch(entry, history=None)
    running = host._children["demo"]
    running.process.wait(timeout=10)
    host._observe_exits(config, read_service_state())

    rows = read_procs()
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "success"
    assert row.service is not None
    assert row.service.name == "demo"
    assert row.service.mode == SERVICE_PROC_MODE_DAEMON
    assert row.service.source == "user"
    assert "demo" not in host._children
    assert "demo" not in host._pending

    log_path = service_proc_output_log_path("demo")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and (
        not log_path.exists() or "service child" not in log_path.read_text()
    ):
        time.sleep(0.05)  # sase-test-wait: background output pump flushes log
    assert "service child" in log_path.read_text(encoding="utf-8")
