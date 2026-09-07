"""Race-safe on-demand supervision of the local federation worker process."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._constants import FEDERATION_WORKER_COMMAND
from ._errors import FederationWorkerResponseError, FederationWorkerUnavailable
from ._hosts import FederationConfig
from ._ipc import FederationIpcClient
from ._settings import FederationWorkerSettings, resolve_timeout

IpcClientFactory = Callable[[Path, int], "FederationIpcClient"]
CommandResolver = Callable[[FederationWorkerSettings], tuple[str, ...]]
PopenFactory = Callable[..., subprocess.Popen[Any]]


def resolve_federation_worker_command(
    settings: FederationWorkerSettings | None = None,
) -> tuple[str, ...]:
    """Resolve the packaged worker command, then linked-core dev binaries."""

    settings = settings or FederationWorkerSettings()
    if settings.command:
        return settings.command
    packaged = shutil.which(FEDERATION_WORKER_COMMAND)
    if packaged:
        return (packaged,)

    repo_root = Path(__file__).resolve().parents[4]
    for target_root in (
        repo_root / "sase/repos/linked/sase-core/target",
        repo_root / "sase/repos/external/gh/sase-org/sase-core/target",
        repo_root.parent / "sase-core/target",
    ):
        for profile in ("debug", "release"):
            candidate = target_root / profile / FEDERATION_WORKER_COMMAND
            if candidate.is_file():
                return (str(candidate),)
    return ()


@dataclass
class FederationWorkerSupervisor:
    """Race-safe on-demand worker process supervisor."""

    config: FederationConfig
    command_resolver: CommandResolver = resolve_federation_worker_command
    client_factory: IpcClientFactory = lambda p, n: FederationIpcClient(p, n)
    popen: PopenFactory = subprocess.Popen
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _proc: subprocess.Popen[Any] | None = field(default=None, init=False)
    _configured: bool = field(default=False, init=False)

    def request(
        self,
        operation: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        timeout = resolve_timeout(
            timeout_seconds, self.config.worker.request_timeout_seconds
        )
        self.ensure_started(timeout)
        try:
            return self._send(operation, timeout)
        except FederationWorkerUnavailable:
            if not retry or operation.get("op") == "shutdown":
                raise
            with self._lock:
                self._configured = False
            self.ensure_started(timeout, force=True)
            return self._send(operation, timeout)

    def ensure_started(self, timeout_seconds: float, *, force: bool = False) -> None:
        if not force and self._healthy(timeout_seconds=0.2):
            self._ensure_configured(timeout_seconds)
            return
        with self._lock:
            if not force and self._healthy(timeout_seconds=0.2):
                self._ensure_configured(timeout_seconds)
                return
            command = self.command_resolver(self.config.worker)
            if not command:
                raise FederationWorkerUnavailable(
                    "federation worker command not found; install sase-core-rs or build "
                    "sase-core with `cargo build -p sase_gateway`"
                )
            argv = self._worker_argv(command)
            self._proc = self.popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
            )
            self._wait_for_health(timeout_seconds)
            self._ensure_configured(timeout_seconds)

    def _worker_argv(self, command: Sequence[str]) -> list[str]:
        settings = self.config.worker
        argv = [
            *command,
            "--sase-home",
            str(settings.sase_home),
            "--socket",
            str(settings.resolved_socket_path),
            "--idle-timeout-seconds",
            f"{settings.idle_timeout_seconds:g}",
            "--max-frame-bytes",
            str(settings.max_frame_bytes),
        ]
        if settings.run_root is not None:
            argv.extend(["--run-root", str(settings.run_root)])
        return argv

    def _wait_for_health(self, timeout_seconds: float) -> None:
        deadline = self.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while self.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise FederationWorkerUnavailable(
                    "federation worker exited before health check completed"
                )
            try:
                health = self._send({"op": "health"}, min(0.5, timeout_seconds))
                if health.get("status") == "ok":
                    return
            except (FederationWorkerUnavailable, FederationWorkerResponseError) as exc:
                last_error = exc
            self.sleep(0.05)
        suffix = f": {last_error}" if last_error else ""
        raise FederationWorkerUnavailable(
            f"federation worker did not become ready within {timeout_seconds:g}s{suffix}"
        )

    def _ensure_configured(self, timeout_seconds: float) -> None:
        with self._lock:
            if self._configured:
                return
            operation = {"op": "replace_config", "hosts": self.config.hosts_wire()}
            self._send(operation, timeout_seconds)
            self._configured = True

    def _healthy(self, *, timeout_seconds: float) -> bool:
        try:
            health = self._send({"op": "health"}, timeout_seconds)
        except (FederationWorkerUnavailable, FederationWorkerResponseError):
            return False
        return health.get("status") == "ok"

    def _send(
        self, operation: Mapping[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        client = self.client_factory(
            self.config.worker.resolved_socket_path,
            self.config.worker.max_frame_bytes,
        )
        return client.request(operation, timeout_seconds=timeout_seconds)
