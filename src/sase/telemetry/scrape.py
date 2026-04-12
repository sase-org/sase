"""HTTP client and Prometheus text exposition format parser.

Fetches and parses metrics from pushgateway or exposition endpoints.
"""

from __future__ import annotations

import json
import logging
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Matches: metric_name{label1="val1",label2="val2"} 42.0
# Also matches: metric_name 42.0  (no labels)
_SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?:\{(?P<labels>[^}]*)\})?"
    r"\s+(?P<value>\S+)"
    r"(?:\s+(?P<timestamp>\S+))?$"
)

_LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class MetricSample:
    """A single parsed metric sample from Prometheus text format."""

    name: str
    labels: dict[str, str] = field(default_factory=dict)
    value: float = 0.0
    metric_type: str = "untyped"


def scrape(url: str, timeout: float = 2.0) -> list[MetricSample]:
    """Fetch and parse Prometheus metrics from *url*.

    Returns an empty list if the endpoint is unreachable.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return []
    return _parse_prometheus_text(text)


def check_reachable(url: str, timeout: float = 2.0) -> bool:
    """Return True if *url* responds to an HTTP GET within *timeout*."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _parse_prometheus_text(text: str) -> list[MetricSample]:
    """Parse Prometheus text exposition format into MetricSample list."""
    samples: list[MetricSample] = []
    # Track TYPE declarations: metric_name -> type
    types: dict[str, str] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("# TYPE "):
            parts = line.split(None, 4)
            if len(parts) >= 4:
                types[parts[2]] = parts[3]
            continue

        if line.startswith("#"):
            continue

        match = _SAMPLE_RE.match(line)
        if not match:
            continue

        name = match.group("name")
        value_str = match.group("value")
        labels_str = match.group("labels") or ""

        labels = dict(_LABEL_RE.findall(labels_str))

        try:
            value = float(value_str)
        except ValueError:
            continue

        # Derive the base metric name for type lookup.
        # Histogram suffixes: _bucket, _count, _sum, _total
        base = _base_metric_name(name)
        metric_type = types.get(base, types.get(name, "untyped"))

        samples.append(
            MetricSample(
                name=name,
                labels=labels,
                value=value,
                metric_type=metric_type,
            )
        )

    return samples


def _base_metric_name(name: str) -> str:
    """Strip histogram/summary suffixes to find the base TYPE name."""
    for suffix in ("_bucket", "_count", "_sum", "_total", "_created"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def compute_percentiles(
    samples: list[MetricSample],
    quantiles: tuple[float, ...] = (0.50, 0.95, 0.99),
) -> dict[str, float]:
    """Compute approximate percentiles from histogram bucket samples.

    Returns a dict like ``{"p50": 1.23, "p95": 4.56, "p99": 9.01}``.
    Only works with histogram ``_bucket`` samples that share the same
    base name and label set (minus the ``le`` label).
    """
    # Collect (le_bound, cumulative_count) pairs.  When multiple pushgateway
    # groups contribute samples with the same ``le`` bound, sum them so the
    # resulting histogram represents all groups combined.
    bucket_sums: dict[float, float] = {}
    for s in samples:
        if not s.name.endswith("_bucket"):
            continue
        le = s.labels.get("le")
        if le is None:
            continue
        try:
            bound = float(le)
        except ValueError:
            continue
        bucket_sums[bound] = bucket_sums.get(bound, 0.0) + s.value

    if not bucket_sums:
        return {}

    buckets = sorted(bucket_sums.items(), key=lambda b: b[0])
    total = buckets[-1][1] if buckets else 0
    if total == 0:
        return {}

    result: dict[str, float] = {}
    for q in quantiles:
        target = q * total
        for bound, count in buckets:
            if count >= target:
                if math.isinf(bound):
                    # +Inf bucket — use previous finite bound if available
                    prev = [b for b, _ in buckets if not math.isinf(b)]
                    bound = prev[-1] if prev else 0.0
                label = f"p{int(q * 100)}"
                result[label] = bound
                break

    return result


def format_samples_as_json(samples: list[MetricSample]) -> str:
    """Serialize samples to a JSON string."""
    return json.dumps(
        [
            {
                "name": s.name,
                "labels": s.labels,
                "value": s.value,
                "type": s.metric_type,
            }
            for s in samples
        ],
        indent=2,
    )


def format_samples_as_prometheus(samples: list[MetricSample]) -> str:
    """Re-serialize samples to Prometheus text format."""
    lines: list[str] = []
    for s in samples:
        if s.labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in s.labels.items())
            lines.append(f"{s.name}{{{label_str}}} {s.value}")
        else:
            lines.append(f"{s.name} {s.value}")
    return "\n".join(lines)
