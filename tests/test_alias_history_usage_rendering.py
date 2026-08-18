"""Tests for the Alias History model-usage strip renderer."""

from __future__ import annotations

from sase.ace.tui.modals.alias_history_usage_rendering import alias_history_usage_text
from sase.ace.tui.provider_styles import provider_bar_style
from sase.llm_provider.alias_history_usage import (
    AliasHistoryModelUsage,
    AliasHistoryUsageSummary,
    summarize_alias_history_usage,
)

from ._alias_history_helpers import make_group, make_pool_member, make_run, make_view


def _row(
    *,
    provider: str | None = "claude",
    model: str | None = "opus",
    effort: str | None = "high",
    effort_is_mixed: bool = False,
    count: int = 1,
    share: float = 1.0,
    share_percent: int = 100,
    done: int = 1,
    failed: int = 0,
    running: int = 0,
    in_pool: bool = True,
    is_unrecorded: bool = False,
) -> AliasHistoryModelUsage:
    return AliasHistoryModelUsage(
        provider=provider,
        model=model,
        effort=effort,
        effort_is_mixed=effort_is_mixed,
        count=count,
        share=share,
        share_percent=share_percent,
        done=done,
        failed=failed,
        running=running,
        in_pool=in_pool,
        is_unrecorded=is_unrecorded,
    )


def _summary(
    rows: list[AliasHistoryModelUsage],
    *,
    counted_runs: int | None = None,
    duplicate_runs: int = 0,
    pool_total: int = 0,
    pool_used: int = 0,
) -> AliasHistoryUsageSummary:
    return AliasHistoryUsageSummary(
        rows=tuple(rows),
        counted_runs=sum(row.count for row in rows)
        if counted_runs is None
        else counted_runs,
        duplicate_runs=duplicate_runs,
        pool_total=pool_total,
        pool_used=pool_used,
    )


def test_loading_and_error_are_single_line() -> None:
    loading = alias_history_usage_text(None)
    assert loading.plain == "Model usage · loading…"
    assert "\n" not in loading.plain
    error = alias_history_usage_text(None, error="disk full")
    assert error.plain == "Model usage · disk full"
    assert "\n" not in error.plain


def test_empty_window_is_single_line() -> None:
    text = alias_history_usage_text(_summary([], counted_runs=0, pool_total=2))
    assert text.plain == "Model usage · no runs in this window"
    assert "\n" not in text.plain


def test_header_omits_members_segment_when_pool_is_not_a_pool() -> None:
    text = alias_history_usage_text(
        _summary([_row()], counted_runs=1, pool_total=1, pool_used=1)
    )
    assert "Model usage" in text.plain
    assert "1 run" in text.plain
    assert "members used" not in text.plain


def test_header_includes_members_segment_and_deduped() -> None:
    text = alias_history_usage_text(
        _summary(
            [_row(count=2, share=1.0, share_percent=100)],
            counted_runs=2,
            duplicate_runs=1,
            pool_total=3,
            pool_used=2,
        )
    )
    plain = text.plain
    assert "2 runs" in plain
    assert "(deduped)" in plain
    assert "2 of 3 members used" in plain


def test_row_columns_align_across_models() -> None:
    summary = _summary(
        [
            _row(model="opus", count=3, share=0.75, share_percent=75),
            _row(model="sonnet", count=1, share=0.25, share_percent=25),
        ],
        counted_runs=4,
    )
    lines = alias_history_usage_text(summary).plain.splitlines()[1:]
    bar_starts = [line.index("█") if "█" in line else line.index("░") for line in lines]
    assert bar_starts[0] == bar_starts[1]
    percents = [line.rfind("%") for line in lines]
    assert percents[0] == percents[1]


def test_one_percent_share_still_paints_a_visible_cell() -> None:
    text = alias_history_usage_text(
        _summary(
            [_row(count=1, share=0.001, share_percent=0)],
            counted_runs=1000,
        )
    )
    body = text.plain.splitlines()[1]
    assert any(glyph in body for glyph in "▏▎▍▌▋▊▉█")


def test_failed_and_running_chips_appear_only_when_nonzero() -> None:
    quiet = alias_history_usage_text(
        _summary([_row(failed=0, running=0)], counted_runs=1)
    )
    noisy = alias_history_usage_text(
        _summary([_row(failed=2, running=1, done=0)], counted_runs=3)
    )
    assert "✗" not in quiet.plain
    assert "▶" not in quiet.plain
    assert "✗2" in noisy.plain
    assert "▶1" in noisy.plain


def test_unused_and_off_pool_tags() -> None:
    text = alias_history_usage_text(
        _summary(
            [
                _row(
                    model="sonnet",
                    count=2,
                    share=2 / 3,
                    share_percent=67,
                    in_pool=True,
                ),
                _row(
                    model="haiku",
                    count=1,
                    share=1 / 3,
                    share_percent=33,
                    in_pool=False,
                ),
                _row(model="opus", count=0, share=0.0, share_percent=0, in_pool=True),
            ],
            counted_runs=3,
            pool_total=2,
            pool_used=1,
        )
    )
    assert "unused" in text.plain
    assert "off-pool" in text.plain


def test_overflow_row_math_uses_remaining_percent() -> None:
    # 10+9+8+7+6 = 40; let summarize compute honest percents.
    runs = [
        make_run(
            artifact_dir=f"/tmp/{model}-{n}",
            model=model,
            llm_provider="claude",
        )
        for model, count in (
            ("m0", 10),
            ("m1", 9),
            ("m2", 8),
            ("m3", 7),
            ("m4", 6),
        )
        for n in range(count)
    ]
    summary = summarize_alias_history_usage(make_view([make_group("large", runs)]))
    text = alias_history_usage_text(summary)
    lines = text.plain.splitlines()
    assert len(lines) == 5
    assert "+2 more" in lines[-1]
    shown_percents = [
        int(line.split()[-1].rstrip("%"))
        for line in lines[1:4]
        if line.strip() and not line.strip().startswith("+")
    ]
    overflow_percent = int(lines[-1].split()[-1].rstrip("%"))
    assert sum(shown_percents) + overflow_percent == 100
    assert "13" in lines[-1]


def test_mixed_effort_renders_dim_mixed_suffix() -> None:
    text = alias_history_usage_text(
        _summary(
            [_row(effort=None, effort_is_mixed=True, count=2, share=1.0)],
            counted_runs=2,
        )
    )
    assert "@ mixed" in text.plain


def test_unrecorded_row_uses_unrecorded_label() -> None:
    text = alias_history_usage_text(
        _summary(
            [
                _row(
                    provider=None,
                    model=None,
                    effort=None,
                    is_unrecorded=True,
                    in_pool=False,
                )
            ],
            counted_runs=1,
        )
    )
    assert "unrecorded" in text.plain


def test_provider_bar_style_is_unbolded_model_hue() -> None:
    assert "bold" not in provider_bar_style("claude")
    assert provider_bar_style("claude") == "#FFAF00"


def test_zero_share_unused_row_is_empty_track() -> None:
    runs = [make_run(artifact_dir="/tmp/1", model="sonnet", llm_provider="claude")]
    summary = summarize_alias_history_usage(
        make_view([make_group("large", runs)]),
        pool=(
            make_pool_member("claude", "sonnet"),
            make_pool_member("claude", "opus"),
        ),
    )
    text = alias_history_usage_text(summary)
    unused_line = next(line for line in text.plain.splitlines() if "unused" in line)
    assert "░" * 10 in unused_line
    assert "  0%" in unused_line or unused_line.rstrip().endswith("0%")
