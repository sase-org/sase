"""Tests for the ToolRun state vocabulary (plan §3.2, epic sase-1bt)."""

from __future__ import annotations

import unicodedata

import pytest

from sase.tool.view_vocabulary import (
    BUCKET_STYLES,
    SEVERITY_ORDER,
    format_age,
    format_min_sec,
    format_settled_ts,
    header_chip_text,
    is_silent,
    row_chip_text,
    severity_rank,
    style_for_bucket,
    switcher_runs_text,
)


@pytest.mark.parametrize(
    ("bucket", "glyph", "word", "color"),
    [
        ("running", "⚒", "running", "bold #87D7FF"),
        ("silent", "⚒⚠", "silent", "bold #FF5F5F"),
        ("pass", "✓", "pass", "#5FD75F"),
        ("new_failures", "✗", "NEW", "#FF5F5F"),
        ("known_only", "≈", "known only", "#87AF87"),
        ("undetermined", "?", "UNKNOWN", "#FFAF5F"),
        ("killed", "⊘", "killed", "#D75FFF"),
        ("stopped", "⊘", "stopped", "dim"),
        ("lost", "⊘", "lost", "dim #FF5F5F"),
    ],
)
def test_bucket_table(bucket: str, glyph: str, word: str, color: str) -> None:
    style = style_for_bucket(bucket)
    assert (style.glyph, style.word, style.color) == (glyph, word, color)
    assert BUCKET_STYLES[bucket] is style


def test_unknown_bucket_falls_back_to_undetermined() -> None:
    assert style_for_bucket("bogus") is BUCKET_STYLES["undetermined"]
    assert style_for_bucket(None) is BUCKET_STYLES["undetermined"]


def test_severity_order_matches_plan() -> None:
    assert SEVERITY_ORDER == (
        "new_failures",
        "undetermined",
        "killed",
        "lost",
        "stopped",
        "known_only",
        "pass",
    )
    ranks = [severity_rank(bucket) for bucket in SEVERITY_ORDER]
    assert ranks == sorted(ranks)
    assert severity_rank("bogus") == severity_rank("undetermined")


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "<1m"),
        (59, "<1m"),
        (60, "1m"),
        (133, "2m"),
        (3599, "59m"),
        (3600, "1h"),
        (71 * 3600, "71h"),
        (72 * 3600, "3d"),
        (2 * 86400, "48h"),
    ],
)
def test_format_age(seconds: float, expected: str) -> None:
    assert format_age(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(540, "9m00s"), (62, "1m02s"), (252, "4m12s"), (241, "4m01s"), (0, "0m00s")],
)
def test_format_min_sec(seconds: float, expected: str) -> None:
    assert format_min_sec(seconds) == expected


def test_is_silent_threshold() -> None:
    assert is_silent(0, 59.9) is False
    assert is_silent(0, 60) is True
    assert is_silent(0, 61, silent_after_s=120) is False


def test_row_chip_progress() -> None:
    assert row_chip_text("check", stages_done=6, stages_expected=11) == "⚒ check 7/11"


def test_row_chip_settled_position_without_in_flight_stage() -> None:
    assert (
        row_chip_text("check", stages_done=7, stages_expected=11, in_flight=False)
        == "⚒ check 7/11"
    )


def test_row_chip_starting_and_stopping() -> None:
    assert row_chip_text("check", state="created") == "⚒ check starting"
    assert (
        row_chip_text("check", stages_done=6, stages_expected=11, stop_requested=True)
        == "⚒ check stopping"
    )


def test_row_chip_silent() -> None:
    assert row_chip_text("check", silent_age_s=240) == "⚒⚠ check silent 4m"


def test_row_chip_falls_back_to_elapsed_past_reference() -> None:
    assert (
        row_chip_text("check", stages_done=11, stages_expected=11, elapsed_s=133)
        == "⚒ check 2m"
    )
    assert row_chip_text("check", elapsed_s=133) == "⚒ check 2m"


def test_row_chip_extra_live_run() -> None:
    assert (
        row_chip_text("check", stages_done=6, stages_expected=11, extra_live=1)
        == "⚒ check 7/11+1"
    )


def test_row_chip_truncates_label_first_to_20_cells() -> None:
    text = row_chip_text("very-long-tool-name", stages_done=6, stages_expected=11)
    assert text == "⚒ very-long-to… 7/11"
    assert len(text) == 20


def test_row_chip_truncates_silent_label() -> None:
    text = row_chip_text("very-long-tool-name", silent_age_s=240)
    assert len(text) <= 20
    assert text.startswith("⚒⚠ ")
    assert text.endswith(" silent 4m")


def test_header_chip_live_with_typical() -> None:
    assert (
        header_chip_text(
            "check",
            "running",
            stage="lint (mypy)",
            stages_done=6,
            stages_expected=11,
            elapsed_s=133,
            typical_ms=253000,
        )
        == "⚒ check · lint (mypy) 7/11 · 2m13s / typ 4m13s"
    )


def test_header_chip_silent() -> None:
    assert (
        header_chip_text(
            "check", "running", stage="test (scoped)", silent_age_s=3 * 86400
        )
        == "⚒⚠ check · test (scoped) · silent 3d"
    )


def test_header_chip_settled_buckets() -> None:
    settled = format_settled_ts(1_700_000_000)
    assert (
        header_chip_text("check", "pass", duration_ms=241000, settled_ts=1_700_000_000)
        == f"⚒ check ✓ 4m01s · {settled}"
    )
    assert (
        header_chip_text(
            "check",
            "new_failures",
            new=3,
            known=1,
            duration_ms=252000,
            settled_ts=1_700_000_000,
        )
        == f"⚒ check ✗ 3 NEW · 1 KNOWN · 4m12s · {settled}"
    )
    assert (
        header_chip_text(
            "check",
            "known_only",
            known=2,
            duration_ms=245000,
            settled_ts=1_700_000_000,
        )
        == f"⚒ check ≈ known only · 2 KNOWN · 4m05s · {settled}"
    )
    assert (
        header_chip_text(
            "check",
            "undetermined",
            unknown=2,
            duration_ms=260000,
            settled_ts=1_700_000_000,
        )
        == f"⚒ check ? 2 UNKNOWN · 4m20s · {settled}"
    )
    assert (
        header_chip_text("check", "undetermined", untriaged=True)
        == "⚒ check ? untriaged"
    )


def test_header_chip_killed_stopped_lost() -> None:
    settled = format_settled_ts(1_700_000_000)
    assert (
        header_chip_text(
            "check",
            "killed",
            terminal_cause="signal",
            duration_ms=540000,
            settled_ts=1_700_000_000,
        )
        == f"⚒ check ⊘ killed at 9m00s · signal · {settled}"
    )
    assert (
        header_chip_text(
            "check", "killed", terminal_cause="timeout", duration_ms=1800000
        )
        == "⚒ check ⊘ timed out at 30m00s"
    )
    assert (
        header_chip_text("check", "stopped", duration_ms=62000)
        == "⚒ check ⊘ stopped at 1m02s"
    )
    assert (
        header_chip_text("check", "lost", terminal_cause="wrapper_lost")
        == "⚒ check ⊘ lost · wrapper_lost"
    )
    assert header_chip_text("check", "lost") == "⚒ check ⊘ lost"


def test_header_chip_extra_labels_suffix() -> None:
    assert (
        header_chip_text("check", "pass", duration_ms=241000, extra_labels=2).endswith(
            "+2"
        )
        is True
    )


def test_switcher_runs_text() -> None:
    assert switcher_runs_text(2) == "⚒2"
    assert switcher_runs_text(0) == "⚒0"


@pytest.mark.parametrize("char", ["⚒", "⚠", "⏲", "✓", "✗", "⊘", "?"])
def test_chip_glyphs_are_single_cell(char: str) -> None:
    assert unicodedata.east_asian_width(char) in {"N", "Na"}


def test_known_only_glyph_is_never_wide() -> None:
    assert unicodedata.east_asian_width("≈") in {"N", "Na", "H", "A"}
