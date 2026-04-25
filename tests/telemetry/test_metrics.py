"""Tests for telemetry metric definitions."""

from sase.telemetry._stubs import StubCounter, StubGauge, StubHistogram
from sase.telemetry.metrics import METRIC_DEFS


def test_all_metric_defs_have_valid_kind() -> None:
    valid_kinds = {"counter", "gauge", "histogram"}
    for attr, kind, name, doc, labels, extra in METRIC_DEFS:
        assert kind in valid_kinds, f"{attr}: invalid kind {kind!r}"


def test_all_metric_names_follow_convention() -> None:
    """All metric names must start with 'sase_'."""
    for attr, _, name, _, _, _ in METRIC_DEFS:
        assert name.startswith("sase_"), (
            f"{attr}: name {name!r} must start with 'sase_'"
        )


def test_counter_names_end_with_total() -> None:
    for attr, kind, name, _, _, _ in METRIC_DEFS:
        if kind == "counter":
            assert name.endswith("_total"), (
                f"{attr}: counter name {name!r} must end with '_total'"
            )


def test_histogram_names_end_with_seconds() -> None:
    for attr, kind, name, _, _, _ in METRIC_DEFS:
        if kind == "histogram":
            assert name.endswith("_seconds"), (
                f"{attr}: histogram name {name!r} must end with '_seconds'"
            )


def test_metric_names_are_unique() -> None:
    names = [name for _, _, name, _, _, _ in METRIC_DEFS]
    assert len(names) == len(set(names)), "Duplicate metric names found"


def test_module_attrs_are_unique() -> None:
    attrs = [attr for attr, _, _, _, _, _ in METRIC_DEFS]
    assert len(attrs) == len(set(attrs)), "Duplicate module attributes found"


def test_default_singletons_are_stubs() -> None:
    """All module-level singletons default to stub instances."""
    from sase.telemetry import metrics as m

    stub_types = (StubCounter, StubGauge, StubHistogram)
    for attr, _, _, _, _, _ in METRIC_DEFS:
        obj = getattr(m, attr)
        assert isinstance(obj, stub_types), (
            f"{attr} should be a stub, got {type(obj).__name__}"
        )


def test_metric_def_count() -> None:
    """Sanity check: 34 metrics total (30 original + 3 token counters + retry spawns)."""
    assert len(METRIC_DEFS) == 34
