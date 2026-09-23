"""Shared scaffolding for foreground service-host scenario tests.

Each scenario test drives the real ``_ServiceHost`` / ``ServiceHostLock``
code under a temporary ``SASE_HOME`` with cheap real children (``python -c``
sleepers and fail-fast exits). Config travels the real composition path
(``_compose_service_config`` over synthetic layers); only the layer-discovery
seam is stubbed. The platform lifecycle stays untouched: no test spawns
``sase service run`` or routes through the native unit.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.config.core import ConfigLayer
from sase.procs import (
    COMMAND_PROC_KIND,
    ProcReserve,
    ProcSupervisorClaim,
    claim_proc_supervisor,
    reserve_proc,
)
from sase.procs.service_meta import (
    SERVICE_ONESHOT_ORIGIN,
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_TRANSIENT,
    ProcServiceBlock,
)
from sase.service.config import ServiceConfigComposition, _compose_service_config
from sase.service.control import utc_timestamp
from sase.service.host import _ServiceHost
from sase.service.state import ServiceHostRecord, record_service_host

_SLEEPER = (sys.executable, "-c", "import time; time.sleep(30)")
_FAIL_FAST = (sys.executable, "-c", "import sys; sys.exit(1)")
_CLEAN_EXIT = (sys.executable, "-c", "import sys; sys.exit(0)")
_SLOW_FAIL = (
    sys.executable,
    "-c",
    "import time; time.sleep(1.5); sys.exit(1)",
)


def _layer_spec(
    argv: tuple[str, ...],
    *,
    restart: str = "on-failure",
    stop_signal: str = "SIGTERM",
    stop_timeout: float = 0.5,
    enabled: bool = True,
) -> dict[str, object]:
    return {
        "command": [str(part) for part in argv],
        "enabled": enabled,
        "restart": restart,
        "stop_signal": stop_signal,
        "stop_timeout": stop_timeout,
    }


def _compose(procs: dict[str, dict[str, object]]) -> ServiceConfigComposition:
    layer = ConfigLayer(
        name="user",
        path="/home/u/sase.yml",
        exists=True,
        list_strategy="concatenate",
        data={"service": {"procs": dict(procs)}},
    )
    return _compose_service_config([layer])


def _wait_for(predicate: Callable[[], bool], *, timeout: float = 15.0) -> bool:
    """Poll *predicate* until it holds or *timeout* expires."""
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)  # sase-test-wait: poll for child exit or proc-store state


@contextmanager
def _service_host(
    monkeypatch: pytest.MonkeyPatch,
    get_config: Callable[[], ServiceConfigComposition],
) -> Iterator[_ServiceHost]:
    """Yield a real host with stubbed config discovery; stop children on exit."""
    monkeypatch.setattr("sase.service.host_state.load_service_config", get_config)
    host = _ServiceHost()
    try:
        yield host
    finally:
        host._stop_all_children()


@contextmanager
def _preserved_host_globals() -> Iterator[None]:
    """Save and restore the process-global state ``run_host`` rewrites."""
    import sase.config.core as config_core

    saved_term = signal.getsignal(signal.SIGTERM)
    saved_int = signal.getsignal(signal.SIGINT)
    saved_usr1 = (
        signal.getsignal(signal.SIGUSR1) if hasattr(signal, "SIGUSR1") else None
    )
    saved_local = config_core._include_local_config
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, saved_term)
        signal.signal(signal.SIGINT, saved_int)
        if saved_usr1 is not None:
            signal.signal(signal.SIGUSR1, saved_usr1)
        from sase.config.core import set_include_local_config

        set_include_local_config(saved_local)


def _child_exited(host: _ServiceHost, name: str) -> bool:
    running = host._children.get(name)
    return running is not None and running.process.poll() is not None


def _stub_host_spawn(monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]) -> None:
    """Stub the ``sase service run`` exec: record the spawn, publish a heartbeat."""
    # These scenarios drive the real detached fallback, so they opt into the
    # isolated lifecycle override that the pytest guard otherwise blocks.
    monkeypatch.setenv("SASE_SERVICE_ALLOW_LIFECYCLE_IN_TESTS", "1")

    def _fake_popen(argv: object, **kwargs: object) -> object:
        spawned.append([str(part) for part in argv])  # type: ignore[union-attr]
        now = time.time()
        record_service_host(
            ServiceHostRecord(
                pid=os.getpid(),
                started_at=now,
                heartbeat_at=now,
                mode="foreground",
            )
        )

        class _FakeChild:
            pid = os.getpid()

        return _FakeChild()

    monkeypatch.setattr(
        "sase.service.control._native_lifecycle_action", lambda _action: None
    )
    # Popen is looked up as an attribute of the shared subprocess module, so
    # the monkeypatch window must not overlap any real child spawn.
    monkeypatch.setattr("sase.service.control.subprocess.Popen", _fake_popen)


def _reaped_pid() -> int:
    """Return a pid that has exited and been reaped (stale by construction)."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    assert not is_process_running(child.pid)
    return child.pid


def _reserve_oneshot_row(
    proc_id: str, tmp_path: Path, *, created_at: str | None = None
) -> str:
    return reserve_proc(
        ProcReserve(
            proc_id=proc_id,
            label=f"oneshot: {proc_id}",
            argv=["sh", "-c", "echo hi"],
            cwd=str(tmp_path),
            created_at=utc_timestamp() if created_at is None else created_at,
            log_path=str(tmp_path / f"{proc_id}.log"),
            request_fingerprint=f"fp-{proc_id}",
            reserved_by="pytest-host-scenarios",
            kind=COMMAND_PROC_KIND,
            origin=SERVICE_ONESHOT_ORIGIN,
            service=ProcServiceBlock(
                name=None,
                mode=SERVICE_PROC_MODE_ONESHOT,
                source=SERVICE_PROC_SOURCE_TRANSIENT,
            ),
        )
    ).proc.proc_id


def _claim_row(
    proc_id: str, *, supervisor_id: str, pid: int | None, pgid: int | None = None
) -> None:
    claim_proc_supervisor(
        ProcSupervisorClaim(
            proc_id=proc_id,
            supervisor_id=supervisor_id,
            claimed_at=utc_timestamp(),
            pid=pid,
            pgid=pgid,
        )
    )
