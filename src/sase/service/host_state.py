"""Runtime records and reconcile tick for the foreground service host."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

from sase.service.boot import current_boot_id
from sase.service.config import ServiceConfigComposition
from sase.service.config import load_service_config
from sase.service.host_lifecycle import run_host
from sase.service.host_models import GivenUp as _GivenUp
from sase.service.host_models import PendingRestart as _PendingRestart
from sase.service.host_models import RunningProc as _RunningProc
from sase.service.host_reporting import (
    empty_service_config,
    write_current_host_status,
)
from sase.service.host_support import package_version as _package_version
from sase.service.restart import ServiceRestartDecision, ServiceRestartHistory
from sase.service.state import (
    ServiceHostRecord,
    ServiceStateSnapshot,
    read_service_state,
    record_service_host,
)
from sase.service.status import ServiceProcLastExit

_RECONCILE_SECONDS = 1.0


class ServiceHostStateMixin:
    """Own the host's runtime records and drive the reconcile tick."""

    def __init__(self) -> None:
        self._running = True
        self._nudge = threading.Event()
        self._children: dict[str, _RunningProc] = {}
        self._pending: dict[str, _PendingRestart] = {}
        self._last_exits: dict[str, ServiceProcLastExit] = {}
        self._restart_history: dict[str, ServiceRestartHistory] = {}
        self._restart_decisions: dict[str, ServiceRestartDecision] = {}
        self._restart_counts: dict[str, int] = {}
        self._boot_id = current_boot_id()
        self._started_at = time.time()
        self._unit = os.environ.get("SASE_SERVICE_UNIT") or None
        self._warned_service_marker_dropped = False
        self._last_good_config: ServiceConfigComposition | None = None
        self._config_error: str | None = None
        self._given_up: dict[str, _GivenUp] = {}
        self._notify_episodes: dict[str, int] = {}

    def run(self: Any) -> int:
        """Run the foreground host until SIGTERM, SIGINT, or KeyboardInterrupt."""
        return run_host(self, _RECONCILE_SECONDS)

    def _record_heartbeat(self: Any, *, error: str | None = None) -> None:
        record_service_host(
            ServiceHostRecord(
                pid=os.getpid(),
                boot_id=self._boot_id,
                started_at=self._started_at,
                heartbeat_at=time.time(),
                mode="foreground",
                unit=self._unit,
                sase_version=_package_version(),
                error=error,
            )
        )

    def _reconcile_once(self: Any) -> None:
        heartbeat_error: str | None = None
        config: ServiceConfigComposition | None
        try:
            try:
                config = load_service_config()
                self._last_good_config = config
                self._config_error = None
            except Exception as exc:  # noqa: BLE001 - degraded host keeps supervising.
                heartbeat_error = str(exc)
                self._config_error = heartbeat_error
                config = self._last_good_config
                print(
                    f"sase service host config error: {exc} "
                    "— supervising last-known-good config",
                    file=sys.stderr,
                )
            try:
                state = read_service_state()
            except Exception as exc:  # noqa: BLE001 - host must keep heartbeating.
                if heartbeat_error is None:
                    heartbeat_error = str(exc)
                print(f"sase service host reconcile error: {exc}", file=sys.stderr)
                return
            if config is None:
                try:
                    self._observe_exits(None, state)
                    write_current_host_status(
                        self,
                        empty_service_config(),
                        state,
                        config_error=heartbeat_error,
                    )
                except Exception as exc:  # noqa: BLE001 - host must keep running.
                    if heartbeat_error is None:
                        heartbeat_error = str(exc)
                    print(f"sase service host reconcile error: {exc}", file=sys.stderr)
                return
            try:
                self._observe_exits(config, state)
                self._reconcile_desired(config, state)
                write_current_host_status(
                    self, config, state, config_error=heartbeat_error
                )
            except Exception as exc:  # noqa: BLE001 - host must keep running.
                if heartbeat_error is None:
                    heartbeat_error = str(exc)
                try:
                    write_current_host_status(
                        self, config, state, config_error=heartbeat_error
                    )
                except Exception:
                    pass
                print(f"sase service host reconcile error: {exc}", file=sys.stderr)
        finally:
            try:
                self._record_heartbeat(error=heartbeat_error)
            except Exception:  # noqa: BLE001 - heartbeat must not kill the host.
                pass

    def _observe_exits(
        self: Any,
        config: ServiceConfigComposition | None,
        state: ServiceStateSnapshot,
    ) -> None:
        for name, running in list(self._children.items()):
            return_code = running.process.poll()
            if return_code is None:
                continue
            self._settle_exit(name, running, return_code, config=config, state=state)
            del self._children[name]
