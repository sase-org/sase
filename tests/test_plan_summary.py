"""Tests for sase.sdd.plan_summary."""

from __future__ import annotations

import pytest

from sase.sdd.plan_summary import (
    _PlanCountsSummary,
    decode_plan_counts,
    encode_plan_counts,
    plan_counts_summary,
)
from sase.sdd.plan_validate import (
    PlanValidationResult,
    ValidatedPlanPhase,
    _ValidatedPlan,
)


def _phase(
    phase_id: str, *, depends_on: tuple[str, ...] = (), size: str = "medium"
) -> ValidatedPlanPhase:
    return ValidatedPlanPhase(
        id=phase_id,
        title=phase_id,
        depends_on=depends_on,
        description=None,
        size=size,
        model=None,
    )


def _validation(phases: tuple[ValidatedPlanPhase, ...]) -> PlanValidationResult:
    plan = _ValidatedPlan(
        tier="epic",
        goal="do the thing",
        size=None,
        model=None,
        title="Test Plan",
        phases=phases,
        patch=None,
        bug_id=None,
        parent_bead=None,
        bead=None,
        parent=None,
        proposed_by=None,
    )
    return PlanValidationResult(schema_version=3, ok=True, diagnostics=(), plan=plan)


class TestPlanCountsSummary:
    def test_derives_phase_wave_and_size_counts(self) -> None:
        # Diamond dependency graph: a -> {b, c} -> d, so waves are
        # [a], [b, c], [d].
        phases = (
            _phase("a", size="xsmall"),
            _phase("b", depends_on=("a",), size="small"),
            _phase("c", depends_on=("a",), size="small"),
            _phase("d", depends_on=("b", "c"), size="medium"),
        )
        summary = plan_counts_summary(_validation(phases), tier="epic")
        assert summary == _PlanCountsSummary(
            tier="epic",
            phase_count=4,
            wave_count=3,
            size_counts=(("xsmall", 1), ("small", 2), ("medium", 1)),
        )

    def test_size_histogram_is_zero_omitted_and_canonically_ordered(self) -> None:
        phases = (_phase("a", size="large"), _phase("b", size="xsmall"))
        summary = plan_counts_summary(_validation(phases), tier="epic")
        assert summary is not None
        # Canonical PHASE_SIZE_VALUES order, not authored order, and no
        # zero-count entries for small/medium/xlarge.
        assert summary.size_counts == (("xsmall", 1), ("large", 1))

    def test_wave_count_none_on_dependency_cycle(self) -> None:
        phases = (_phase("a", depends_on=("b",)), _phase("b", depends_on=("a",)))
        summary = plan_counts_summary(_validation(phases), tier="epic")
        assert summary is not None
        assert summary.wave_count is None
        assert summary.phase_count == 2

    def test_returns_none_when_validation_failed(self) -> None:
        validation = PlanValidationResult(
            schema_version=3, ok=False, diagnostics=(), plan=None
        )
        assert plan_counts_summary(validation, tier="epic") is None


class TestEncodeDecodeRoundTrip:
    def test_epic_round_trip(self) -> None:
        summary = _PlanCountsSummary(
            tier="epic",
            phase_count=7,
            wave_count=3,
            size_counts=(("xsmall", 1), ("small", 2), ("medium", 3), ("large", 1)),
        )
        assert decode_plan_counts(encode_plan_counts(summary)) == summary

    def test_epic_round_trip_without_waves_or_sizes(self) -> None:
        summary = _PlanCountsSummary(
            tier="epic", phase_count=2, wave_count=None, size_counts=()
        )
        assert decode_plan_counts(encode_plan_counts(summary)) == summary

    def test_tale_encodes_tier_only(self) -> None:
        summary = _PlanCountsSummary(
            tier="tale", phase_count=0, wave_count=None, size_counts=()
        )
        encoded = encode_plan_counts(summary)
        assert encoded == {"plan_tier": "tale"}
        assert decode_plan_counts(encoded) == summary


class TestDecodePlanCountsHostileInput:
    @pytest.mark.parametrize(
        ("action_data", "expected"),
        [
            ({}, None),
            ({"plan_tier": "bogus"}, None),
            (
                {"plan_tier": "epic"},
                _PlanCountsSummary(
                    tier="epic", phase_count=0, wave_count=None, size_counts=()
                ),
            ),
            (
                {"plan_tier": "epic", "plan_phase_count": "abc"},
                _PlanCountsSummary(
                    tier="epic", phase_count=0, wave_count=None, size_counts=()
                ),
            ),
            (
                {"plan_tier": "epic", "plan_phase_count": "-3"},
                _PlanCountsSummary(
                    tier="epic", phase_count=0, wave_count=None, size_counts=()
                ),
            ),
            (
                {
                    "plan_tier": "epic",
                    "plan_phase_count": "5",
                    "plan_wave_count": "abc",
                },
                _PlanCountsSummary(
                    tier="epic", phase_count=5, wave_count=None, size_counts=()
                ),
            ),
            (
                {
                    "plan_tier": "epic",
                    "plan_phase_count": "5",
                    "plan_phase_sizes": "xsmall=abc",
                },
                _PlanCountsSummary(
                    tier="epic", phase_count=5, wave_count=None, size_counts=()
                ),
            ),
            (
                {
                    "plan_tier": "epic",
                    "plan_phase_count": "5",
                    "plan_phase_sizes": "bogus=2",
                },
                _PlanCountsSummary(
                    tier="epic", phase_count=5, wave_count=None, size_counts=()
                ),
            ),
            (
                {
                    "plan_tier": "epic",
                    "plan_phase_count": "5",
                    "plan_phase_sizes": "",
                },
                _PlanCountsSummary(
                    tier="epic", phase_count=5, wave_count=None, size_counts=()
                ),
            ),
        ],
    )
    def test_never_raises_and_degrades_field_by_field(
        self, action_data: dict[str, str], expected: _PlanCountsSummary | None
    ) -> None:
        assert decode_plan_counts(action_data) == expected

    def test_partial_size_parse_keeps_valid_entries(self) -> None:
        result = decode_plan_counts(
            {
                "plan_tier": "epic",
                "plan_phase_count": "3",
                "plan_phase_sizes": "xsmall=1,bogus=9,small=abc,medium=2",
            }
        )
        assert result == _PlanCountsSummary(
            tier="epic",
            phase_count=3,
            wave_count=None,
            size_counts=(("xsmall", 1), ("medium", 2)),
        )
