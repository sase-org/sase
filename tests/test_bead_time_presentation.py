"""Shared bead creation/update time presentation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, UTC

import pytest

from sase.bead_time_presentation import (
    BEAD_CREATED_GLYPH,
    BEAD_TIME_ACCENT,
    BEAD_TIME_CLI_STYLE,
    BEAD_TIME_RICH_STYLE,
    BEAD_TIME_UNKNOWN_LABEL,
    BEAD_UPDATED_GLYPH,
    bead_age_label,
    bead_created_chip,
    bead_created_cli,
    bead_created_label,
    bead_instant_label,
    bead_updated_chip,
    suppress_duplicate_updated,
)

# The store's canonical shape: aware UTC with a ``Z`` suffix. Rendered in the
# ``America/New_York`` timezone pinned for every test by ``tests/conftest.py``.
STORE_CREATED_AT = "2026-04-28T01:34:17Z"
STORE_CREATED_LOCAL = "2026-04-27 21:34:17 EDT"

# A fixed "now" three months after ``STORE_CREATED_AT``, expressed as the naive
# configured-tz wall time that ``local_now`` returns.
FIXED_NOW = datetime(2026, 7, 28, 12, 0, 0)


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``local_now`` so callers that omit ``now=`` stay deterministic."""
    monkeypatch.setattr("sase.core.time.local_now", lambda: FIXED_NOW)


def _created(**offset: float) -> datetime:
    """Return a wall-clock instant *offset* before :data:`FIXED_NOW`."""
    return FIXED_NOW - timedelta(**offset)


def test_glyphs_and_accent_are_the_documented_vocabulary() -> None:
    assert BEAD_CREATED_GLYPH == "⧖"
    assert BEAD_UPDATED_GLYPH == "✎"
    assert BEAD_TIME_ACCENT == "#5FAFAF"
    assert BEAD_TIME_RICH_STYLE == BEAD_TIME_ACCENT
    assert BEAD_TIME_CLI_STYLE.startswith("\x1b[38;5;")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (STORE_CREATED_AT, STORE_CREATED_LOCAL),
        # Naive ISO is configured-tz wall time by repo convention, so it is
        # *not* shifted the way the aware-UTC form above is.
        ("2026-04-28 01:34:17", "2026-04-28 01:34:17 EDT"),
        # Epoch seconds resolve through the same configured timezone.
        (
            datetime(2026, 4, 28, 1, 34, 17, tzinfo=UTC).timestamp(),
            STORE_CREATED_LOCAL,
        ),
        # A winter instant proves the tz abbreviation is not hard-coded.
        ("2026-01-01T00:00:00Z", "2025-12-31 19:00:00 EST"),
    ],
)
def test_instant_label_renders_stored_shapes_in_configured_timezone(
    value: object, expected: str
) -> None:
    assert bead_instant_label(value) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "   ", "not-a-timestamp", None])
def test_instant_label_is_honest_about_unusable_values(value: str | None) -> None:
    assert bead_instant_label(value) == BEAD_TIME_UNKNOWN_LABEL


@pytest.mark.parametrize(
    ("created", "expected"),
    [
        (_created(seconds=0), "now"),
        (_created(seconds=59), "now"),
        (_created(seconds=60), "1m"),
        (_created(minutes=59), "59m"),
        (_created(minutes=60), "1h"),
        (_created(hours=23), "23h"),
        (_created(hours=24), "1d"),
        (_created(days=29), "29d"),
        (_created(days=30), "1mo"),
        (_created(days=364), "12mo"),
        (_created(days=365), "1y"),
        (_created(days=800), "2y"),
    ],
)
def test_age_label_covers_every_bucket_boundary(
    created: datetime, expected: str
) -> None:
    assert bead_age_label(created) == expected


def test_age_label_clamps_a_skewed_future_timestamp_to_now() -> None:
    assert bead_age_label(FIXED_NOW + timedelta(days=3)) == "now"


@pytest.mark.parametrize("value", ["", "   ", "nonsense", None])
def test_age_label_is_empty_for_unusable_values(value: str | None) -> None:
    assert bead_age_label(value) == ""


def test_age_label_accepts_an_explicit_now_for_tests() -> None:
    assert (
        bead_age_label(STORE_CREATED_AT, now=datetime(2026, 4, 29, 1, 34, 17)) == "1d"
    )


def test_created_label_pairs_the_instant_with_a_relative_age() -> None:
    assert bead_created_label(STORE_CREATED_AT) == f"{STORE_CREATED_LOCAL} · 3mo ago"


def test_created_label_says_now_rather_than_now_ago() -> None:
    assert bead_created_label(_created(seconds=5)) == (
        f"{bead_instant_label(_created(seconds=5))} · now"
    )


def test_created_label_omits_the_age_entirely_when_not_relative() -> None:
    """Persisted surfaces must render a value that never drifts as it ages."""
    assert bead_created_label(STORE_CREATED_AT, relative=False) == STORE_CREATED_LOCAL


@pytest.mark.parametrize("relative", [True, False])
def test_created_label_placeholder_survives_both_density_modes(relative: bool) -> None:
    assert bead_created_label("garbage", relative=relative) == BEAD_TIME_UNKNOWN_LABEL


def test_created_and_updated_chips_carry_the_shared_accent() -> None:
    created = bead_created_chip(STORE_CREATED_AT)
    updated = bead_updated_chip(_created(days=2))
    assert created.plain == f"{BEAD_CREATED_GLYPH} 3mo"
    assert updated.plain == f"{BEAD_UPDATED_GLYPH} 2d"
    assert str(created.style) == BEAD_TIME_RICH_STYLE
    assert str(updated.style) == BEAD_TIME_RICH_STYLE


@pytest.mark.parametrize("chip", [bead_created_chip, bead_updated_chip])
def test_chips_are_empty_for_unusable_values(chip: object) -> None:
    assert chip("").plain == ""  # type: ignore[operator]


def test_created_cli_cell_wraps_the_compact_age_in_color_when_asked() -> None:
    plain = bead_created_cli(STORE_CREATED_AT, use_color=False)
    colored = bead_created_cli(STORE_CREATED_AT, use_color=True)
    assert plain == f"{BEAD_CREATED_GLYPH} 3mo"
    assert colored == f"{BEAD_TIME_CLI_STYLE}{plain}\x1b[0m"


def test_created_cli_cell_uses_a_stable_date_when_not_relative() -> None:
    assert (
        bead_created_cli(STORE_CREATED_AT, use_color=False, relative=False)
        == f"{BEAD_CREATED_GLYPH} 2026-04-27"
    )


@pytest.mark.parametrize("use_color", [True, False])
def test_created_cli_cell_is_empty_for_unusable_values(use_color: bool) -> None:
    assert bead_created_cli("", use_color=use_color) == ""


@pytest.mark.parametrize(
    ("created", "updated", "suppressed"),
    [
        # A freshly filed bead: both timestamps render the same label.
        (STORE_CREATED_AT, STORE_CREATED_AT, True),
        # Same bucket, different instants -- still nothing new to say.
        (_created(days=90), _created(days=95), True),
        # A genuinely later update earns its own cell.
        (STORE_CREATED_AT, _created(days=2), False),
        # No usable update timestamp at all.
        (STORE_CREATED_AT, "", True),
        (STORE_CREATED_AT, None, True),
    ],
)
def test_suppress_duplicate_updated_keeps_dense_rows_quiet(
    created: object, updated: object, suppressed: bool
) -> None:
    assert suppress_duplicate_updated(created, updated) is suppressed  # type: ignore[arg-type]
