"""Registry management, HTTP exposition, and Push Gateway helpers."""

from __future__ import annotations

import atexit
import logging
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
