"""Registry management, HTTP exposition, and Push Gateway helpers."""

from __future__ import annotations

import atexit
import json
import logging
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from sase.telemetry._config import get_telemetry_config

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry

log = logging.getLogger(__name__)

_initialized: bool = False
# Dedicated CollectorRegistry so tests (and multi-init scenarios) don't collide
# with the global default registry.
_registry: CollectorRegistry | None = None


def init_telemetry(*, start_http_server: bool = False) -> None:
    """Initialize the telemetry subsystem.

    Must be called once at process startup.  When telemetry is disabled (the
    default) this is a no-op — metric singletons remain as lightweight stubs.

    Args:
        start_http_server: If ``True`` **and** telemetry is enabled, start a
            Prometheus HTTP exposition server on the configured port.  Intended
            for long-lived processes such as the axe orchestrator.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    config = get_telemetry_config()
    if not config.enabled:
        log.debug("Telemetry disabled — metrics remain as stubs")
        return

    _create_real_metrics()

    if start_http_server:
        _start_http_server(config.exposition_port)


def _create_real_metrics() -> None:
    """Replace stub singletons in ``metrics`` with real prometheus_client objects."""
    global _registry

    import prometheus_client  # only imported when enabled

    from sase.telemetry import metrics as m
    from sase.telemetry.metrics import METRIC_DEFS

    reg = prometheus_client.CollectorRegistry()
    _registry = reg

    factory = {
        "counter": prometheus_client.Counter,
        "gauge": prometheus_client.Gauge,
        "histogram": prometheus_client.Histogram,
    }

    for attr, kind, name, doc, labelnames, extra in METRIC_DEFS:
        cls = factory[kind]
        metric = cls(name, doc, labelnames=labelnames, registry=reg, **extra)
        setattr(m, attr, metric)

    log.info("Telemetry enabled — %d real metrics created", len(METRIC_DEFS))


def _start_http_server(port: int) -> None:
    """Start the Prometheus HTTP exposition server."""
    if _registry is None:
        return
    try:
        import prometheus_client

        prometheus_client.start_http_server(port, registry=_registry)
        log.info("Prometheus HTTP server started on port %d", port)
    except Exception:
        log.exception("Failed to start Prometheus HTTP server on port %d", port)


def push_metrics(
    job: str,
    grouping_key: dict[str, str] | None = None,
) -> None:
    """Push metrics to the configured Prometheus Push Gateway.

    Uses ``pushadd_to_gateway`` (POST/merge) with the dedicated
    ``CollectorRegistry`` so it never replaces metrics from other jobs.

    Silently catches all exceptions — a downed pushgateway must never crash
    the caller.
    """
    config = get_telemetry_config()
    if not config.enabled or _registry is None:
        return

    try:
        from prometheus_client import pushadd_to_gateway

        pushadd_to_gateway(
            config.pushgateway_url,
            job=job,
            registry=_registry,
            grouping_key=grouping_key or {},
        )
        log.debug("Metrics pushed to %s (job=%s)", config.pushgateway_url, job)
    except Exception:
        log.debug(
            "Failed to push metrics to %s (job=%s)",
            config.pushgateway_url,
            job,
            exc_info=True,
        )


def register_push_on_exit(
    job: str,
    **grouping_key: str,
) -> None:
    """Register an ``atexit`` handler that pushes metrics on process exit.

    Intended for medium-lived processes like agent runners.
    """
    config = get_telemetry_config()
    if not config.enabled:
        return

    def _push() -> None:
        push_metrics(job, grouping_key or None)

    atexit.register(_push)
    log.debug("Registered atexit push (job=%s)", job)


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
