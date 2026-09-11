"""Shared helpers for compact provider-usage top-bar presentation tests."""

from __future__ import annotations

from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.ace.tui.widgets._provider_usage_indicator import usage_indicator_groups
from tests._usage_view_helpers import usage_provider, usage_window

FROZEN_NOW = 1_800_000_000.0

_CONSOLE = Console(width=240)


def _rendered_segments(text: Text) -> list[tuple[str, Style | None]]:
    """Return the fully resolved (base + span) style for each rendered run."""
    return [(segment.text, segment.style) for segment in text.render(_CONSOLE)]


def _segments_with_offsets(text: Text) -> list[tuple[int, int, str, Style | None]]:
    offset = 0
    result: list[tuple[int, int, str, Style | None]] = []
    for segment in text.render(_CONSOLE):
        length = len(segment.text)
        if length:
            result.append((offset, offset + length, segment.text, segment.style))
        offset += length
    return result


def _style_for(text: Text, token: str) -> Style:
    """Return the resolved style of the one segment rendering exactly *token*."""
    matches = [
        style for rendered, style in _rendered_segments(text) if rendered == token
    ]
    assert len(matches) == 1, (
        f"expected exactly one {token!r} segment in {text.plain!r}"
    )
    style = matches[0]
    assert style is not None
    return style


def _style_at_token(text: Text, token: str, *, occurrence: int = 0) -> Style:
    start = -1
    cursor = 0
    for _ in range(occurrence + 1):
        start = text.plain.find(token, cursor)
        assert start >= 0, f"missing {token!r} occurrence {occurrence}"
        cursor = start + len(token)
    for seg_start, seg_end, _rendered, style in _segments_with_offsets(text):
        if seg_start <= start < seg_end:
            assert style is not None
            return style
    raise AssertionError(f"no style for {token!r} in {text.plain!r}")


def _style_at_offset(text: Text, offset: int) -> Style:
    for seg_start, seg_end, _rendered, style in _segments_with_offsets(text):
        if seg_start <= offset < seg_end:
            assert style is not None
            return style
    raise AssertionError(f"no style at offset {offset} in {text.plain!r}")


def _pipe_styles(text: Text) -> list[Style]:
    styles: list[Style] = []
    for index, character in enumerate(text.plain):
        if character != "|":
            continue
        for seg_start, seg_end, _rendered, style in _segments_with_offsets(text):
            if seg_start <= index < seg_end:
                assert style is not None
                styles.append(style)
                break
    return styles


def _assert_style_run(
    text: Text,
    run: str,
    expected: Style,
    *,
    occurrence: int = 0,
) -> tuple[int, int]:
    start = -1
    cursor = 0
    for _ in range(occurrence + 1):
        start = text.plain.find(run, cursor)
        assert start >= 0, f"missing {run!r} occurrence {occurrence}"
        cursor = start + len(run)
    end = start + len(run)
    for offset in range(start, end):
        assert _style_at_offset(text, offset) == expected
    return start, end


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    stripped = value.lstrip("#")
    return tuple(int(stripped[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _srgb_to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(value: str) -> float:
    r, g, b = (_srgb_to_linear(c) for c in _hex_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(a: str, b: str) -> float:
    la = _relative_luminance(a) + 0.05
    lb = _relative_luminance(b) + 0.05
    return max(la, lb) / min(la, lb)


def _scope(
    *,
    kind: str,
    product: str | None = None,
    family: str | None = None,
    model_ids: tuple[str, ...] = (),
    vendor_label: str | None = None,
    vendor_id: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "product": product,
        "family": family,
        "model_ids": list(model_ids),
        "vendor_label": vendor_label,
        "vendor_id": vendor_id,
    }


def _entry(
    *,
    provider: str = "claude",
    window_key: str = "weekly",
    window_label: str = "Week - all",
    weekly_all: bool = True,
    period_kind: str = "weekly",
    duration_seconds: float | None = 604_800.0,
    scope: dict[str, object] | None = None,
    remaining_percent: float = 62.0,
    freshness: str = "fresh",
    reset_state: str = "future",
    seconds_until_reset: float | None = 273_840.0,
    resets_at: float | None = FROZEN_NOW + 273_840.0,
    vendor_state: str = "allowed",
    window_attention: str = "none",
    display_attention: str = "none",
    collector_problem: bool = False,
    policy_source: str = "weekly_all",
) -> dict[str, object]:
    return {
        "provider": provider,
        "context_ref": f"{provider}:default:1",
        "window_key": window_key,
        "window_label": window_label,
        "effective_policy": {"kind": "always"},
        "policy_source": policy_source,
        "weekly_all": weekly_all,
        "period": {"kind": period_kind, "duration_seconds": duration_seconds},
        "scope": scope or _scope(kind="all_models"),
        "used_percent": max(0.0, 100.0 - remaining_percent),
        "remaining_percent": remaining_percent,
        "exceeded_by_percent": None,
        "freshness": freshness,
        "reset_state": reset_state,
        "seconds_until_reset": seconds_until_reset,
        "resets_at": resets_at,
        "duration_seconds": duration_seconds,
        "period_start": None,
        "age_seconds": 30.0,
        "observed_at": FROZEN_NOW - 30.0,
        "vendor_state": vendor_state,
        "window_attention": window_attention,
        "display_attention": display_attention,
        "collector_problem": collector_problem,
    }


def _groups(*entries: dict[str, object], dark: bool = True):
    return usage_indicator_groups(entries, dark=dark, now=FROZEN_NOW)


def _indicator_snapshot(*windows: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": FROZEN_NOW,
        "collection_health": "ok",
        "providers": [
            usage_provider(
                "claude",
                used_percent=10.0,
                remaining_percent=90.0,
                attention={
                    "kind": "none",
                    "provider": "claude",
                    "window_key": "weekly",
                },
                windows=list(windows),
                known_constraints=[],
            )
        ],
        "attention": None,
    }


def _weekly_usage_window(
    *,
    key: str,
    label: str,
    remaining_percent: float,
    resets_at: float,
    applicability: dict[str, object],
) -> dict[str, object]:
    window = usage_window(
        key=key,
        label=label,
        used_percent=max(0.0, 100.0 - remaining_percent),
        remaining_percent=remaining_percent,
        resets_at=resets_at,
        applicability=applicability,
    )
    window["duration_seconds"] = 604_800.0
    return window
