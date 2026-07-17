"""In-house metric registry and local-store flushing."""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from sase.telemetry._accumulators import (
    Counter,
    Gauge,
    Histogram,
    Metric,
    MetricRegistry,
)
from sase.telemetry._config import get_telemetry_config

log = logging.getLogger(__name__)

_initialized: bool = False
_initialized_pid: int | None = None
_registry: MetricRegistry | None = None
_source: str = ""
_flusher_thread: threading.Thread | None = None
_flusher_stop = threading.Event()
_exit_handlers: list[Any] = []
_FLUSH_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 0.05


def init_telemetry(*, start_flusher: bool = False, source: str | None = None) -> None:
    """Initialize the telemetry subsystem.

    Must be called once at process startup.  When telemetry is disabled this is
    a no-op and metric singletons remain as lightweight stubs.

    Args:
        start_flusher: Start the periodic flush thread used by long-lived
            daemons. Short-lived runners instead call
            :func:`register_flush_on_exit`.
        source: Stable source prefix for periodic gauge aggregation. The
            current process id is appended automatically.
    """
    global _initialized, _initialized_pid, _source
    pid = os.getpid()
    if _initialized and _initialized_pid == pid:
        if start_flusher:
            _start_flusher()
        return
    if _initialized_pid is not None and _initialized_pid != pid:
        _reset_after_fork()
    _initialized = True
    _initialized_pid = pid
    _source = _format_source(source or "process", None)

    config = get_telemetry_config()
    if not config.enabled:
        log.debug("Telemetry disabled — metrics remain as stubs")
        return

    _create_real_metrics()
    if start_flusher:
        _start_flusher()


def _create_real_metrics() -> None:
    """Replace stub singletons with in-house accumulators."""
    global _registry

    from sase.telemetry import metrics as m
    from sase.telemetry.metrics import METRIC_DEFS

    created: list[Metric] = []
    for attr, kind, name, doc, labelnames, extra in METRIC_DEFS:
        if kind == "counter":
            real: Metric = Counter(name, doc, labelnames)
        elif kind == "gauge":
            real = Gauge(name, doc, labelnames)
        else:
            real = Histogram(name, doc, labelnames, **extra)
        created.append(real)
        # Point the pre-existing stub at the real metric so modules that
        # imported the stub via ``from sase.telemetry.metrics import X``
        # before init_telemetry() still forward calls to the real object.
        stub = getattr(m, attr, None)
        if stub is not None:
            stub._real = real
        setattr(m, attr, real)

    _registry = MetricRegistry(created)
    log.info("Telemetry enabled — %d in-house metrics created", len(created))


def _start_flusher() -> None:
    """Start one daemon thread that periodically flushes local deltas."""
    global _flusher_thread
    if _registry is None or (_flusher_thread and _flusher_thread.is_alive()):
        return
    _flusher_stop.clear()
    _flusher_thread = threading.Thread(
        target=_flusher_loop,
        name="sase-telemetry-flusher",
        daemon=True,
    )
    _flusher_thread.start()
    log.debug("Started telemetry flusher thread")


def _flusher_loop() -> None:
    interval = max(0.1, get_telemetry_config().flush_interval_seconds)
    while not _flusher_stop.wait(interval):
        flush_metrics()


def flush_metrics(
    job: str | None = None,
    grouping_key: dict[str, str] | None = None,
) -> int:
    """Drain pending metrics and persist one batch to the local core store.

    Store failures are retried a bounded number of times, then dropped and
    logged at debug level. Telemetry must never disrupt the caller's work.
    Returns the number of recorded samples, or zero when disabled/empty/failed.
    """
    config = get_telemetry_config()
    if not config.enabled or _registry is None:
        return 0

    now_ts = int(time.time())
    source = _format_source(job, grouping_key) if job else _source
    samples = _registry.drain(ts=now_ts, source=source)
    if not samples:
        return 0
    batch = {
        "samples": samples,
        "now_ts": now_ts,
        "retention": config.retention.as_wire(),
    }

    for attempt in range(1, _FLUSH_ATTEMPTS + 1):
        try:
            from sase_core_rs import telemetry_record_batch  # type: ignore[import-untyped]

            result = telemetry_record_batch(
                str(config.resolved_store_path),
                batch,
                config.busy_timeout_ms,
            )
            recorded = int(result.get("samples_recorded", len(samples)))
            log.debug("Flushed %d telemetry samples (source=%s)", recorded, source)
            return recorded
        except Exception:
            if attempt < _FLUSH_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS * attempt)
                continue
            log.debug(
                "Dropped %d telemetry samples after %d flush attempts (source=%s)",
                len(samples),
                attempt,
                source,
                exc_info=True,
            )
    return 0


def register_flush_on_exit(
    job: str,
    **grouping_key: str,
) -> None:
    """Register an ``atexit`` handler that flushes local metrics.

    Intended for short- and medium-lived processes such as agent runners.
    """
    config = get_telemetry_config()
    if not config.enabled:
        return

    def _flush() -> None:
        flush_metrics(job, grouping_key or None)

    atexit.register(_flush)
    _exit_handlers.append(_flush)
    log.debug("Registered atexit telemetry flush (job=%s)", job)


def _format_source(job: str, grouping_key: dict[str, str] | None) -> str:
    parts = [job]
    parts.extend(
        f"{key}={value}" for key, value in sorted((grouping_key or {}).items())
    )
    parts.append(f"pid={os.getpid()}")
    return ":".join(parts)


def _reset_after_fork() -> None:
    """Discard inherited process-local registry/thread state after a fork."""
    _reset_for_tests()


def _reset_for_tests() -> None:
    """Reset module and metric state without leaving background threads."""
    global _initialized, _initialized_pid, _registry, _flusher_thread, _source
    _flusher_stop.set()
    if _flusher_thread and _flusher_thread.is_alive():
        _flusher_thread.join(timeout=1)
    for handler in _exit_handlers:
        atexit.unregister(handler)
    _exit_handlers.clear()
    _initialized = False
    _initialized_pid = None
    _registry = None
    _flusher_thread = None
    _source = ""
    from sase.telemetry.metrics import restore_metric_stubs

    restore_metric_stubs()


# Job names used by runner processes (for stale group cleanup).
_RUNNER_JOBS = frozenset(
    {
        "agent_runner",
        "mentor-runner",
        "fix-hook-runner",
        "summarize-hook-runner",
        "crs-runner",
    }
)

# Default maximum age (seconds) before a pushgateway group is considered stale.
_DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days


def cleanup_stale_groups(
    max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
) -> int:
    """Delete stale pushgateway groups whose ``instance`` timestamp is old.

    Returns the number of groups deleted.
    """
    config = get_telemetry_config()
    if not config.enabled:
        return 0

    gw_url = config.pushgateway_url.rstrip("/")
    # Ensure scheme is present.
    if not gw_url.startswith(("http://", "https://")):
        gw_url = f"http://{gw_url}"

    # Fetch all metric families from the pushgateway admin API.
    try:
        req = urllib.request.Request(f"{gw_url}/api/v1/metrics")
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        log.debug("Failed to fetch pushgateway metrics API", exc_info=True)
        return 0

    now = time.time()
    deleted = 0

    for group in data:
        labels = group.get("labels", {})
        job = labels.get("job", "")
        instance = labels.get("instance", "")

        if job not in _RUNNER_JOBS or not instance:
            continue

        # Instance value is a unix-style timestamp string.
        try:
            ts = float(instance)
        except (ValueError, TypeError):
            continue

        if now - ts < max_age_seconds:
            continue

        # Build the DELETE URL for this group.
        parts = [f"{gw_url}/metrics/job/{job}"]
        for k, v in sorted(labels.items()):
            if k == "job":
                continue
            parts.append(f"{k}/{v}")
        delete_url = "/".join(parts)

        try:
            dreq = urllib.request.Request(delete_url, method="DELETE")
            with urllib.request.urlopen(dreq, timeout=5):  # noqa: S310
                pass
            deleted += 1
            log.debug("Deleted stale pushgateway group: %s", delete_url)
        except (urllib.error.URLError, OSError, TimeoutError):
            log.debug(
                "Failed to delete pushgateway group: %s",
                delete_url,
                exc_info=True,
            )

    if deleted:
        log.info("Cleaned up %d stale pushgateway group(s)", deleted)

    return deleted
