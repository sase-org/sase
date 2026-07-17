"""Thread-safe in-process telemetry accumulators.

The public metric surface intentionally mirrors the small subset of the
instrumentation API used by SASE. Accumulators retain only data that has
not yet been flushed: counters and histograms drain deltas, while gauges emit
their latest value on every flush so live processes do not become stale.
"""

from __future__ import annotations

import math
import threading
import time
from contextlib import ContextDecorator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Self

MetricKind = Literal["counter", "gauge", "histogram"]
_LabelKey = tuple[str, ...]

_DEFAULT_HISTOGRAM_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
)


class Metric(Protocol):
    """Common accumulator operations used by :class:`MetricRegistry`."""

    name: str
    kind: MetricKind

    def drain(self, *, ts: int, source: str) -> list[dict[str, Any]]: ...

    def get_sample_value(self, name: str, labels: dict[str, str]) -> float | None: ...


class _BaseMetric:
    """Label validation and wire-sample helpers shared by all metric kinds."""

    kind: MetricKind

    def __init__(self, name: str, documentation: str, labelnames: list[str]) -> None:
        self.name = name
        self._name = name
        self.documentation = documentation
        self.labelnames = tuple(labelnames)
        self._lock = threading.Lock()

    def _label_key(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> _LabelKey:
        if args and kwargs:
            raise ValueError("labels cannot be supplied as both args and kwargs")
        if args:
            if len(args) != len(self.labelnames):
                raise ValueError(
                    f"incorrect label count for {self.name}: expected "
                    f"{len(self.labelnames)}, got {len(args)}"
                )
            return tuple(str(value) for value in args)

        unknown = set(kwargs) - set(self.labelnames)
        missing = set(self.labelnames) - set(kwargs)
        if unknown or missing:
            details: list[str] = []
            if missing:
                details.append(f"missing {sorted(missing)!r}")
            if unknown:
                details.append(f"unexpected {sorted(unknown)!r}")
            raise ValueError(f"incorrect labels for {self.name}: {', '.join(details)}")
        return tuple(str(kwargs[name]) for name in self.labelnames)

    def _labels_dict(self, key: _LabelKey) -> dict[str, str]:
        return dict(zip(self.labelnames, key, strict=True))

    def _wire_sample(
        self, *, key: _LabelKey, ts: int, source: str, **values: Any
    ) -> dict[str, Any]:
        return {
            "ts": ts,
            "metric": self.name,
            "kind": self.kind,
            "labels": self._labels_dict(key),
            "source": source,
            **values,
        }


def _finite(value: float, *, operation: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{operation} value must be finite")
    return value


class Counter(_BaseMetric):
    """Monotonic counter whose flushes contain deltas."""

    kind: MetricKind = "counter"

    def __init__(self, name: str, documentation: str, labelnames: list[str]) -> None:
        super().__init__(name, documentation, labelnames)
        self._values: dict[_LabelKey, float] = {}

    def labels(self, *args: Any, **kwargs: Any) -> _CounterChild:
        return _CounterChild(self, self._label_key(args, kwargs))

    def inc(self, amount: float = 1) -> None:
        self._inc((), amount)

    def _inc(self, key: _LabelKey, amount: float) -> None:
        amount = _finite(amount, operation="counter increment")
        if amount < 0:
            raise ValueError("counter increment must be non-negative")
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def drain(self, *, ts: int, source: str) -> list[dict[str, Any]]:
        with self._lock:
            deltas = self._values
            self._values = {}
        return [
            self._wire_sample(key=key, ts=ts, source=source, value=value)
            for key, value in deltas.items()
            if value != 0
        ]

    def get_sample_value(self, name: str, labels: dict[str, str]) -> float | None:
        if name != self.name:
            return None
        key = tuple(labels.get(label, "") for label in self.labelnames)
        if set(labels) != set(self.labelnames):
            return None
        with self._lock:
            return self._values.get(key)


@dataclass(frozen=True)
class _CounterChild:
    metric: Counter
    key: _LabelKey

    def inc(self, amount: float = 1) -> None:
        self.metric._inc(self.key, amount)


class Gauge(_BaseMetric):
    """Gauge that emits the latest value for every known label set."""

    kind: MetricKind = "gauge"

    def __init__(self, name: str, documentation: str, labelnames: list[str]) -> None:
        super().__init__(name, documentation, labelnames)
        self._values: dict[_LabelKey, float] = {}

    def labels(self, *args: Any, **kwargs: Any) -> _GaugeChild:
        return _GaugeChild(self, self._label_key(args, kwargs))

    def inc(self, amount: float = 1) -> None:
        self._inc((), amount)

    def dec(self, amount: float = 1) -> None:
        self._inc((), -_finite(amount, operation="gauge decrement"))

    def set(self, value: float) -> None:
        self._set((), value)

    def _inc(self, key: _LabelKey, amount: float) -> None:
        amount = _finite(amount, operation="gauge increment")
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def _set(self, key: _LabelKey, value: float) -> None:
        value = _finite(value, operation="gauge set")
        with self._lock:
            self._values[key] = value

    def drain(self, *, ts: int, source: str) -> list[dict[str, Any]]:
        with self._lock:
            values = tuple(self._values.items())
        return [
            self._wire_sample(key=key, ts=ts, source=source, value=value)
            for key, value in values
        ]

    def get_sample_value(self, name: str, labels: dict[str, str]) -> float | None:
        if name != self.name:
            return None
        key = tuple(labels.get(label, "") for label in self.labelnames)
        if set(labels) != set(self.labelnames):
            return None
        with self._lock:
            return self._values.get(key)


@dataclass(frozen=True)
class _GaugeChild:
    metric: Gauge
    key: _LabelKey

    def inc(self, amount: float = 1) -> None:
        self.metric._inc(self.key, amount)

    def dec(self, amount: float = 1) -> None:
        self.metric._inc(self.key, -_finite(amount, operation="gauge decrement"))

    def set(self, value: float) -> None:
        self.metric._set(self.key, value)


@dataclass
class _HistogramState:
    count: int = 0
    sum: float = 0.0
    min: float | None = None
    max: float | None = None
    buckets: list[int] = field(default_factory=list)


class Histogram(_BaseMetric):
    """Histogram whose aggregate and cumulative bucket values drain as deltas."""

    kind: MetricKind = "histogram"

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: list[str],
        *,
        buckets: list[float] | tuple[float, ...] = _DEFAULT_HISTOGRAM_BUCKETS,
    ) -> None:
        super().__init__(name, documentation, labelnames)
        checked = tuple(
            _finite(bound, operation="histogram bucket") for bound in buckets
        )
        if not checked or tuple(sorted(set(checked))) != checked:
            raise ValueError("histogram buckets must be unique and increasing")
        self.buckets = checked
        self._values: dict[_LabelKey, _HistogramState] = {}

    def labels(self, *args: Any, **kwargs: Any) -> _HistogramChild:
        return _HistogramChild(self, self._label_key(args, kwargs))

    def observe(self, amount: float) -> None:
        self._observe((), amount)

    def time(self) -> _Timer:
        return _Timer(self, ())

    def _observe(self, key: _LabelKey, amount: float) -> None:
        amount = _finite(amount, operation="histogram observation")
        with self._lock:
            state = self._values.get(key)
            if state is None:
                state = _HistogramState(buckets=[0] * len(self.buckets))
                self._values[key] = state
            state.count += 1
            state.sum += amount
            state.min = amount if state.min is None else min(state.min, amount)
            state.max = amount if state.max is None else max(state.max, amount)
            for index, upper_bound in enumerate(self.buckets):
                if amount <= upper_bound:
                    state.buckets[index] += 1

    def drain(self, *, ts: int, source: str) -> list[dict[str, Any]]:
        with self._lock:
            deltas = self._values
            self._values = {}
        return [
            self._wire_sample(
                key=key,
                ts=ts,
                source=source,
                count=state.count,
                sum=state.sum,
                min=state.min,
                max=state.max,
                buckets=[
                    {"le": upper_bound, "count": count}
                    for upper_bound, count in zip(
                        self.buckets, state.buckets, strict=True
                    )
                ],
            )
            for key, state in deltas.items()
            if state.count
        ]

    def get_sample_value(self, name: str, labels: dict[str, str]) -> float | None:
        suffix = next(
            (
                suffix
                for suffix in ("_count", "_sum", "_bucket")
                if name == self.name + suffix
            ),
            None,
        )
        if suffix is None:
            return None
        sample_labels = dict(labels)
        le = sample_labels.pop("le", None)
        key = tuple(sample_labels.get(label, "") for label in self.labelnames)
        if set(sample_labels) != set(self.labelnames):
            return None
        with self._lock:
            state = self._values.get(key)
            if state is None:
                return None
            if suffix == "_count":
                return float(state.count)
            if suffix == "_sum":
                return state.sum
            if le is None:
                return None
            if le == "+Inf":
                return float(state.count)
            try:
                index = self.buckets.index(float(le))
            except (ValueError, TypeError):
                return None
            return float(state.buckets[index])


@dataclass(frozen=True)
class _HistogramChild:
    metric: Histogram
    key: _LabelKey

    def observe(self, amount: float) -> None:
        self.metric._observe(self.key, amount)

    def time(self) -> _Timer:
        return _Timer(self.metric, self.key)


class _Timer(ContextDecorator):
    """Context manager/decorator that records elapsed monotonic time."""

    def __init__(self, metric: Histogram, key: _LabelKey) -> None:
        self._metric = metric
        self._key = key
        self._started: float | None = None

    def __enter__(self) -> Self:
        self._started = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: object = None,
        exc_value: object = None,
        traceback: object = None,
    ) -> None:
        del exc_type, exc_value, traceback
        if self._started is not None:
            self._metric._observe(self._key, time.perf_counter() - self._started)


class MetricRegistry:
    """Collection of in-house accumulators created from ``METRIC_DEFS``."""

    def __init__(self, metrics: list[Metric]) -> None:
        self.metrics = tuple(metrics)

    def drain(self, *, ts: int, source: str) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for metric in self.metrics:
            samples.extend(metric.drain(ts=ts, source=source))
        return samples

    def get_sample_value(
        self, name: str, labels: dict[str, str] | None = None
    ) -> float | None:
        """Return one unflushed value (primarily for instrumentation tests)."""
        for metric in self.metrics:
            value = metric.get_sample_value(name, labels or {})
            if value is not None:
                return value
        return None
