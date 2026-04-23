"""No-op stub classes matching the prometheus_client API surface used by sase.

When telemetry is disabled these stubs are used instead of real metric objects,
ensuring zero import cost and zero runtime overhead.

When telemetry is enabled, ``_create_real_metrics()`` points each stub's
``_real`` attribute at the corresponding real prometheus_client object. This
way, modules that grabbed the metric via ``from sase.telemetry.metrics import
X`` at import time (before ``init_telemetry()`` ran) still reach the real
metric via delegation — the stub binding is no longer dead.
"""

from __future__ import annotations

from typing import Any


class StubCounter:
    """No-op replacement for ``prometheus_client.Counter``."""

    _real: Any = None

    def inc(self, amount: float = 1) -> None:
        if self._real is not None:
            self._real.inc(amount)

    def labels(self, *args: Any, **kwargs: Any) -> Any:
        if self._real is not None:
            return self._real.labels(*args, **kwargs)
        return self


class StubGauge:
    """No-op replacement for ``prometheus_client.Gauge``."""

    _real: Any = None

    def inc(self, amount: float = 1) -> None:
        if self._real is not None:
            self._real.inc(amount)

    def dec(self, amount: float = 1) -> None:
        if self._real is not None:
            self._real.dec(amount)

    def set(self, value: float) -> None:
        if self._real is not None:
            self._real.set(value)

    def labels(self, *args: Any, **kwargs: Any) -> Any:
        if self._real is not None:
            return self._real.labels(*args, **kwargs)
        return self


class StubHistogram:
    """No-op replacement for ``prometheus_client.Histogram``."""

    _real: Any = None

    def observe(self, amount: float) -> None:
        if self._real is not None:
            self._real.observe(amount)

    def time(self) -> Any:
        if self._real is not None:
            return self._real.time()
        return _StubTimer()

    def labels(self, *args: Any, **kwargs: Any) -> Any:
        if self._real is not None:
            return self._real.labels(*args, **kwargs)
        return self


class _StubTimer:
    """No-op context manager returned by ``StubHistogram.time()``."""

    def __enter__(self) -> _StubTimer:
        return self

    def __exit__(
        self,
        exc_type: Any = None,
        exc_val: Any = None,
        exc_tb: Any = None,
    ) -> None:
        del exc_type, exc_val, exc_tb
