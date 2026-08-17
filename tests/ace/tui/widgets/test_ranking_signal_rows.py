"""Provider-neutral tests for the shared ranking-signal renderers."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.widgets._ranking_signal_rows import (
    RECENCY_COLOR,
    RELATION_COLOR,
    _RankingSignals,
    build_score_meter,
    format_reason_chip,
    ranking_label_width,
    ranking_signal_legend,
)


@dataclass(frozen=True, slots=True)
class _Signals:
    """Test-local stand-in proving ``_RankingSignals`` is provider-neutral."""

    reason: str
    related_to: str
    use_count: int
    age_seconds: float
    score: float
    relation: float
    recency: float
    frequency: float


def test_ranking_signals_protocol_is_satisfied_structurally() -> None:
    assert isinstance(
        _Signals("recency", "", 0, 0.0, 0.0, 0.0, 0.0, 0.0), _RankingSignals
    )


def test_ranking_label_width_adds_badge_cells_and_caps() -> None:
    assert ranking_label_width("reconciliation", badge_cells=0, cap=28) == 14
    assert ranking_label_width("phase title", badge_cells=2, cap=28) == 13
    assert ranking_label_width("a" * 40, badge_cells=2, cap=28) == 28


def test_score_meter_renders_empty_for_zero_score() -> None:
    signals = _Signals(
        reason="recency",
        related_to="",
        use_count=0,
        age_seconds=0.0,
        score=0.0,
        relation=0.0,
        recency=0.0,
        frequency=0.0,
    )

    meter = build_score_meter(signals)

    assert meter.plain == "▱▱▱▱▱"
    assert all(str(span.style) == "dim" for span in meter.spans)


def test_score_meter_distributes_fixed_signal_order_by_largest_remainder() -> None:
    signals = _Signals(
        reason="relation",
        related_to="monitor",
        use_count=1,
        age_seconds=10.0,
        score=0.6,
        relation=0.4,
        recency=0.2,
        frequency=0.0,
    )

    meter = build_score_meter(signals)

    assert meter.plain == "▰▰▰▱▱"
    styles = [str(span.style) for span in meter.spans]
    assert styles == [
        f"bold {RELATION_COLOR}",
        f"bold {RELATION_COLOR}",
        f"bold {RECENCY_COLOR}",
        "dim",
        "dim",
    ]


def test_score_meter_never_shows_fewer_than_one_filled_cell_for_positive_score() -> (
    None
):
    signals = _Signals(
        reason="frequency",
        related_to="",
        use_count=1,
        age_seconds=0.0,
        score=0.02,
        relation=0.0,
        recency=0.0,
        frequency=0.02,
    )

    meter = build_score_meter(signals)

    assert meter.plain.count("▰") == 1
    assert meter.plain.count("▱") == 4


def test_reason_chip_shows_related_context_word() -> None:
    signals = _Signals(
        reason="relation",
        related_to="monitor",
        use_count=0,
        age_seconds=0.0,
        score=0.4,
        relation=0.4,
        recency=0.0,
        frequency=0.0,
    )

    chip = format_reason_chip(signals)

    assert chip.plain == "⇄ monitor"


def test_reason_chip_truncates_long_context_word() -> None:
    signals = _Signals(
        reason="relation",
        related_to="a" * 20,
        use_count=0,
        age_seconds=0.0,
        score=0.4,
        relation=0.4,
        recency=0.0,
        frequency=0.0,
    )

    chip = format_reason_chip(signals)

    assert chip.plain == "⇄ " + "a" * 13 + "..."


def test_reason_chip_shows_use_count_for_frequency() -> None:
    signals = _Signals(
        reason="frequency",
        related_to="",
        use_count=47,
        age_seconds=0.0,
        score=0.2,
        relation=0.0,
        recency=0.0,
        frequency=0.2,
    )

    chip = format_reason_chip(signals)

    assert chip.plain == "✦ 47×"


def test_reason_chip_age_unit_boundaries() -> None:
    def chip_for(age_seconds: float) -> str:
        signals = _Signals(
            reason="recency",
            related_to="",
            use_count=0,
            age_seconds=age_seconds,
            score=0.3,
            relation=0.0,
            recency=0.3,
            frequency=0.0,
        )
        return format_reason_chip(signals).plain

    assert chip_for(59) == "◷ 59s"
    assert chip_for(60) == "◷ 1m"
    assert chip_for(3599) == "◷ 59m"
    assert chip_for(3600) == "◷ 1h"
    assert chip_for(86399) == "◷ 23h"
    assert chip_for(86400) == "◷ 1d"
    assert chip_for(604799) == "◷ 6d"
    assert chip_for(604800) == "◷ 1w"


def test_ranking_signal_legend_lists_all_three_signals_in_order() -> None:
    legend = ranking_signal_legend()

    assert legend.plain == "⇄ related · ◷ recent · ✦ frequent"
