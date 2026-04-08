"""Lightweight Prometheus HTTP API client for range and instant queries.

Uses stdlib ``urllib.request`` for consistency with ``scrape.py``.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimeSeries:
    """A single time series returned by a Prometheus query."""

    metric: str
    labels: dict[str, str] = field(default_factory=dict)
    points: list[tuple[float, float]] = field(default_factory=list)


def check_prometheus_reachable(base_url: str, timeout: float = 2.0) -> bool:
    """Return True if the Prometheus API at *base_url* is reachable."""
    url = f"{base_url}/-/ready"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def query_range(
    base_url: str,
    query: str,
    start: float,
    end: float,
    step: str = "15s",
    timeout: float = 5.0,
) -> list[TimeSeries]:
    """Execute a Prometheus range query and return parsed time series.

    Parameters
    ----------
    base_url:
        Prometheus base URL, e.g. ``http://localhost:9090``.
    query:
        PromQL expression.
    start, end:
        Unix timestamps for the query window.
    step:
        Query resolution step (default ``15s``).
    timeout:
        HTTP timeout in seconds.
    """
    params = urllib.parse.urlencode(
        {"query": query, "start": start, "end": end, "step": step}
    )
    url = f"{base_url}/api/v1/query_range?{params}"
    return _fetch_and_parse(url, timeout)


def _fetch_and_parse(url: str, timeout: float) -> list[TimeSeries]:
    """Fetch a Prometheus API URL and parse the JSON response."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        log.debug("Prometheus query failed: %s", exc)
        return []

    if body.get("status") != "success":
        log.debug("Prometheus query returned non-success: %s", body.get("status"))
        return []

    data = body.get("data", {})
    result_type = data.get("resultType", "")
    results = data.get("result", [])

    series: list[TimeSeries] = []
    for r in results:
        metric_labels: dict[str, str] = r.get("metric", {})
        metric_name = metric_labels.pop("__name__", "")

        if result_type == "matrix":
            points = [(float(ts), float(val)) for ts, val in r.get("values", [])]
        elif result_type == "vector":
            pair = r.get("value", [])
            points = [(float(pair[0]), float(pair[1]))] if len(pair) == 2 else []
        else:
            points = []

        series.append(
            TimeSeries(metric=metric_name, labels=metric_labels, points=points)
        )

    return series
