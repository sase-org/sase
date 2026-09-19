"""Host load samples for a live ToolRun.

Sampling shares the executor wait loop: one observation at start, then
approximately every 10 seconds, then once at finish. Collection or write
failures never change child behavior. Missing PSI/loadavg stay null with an
availability diagnostic — never zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import platform
import secrets
import time
from typing import Any

from sase.core.tool_run import tool_run_append_event

SAMPLE_INTERVAL_SECONDS = 10.0
_PSI_KINDS = ("cpu", "memory", "io")


def _collect_load_sample(
    *,
    run_id: str,
    elapsed_ms: int | None,
    sample_id: str | None = None,
    observed_ts: int | None = None,
) -> dict[str, Any]:
    """Collect one load sample. Unsupported fields stay null."""

    availability: list[str] = []
    diagnostics: list[str] = []
    loadavg_1 = loadavg_5 = loadavg_15 = None
    try:
        load_1, load_5, load_15 = _getloadavg()
        loadavg_1, loadavg_5, loadavg_15 = float(load_1), float(load_5), float(load_15)
    except (OSError, AttributeError):
        availability.append("loadavg unavailable")
    logical_cpus = _cpu_count()
    psi = _read_psi()
    if psi is None:
        availability.append("PSI unavailable on this host")
        psi_cpu = psi_memory = psi_io = None
    else:
        psi_cpu, psi_memory, psi_io = psi
        if psi_cpu is None and psi_memory is None and psi_io is None:
            availability.append("PSI unavailable on this host")
    sample = {
        "schema_version": 1,
        "sample_id": sample_id or secrets.token_hex(16),
        "run_id": run_id,
        "attempt": 1,
        "observed_ts": int(observed_ts if observed_ts is not None else time.time()),
        "elapsed_ms": elapsed_ms,
        "loadavg_1": loadavg_1,
        "loadavg_5": loadavg_5,
        "loadavg_15": loadavg_15,
        "logical_cpus": logical_cpus,
        "psi_cpu_some": psi_cpu,
        "psi_memory_some": psi_memory,
        "psi_io_some": psi_io,
        "host_identity": platform.node() or None,
        "availability": availability,
        "diagnostics": diagnostics,
    }
    return sample


def _append_load_sample(sample: Mapping[str, Any]) -> bool:
    """Persist one sample event. Returns False on recording failure."""

    run_id = str(sample.get("run_id") or "")
    if not run_id:
        return False
    observed_ts = sample.get("observed_ts")
    created_ts = int(observed_ts) if isinstance(observed_ts, int) else int(time.time())
    try:
        tool_run_append_event(
            {
                "schema_version": 1,
                "event": {
                    "schema_version": 1,
                    "event_id": secrets.token_hex(16),
                    "run_id": run_id,
                    "attempt": 1,
                    "kind": "sample",
                    "created_ts": created_ts,
                    "sample": dict(sample),
                },
            }
        )
    except Exception:  # noqa: BLE001 - sampling cannot change the child.
        return False
    return True


def _getloadavg() -> tuple[float, float, float]:
    import os

    return os.getloadavg()


def _cpu_count() -> int | None:
    import os

    count = os.cpu_count()
    return int(count) if count else None


def _read_psi() -> tuple[float | None, float | None, float | None] | None:
    values: list[float | None] = []
    any_file = False
    for kind in _PSI_KINDS:
        path = Path(f"/proc/pressure/{kind}")
        if not path.is_file():
            values.append(None)
            continue
        any_file = True
        values.append(_psi_some_avg10(path))
    if not any_file:
        return None
    return values[0], values[1], values[2]


def _psi_some_avg10(path: Path) -> float | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if not line.startswith("some "):
            continue
        for part in line.split():
            if part.startswith("avg10="):
                try:
                    return float(part.split("=", 1)[1])
                except ValueError:
                    return None
    return None


@dataclass
class LoadSampler:
    """Executor-owned sampler that stops at settlement."""

    run_id: str
    started: float
    interval: float = SAMPLE_INTERVAL_SECONDS
    last_monotonic: float | None = None
    samples: list[dict[str, Any]] = field(default_factory=list)
    stopped: bool = False
    write_failures: int = 0

    def elapsed_ms(self) -> int:
        return max(0, int((time.monotonic() - self.started) * 1000))

    def maybe_sample(self, *, force: bool = False) -> dict[str, Any] | None:
        if self.stopped:
            return None
        now = time.monotonic()
        if (
            not force
            and self.last_monotonic is not None
            and now - self.last_monotonic < self.interval
        ):
            return None
        sample = _collect_load_sample(run_id=self.run_id, elapsed_ms=self.elapsed_ms())
        self.last_monotonic = now
        if _append_load_sample(sample):
            self.samples.append(sample)
        else:
            self.write_failures += 1
        return sample

    def stop(self) -> None:
        self.stopped = True


__all__ = [
    "SAMPLE_INTERVAL_SECONDS",
    "LoadSampler",
]
