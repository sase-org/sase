"""No-op stub classes matching the prometheus_client API surface used by sase.

When telemetry is disabled these stubs are used instead of real metric objects,
ensuring zero import cost and zero runtime overhead.
"""

from __future__ import annotations

from typing import Any


class StubCounter:
    """No-op replacement for ``prometheus_client.Counter``."""

    def inc(self, amount: float = 1) -> None:
        pass

    def labels(self, *args: Any, **kwargs: Any) -> StubCounter:
        return self


class StubGauge:
    """No-op replacement for ``prometheus_client.Gauge``."""

    def inc(self, amount: float = 1) -> None:
        pass

    def dec(self, amount: float = 1) -> None:
        pass

    def set(self, value: float) -> None:
        pass

    def labels(self, *args: Any, **kwargs: Any) -> StubGauge:
        return self


class StubHistogram:
    """No-op replacement for ``prometheus_client.Histogram``."""

    def observe(self, amount: float) -> None:
        pass

    def time(self) -> _StubTimer:
        return _StubTimer()

    def labels(self, *args: Any, **kwargs: Any) -> StubHistogram:
        return self


class _StubTimer:
    """No-op context manager returned by ``StubHistogram.time()``."""

    def __enter__(self) -> _StubTimer:
        return self

    def __exit__(self, *args: Any) -> None:
        pass
