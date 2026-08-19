"""Contract for :mod:`sase.monitor_status` and :func:`hash_palette_index`."""

from __future__ import annotations

import hashlib

import pytest

from sase.monitor.request import DEFAULT_START_STATUS, DEFAULT_STOP_STATUS
from sase.monitor_state import DEFAULT_MONITOR_STOP_STATUS as STOP_FROM_STATE
from sase.monitor_status import (
    DEFAULT_MONITOR_START_STATUS,
    DEFAULT_MONITOR_STOP_STATUS,
    MONITOR_STATUS_ACCENTS,
    MONITOR_STATUS_ELLIPSIS,
    MONITOR_STATUS_FAILURE_STYLE,
    MONITOR_STATUS_MAX_CHARS,
    clamp_monitor_status,
    clamp_monitor_status_or_default,
    effective_monitor_status,
    monitor_status_accent,
    monitor_status_glyph,
    monitor_status_pair,
    monitor_status_style,
)
from sase.palette_hash import hash_palette_index

_DARK_SHELL = "#121212"
# Documented pair accents: accidental palette reorder or hash change fails these.
_TESTING_ACCENT = "#6FC4FF"
_MONITORING_ACCENT = "#F8AD08"


def _linearize(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _relative_luminance(color: str) -> float:
    red, green, blue = (int(color[i : i + 2], 16) / 255.0 for i in (1, 3, 5))
    return (
        0.2126 * _linearize(red)
        + 0.7152 * _linearize(green)
        + 0.0722 * _linearize(blue)
    )


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_clamp_leaves_short_and_exact_labels_untouched() -> None:
    assert clamp_monitor_status("TESTING") == "TESTING"
    exact = "A" * MONITOR_STATUS_MAX_CHARS
    assert clamp_monitor_status(exact) == exact
    assert clamp_monitor_status("  TESTING  ") == "TESTING"


def test_clamp_truncates_over_the_cap_to_exactly_max_with_ellipsis() -> None:
    overflow = "VERIFYING THE WHOLE SUITE NOW"
    clamped = clamp_monitor_status(overflow)
    assert len(clamped) == MONITOR_STATUS_MAX_CHARS
    assert clamped[-1] == MONITOR_STATUS_ELLIPSIS
    assert clamped == overflow[: MONITOR_STATUS_MAX_CHARS - 1] + MONITOR_STATUS_ELLIPSIS


@pytest.mark.parametrize(
    "value",
    ["", "   ", "\t", "\n", "\r\n", "TEST\nED", "TEST\rED"],
)
def test_clamp_rejects_empty_and_multiline_values(value: str) -> None:
    with pytest.raises(ValueError):
        clamp_monitor_status(value)


def test_clamp_or_default_never_raises_and_fills_missing() -> None:
    assert (
        clamp_monitor_status_or_default(None, default=DEFAULT_MONITOR_START_STATUS)
        == DEFAULT_MONITOR_START_STATUS
    )
    assert (
        clamp_monitor_status_or_default("  ", default=DEFAULT_MONITOR_STOP_STATUS)
        == DEFAULT_MONITOR_STOP_STATUS
    )
    assert (
        clamp_monitor_status_or_default("TEST\nED", default=DEFAULT_MONITOR_STOP_STATUS)
        == DEFAULT_MONITOR_STOP_STATUS
    )
    overflow = "A" * 48
    clamped = clamp_monitor_status_or_default(
        overflow, default=DEFAULT_MONITOR_START_STATUS
    )
    assert len(clamped) == MONITOR_STATUS_MAX_CHARS
    assert clamped.endswith(MONITOR_STATUS_ELLIPSIS)


def test_pair_normalizes_case_and_whitespace_to_one_key() -> None:
    mixed = monitor_status_pair(" testing ", " tested ")
    canonical = monitor_status_pair("TESTING", "TESTED")
    assert mixed.key == canonical.key
    assert mixed.start == "testing"
    assert mixed.stop == "tested"


def test_pair_fills_missing_halves_from_the_defaults() -> None:
    pair = monitor_status_pair(None, None)
    assert pair.start == DEFAULT_MONITOR_START_STATUS
    assert pair.stop == DEFAULT_MONITOR_STOP_STATUS
    assert monitor_status_pair("", "TESTED").start == DEFAULT_MONITOR_START_STATUS
    assert monitor_status_pair("TESTING", None).stop == DEFAULT_MONITOR_STOP_STATUS


def test_accent_is_stable_and_process_independent() -> None:
    testing = monitor_status_pair("TESTING", "TESTED")
    monitoring = monitor_status_pair("MONITORING", "MONITORED")
    assert monitor_status_accent(testing) == _TESTING_ACCENT
    assert monitor_status_accent(monitoring) == _MONITORING_ACCENT
    assert monitor_status_accent(testing) == monitor_status_accent(
        monitor_status_pair("testing", "tested")
    )
    assert monitor_status_accent(testing) != monitor_status_accent(monitoring)


def test_palette_entries_are_unique_and_match_the_documented_literal() -> None:
    assert MONITOR_STATUS_ACCENTS == (
        "#FEA775",
        "#F8AD08",
        "#CCBF08",
        "#81D005",
        "#0BD68B",
        "#00D2C4",
        "#0BCDEC",
        "#6FC4FF",
        "#A1BAFF",
        "#C4B0FE",
        "#F39CFE",
        "#FF9ECD",
    )
    assert len(set(MONITOR_STATUS_ACCENTS)) == len(MONITOR_STATUS_ACCENTS)


def test_every_palette_entry_clears_aa_contrast_against_the_dark_shell() -> None:
    for color in MONITOR_STATUS_ACCENTS:
        assert _contrast_ratio(color, _DARK_SHELL) >= 4.5


@pytest.mark.parametrize(
    ("monitor_state", "style", "glyph"),
    [
        ("running", f"bold {_TESTING_ACCENT}", ""),
        ("completed", _TESTING_ACCENT, "✓"),
        ("stopped", _TESTING_ACCENT, "⊘"),
        ("failed", MONITOR_STATUS_FAILURE_STYLE, "✗"),
        ("timeout", MONITOR_STATUS_FAILURE_STYLE, "⧖"),
        ("lost", MONITOR_STATUS_FAILURE_STYLE, "⚠"),
        (None, f"bold {_TESTING_ACCENT}", ""),
        ("bogus", f"bold {_TESTING_ACCENT}", ""),
    ],
)
def test_style_rule_covers_every_monitor_state(
    monitor_state: str | None, style: str, glyph: str
) -> None:
    pair = monitor_status_pair("TESTING", "TESTED")
    assert monitor_status_style(pair, monitor_state=monitor_state) == style
    assert monitor_status_glyph(monitor_state) == glyph


@pytest.mark.parametrize(
    ("monitor_state", "settled", "expected"),
    [
        ("running", False, "TESTING"),
        (None, False, "TESTING"),
        ("bogus", False, "TESTING"),
        ("completed", False, "TESTED"),
        ("stopped", False, "TESTED"),
        ("failed", False, "TESTED"),
        ("timeout", False, "TESTED"),
        ("lost", False, "TESTED"),
        ("running", True, "TESTED"),
    ],
)
def test_effective_label_uses_stop_once_terminal_or_settled(
    monitor_state: str | None, settled: bool, expected: str
) -> None:
    pair = monitor_status_pair("TESTING", "TESTED")
    assert (
        effective_monitor_status(pair, monitor_state=monitor_state, settled=settled)
        == expected
    )


def test_hash_palette_index_matches_the_sha256_prefix_construction() -> None:
    key = "gh_sase-org__sase"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    expected = int.from_bytes(digest[:8], "big") % 18
    assert hash_palette_index(key, 18) == expected


def test_defaults_are_reexported_from_monitor_state_and_request() -> None:
    assert STOP_FROM_STATE == DEFAULT_MONITOR_STOP_STATUS
    assert DEFAULT_START_STATUS is DEFAULT_MONITOR_START_STATUS
    assert DEFAULT_STOP_STATUS is DEFAULT_MONITOR_STOP_STATUS
