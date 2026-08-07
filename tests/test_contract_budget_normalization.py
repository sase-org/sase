"""Unit coverage for the contract-set budget guard's normalization arithmetic.

These tests never run the contract set: they feed recorded CPU numbers through
the pure functions in :mod:`tests._test_contract_budget`. The first regression
pair is real measurements taken on the dev host on 2026-08-06, one on a quiet
host and one under 96 spinner processes (pure CPU-cycle contention), pinned
against the probe of the time explicitly via ``baseline=0.77`` since the live
:data:`PROBE_BASELINE_CPU_SECONDS` has since moved. They pin the property the
whole approach rests on -- the same contract set normalizes to the same figure
under loads whose raw wall clock differs by 1.5x.

The second pair is `sase-go`'s 2026-08-07 measurements with the reshaped probe
(see ``PROBE_SOURCE``'s comment), one with no deliberate contention and one
under 40 real xdist workers importing and running ``tests/ace/`` -- the
memory-bandwidth-bound shape the first pair does not exercise.
"""

from __future__ import annotations

import pytest

from tests._test_contract_budget import (
    PROBE_BASELINE_CPU_SECONDS,
    Measurement,
    describe_measurement,
    normalization_factor,
    normalize_seconds,
)


#: Contract set (34 files, 289 tests) measured on a quiet 64-core dev host,
#: normalized against the probe live at the time (``baseline=0.77``).
QUIET_RUN = Measurement(wall=24.37, cpu=24.18, probe_cpu=(0.854, 0.791), baseline=0.77)
#: The same set, same commit, under 96 spinner processes (loadavg 61).
LOADED_RUN = Measurement(wall=37.13, cpu=33.97, probe_cpu=(1.172, 1.234), baseline=0.77)

#: Contract set (34 files, 308+ tests) on the same host with no deliberate
#: contention beyond this host's usual ambient agent load (loadavg 30-35).
QUIET_RUN_XDIST = Measurement(wall=27.38, cpu=27.43, probe_cpu=(1.059, 0.936))
#: The same set, same commit, under 40 real xdist workers running
#: ``tests/ace/`` -- import- and allocation-heavy, not CPU-spin.
LOADED_RUN_XDIST = Measurement(wall=29.25, cpu=29.37, probe_cpu=(1.057, 0.958))

_BUDGET_SECONDS = 35.0


def test_factor_is_the_baseline_over_the_mean_probe() -> None:
    factor = normalization_factor((0.5, 1.5), baseline=2.0)

    assert factor == pytest.approx(2.0)


def test_normalize_scales_measured_cpu_onto_the_reference_scale() -> None:
    # A host running at half speed reads a 2x probe, so half its CPU counts.
    assert normalize_seconds(40.0, (2.0, 2.0), baseline=1.0) == pytest.approx(20.0)


def test_a_probe_matching_the_baseline_leaves_the_measurement_alone() -> None:
    baseline = PROBE_BASELINE_CPU_SECONDS

    assert normalize_seconds(21.0, (baseline, baseline)) == pytest.approx(21.0)


def test_both_bracket_probes_count() -> None:
    """A load change arriving mid-run is split between the brackets."""
    before_only = normalize_seconds(30.0, (1.0,), baseline=1.0)
    bracketed = normalize_seconds(30.0, (1.0, 2.0), baseline=1.0)

    assert before_only == pytest.approx(30.0)
    assert bracketed == pytest.approx(20.0)


def test_normalization_needs_at_least_one_probe() -> None:
    with pytest.raises(ValueError, match="at least one calibration probe"):
        normalization_factor(())


@pytest.mark.parametrize("probe", [0.0, -1.0])
def test_non_positive_probe_is_rejected_rather_than_dividing_by_zero(
    probe: float,
) -> None:
    with pytest.raises(ValueError, match="non-positive CPU"):
        normalization_factor((probe,))


def test_raw_wall_clock_would_have_failed_the_loaded_run() -> None:
    """The regression this phase exists to fix."""
    assert LOADED_RUN.wall > _BUDGET_SECONDS
    assert QUIET_RUN.wall <= _BUDGET_SECONDS
    assert LOADED_RUN.wall / QUIET_RUN.wall > 1.5


def test_raw_cpu_alone_is_not_enough_either() -> None:
    """`sase-fp.3` proposed CPU time; CPU still inflates 1.4x under load."""
    assert LOADED_RUN.cpu / QUIET_RUN.cpu > 1.35


def test_the_same_set_normalizes_alike_under_quiet_and_loaded_probes() -> None:
    quiet = QUIET_RUN.normalized
    loaded = LOADED_RUN.normalized

    # 15%: the normalization removes the bulk of a 1.5x wall inflation, not
    # every last percent of it. Both readings sit well under the budget.
    assert loaded == pytest.approx(quiet, rel=0.15)
    assert max(quiet, loaded) <= _BUDGET_SECONDS


def test_the_quiet_reading_matches_the_headroom_recorded_in_the_guard() -> None:
    assert QUIET_RUN.normalized == pytest.approx(22.6, abs=0.5)


def test_the_reshaped_probe_still_moves_under_xdist_contention() -> None:
    """The reshape (see `PROBE_SOURCE`) is a real, measured improvement, not a
    full fix: comparing a truly quiet baseline to 40 real xdist workers, the
    old cache-resident probe under-corrected sharply (~6% probe move against
    a ~20% true CPU inflation); the reshaped probe narrows that to ~9-10%,
    which is why `_BUDGET_SECONDS` also grew rather than relying on
    normalization alone to close the whole gap.
    """
    quiet = QUIET_RUN_XDIST.normalized
    loaded = LOADED_RUN_XDIST.normalized

    assert loaded > quiet  # some residual under-correction remains
    assert loaded == pytest.approx(quiet, rel=0.10)
    assert max(quiet, loaded) <= _BUDGET_SECONDS


def test_the_xdist_quiet_reading_matches_todays_headroom() -> None:
    assert QUIET_RUN_XDIST.normalized == pytest.approx(25.8, abs=0.5)


def test_the_xdist_loaded_reading_still_clears_the_budget_with_margin() -> None:
    headroom = (_BUDGET_SECONDS - LOADED_RUN_XDIST.normalized) / _BUDGET_SECONDS

    assert headroom > 0.15


def test_failure_message_shows_every_input_to_the_verdict() -> None:
    message = describe_measurement(LOADED_RUN, _BUDGET_SECONDS)

    assert "37.1s" in message  # raw wall
    assert "34.0s" in message  # raw child CPU
    assert "1.172s" in message  # leading probe
    assert "1.234s" in message  # trailing probe
    assert f"{LOADED_RUN.factor:.3f}" in message  # normalization factor
    assert f"{LOADED_RUN.normalized:.1f}s" in message  # the compared figure
    assert "35s budget" in message
