"""Tests for telemetry stub classes."""

from sase.telemetry._stubs import StubCounter, StubGauge, StubHistogram


def test_stub_counter_inc_is_noop() -> None:
    c = StubCounter()
    c.inc()
    c.inc(5)


def test_stub_counter_labels_returns_self() -> None:
    c = StubCounter()
    labeled = c.labels(foo="bar")
    assert labeled is c


def test_stub_counter_chained_labels_inc() -> None:
    """labels().inc() works as a chained no-op."""
    c = StubCounter()
    c.labels(provider="claude").inc()


def test_stub_gauge_operations_are_noop() -> None:
    g = StubGauge()
    g.inc()
    g.inc(2)
    g.dec()
    g.dec(3)
    g.set(42)


def test_stub_gauge_labels_returns_self() -> None:
    g = StubGauge()
    labeled = g.labels(project="test")
    assert labeled is g


def test_stub_histogram_observe_is_noop() -> None:
    h = StubHistogram()
    h.observe(1.5)


def test_stub_histogram_labels_returns_self() -> None:
    h = StubHistogram()
    labeled = h.labels(provider="gemini")
    assert labeled is h


def test_stub_histogram_time_context_manager() -> None:
    h = StubHistogram()
    timer = h.time()
    with timer:
        pass
