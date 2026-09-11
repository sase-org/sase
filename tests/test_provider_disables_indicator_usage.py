"""ProviderDisablesIndicator usage badge composition tests."""

from __future__ import annotations

import pytest
from rich.color import Color

from sase.ace.tui.widgets._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
)
from sase.ace.tui.widgets._provider_usage_indicator import (
    usage_indicator_groups,
)
from sase.ace.tui.widgets.provider_disables_indicator import ProviderDisablesIndicator
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_SOFT,
    TemporaryProviderDisable,
)
from sase.llm_provider.provider_priority import TemporaryProviderPriority
from tests._provider_disables_indicator_helpers import (
    _CONSOLE,
    _FROZEN_NOW,
    _disable,
    _priority,
    _segments_with_offsets,
    _usage_groups,
    _usage_entry,
)


def test_usage_attention_renders_micro_total_beside_disable_when_budget_is_tiny() -> (
    None
):
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=None)},
        usage_groups=_usage_groups(),
        usage_budget=3,
        now=100.0,
    )

    assert "CLAUDE off ∞" in text.plain
    assert text.plain.strip().endswith("2")


def test_priority_pill_does_not_suppress_usage_attention() -> None:
    grok_group = _usage_groups()[0]
    text = ProviderDisablesIndicator._build_content(
        {},
        priority=_priority("codex", expires_at=3_820.0),
        usage_groups=(grok_group,),
        width=80,
        now=100.0,
    )

    assert "CODEX ★ priority 1h2m" in text.plain
    assert "🛰️ ! 0% 3d4h" in text.plain


def test_usage_tooltip_lists_attention_items() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {"claude": _disable("claude", expires_at=None, source="ace")},
        usage_groups=_usage_groups(),
        now=100.0,
    )

    assert tooltip is not None
    assert "CLAUDE - hard · manual, until cleared" in tooltip
    assert "Usage windows:" in tooltip
    assert "GROK - Week - all (key weekly) · 0% remaining" in tooltip
    assert "Providers · Usage" in tooltip


def test_selected_collector_failure_keeps_tooltip_prose_without_top_bar_triangle() -> (
    None
):
    groups = usage_indicator_groups(
        (
            _usage_entry(
                provider="codex",
                remaining_percent=12.0,
                collector_problem=True,
                display_attention="collection_problem",
            ),
        ),
        dark=True,
        now=_FROZEN_NOW,
    )
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {},
        usage_groups=groups,
        now=100.0,
    )
    content = ProviderDisablesIndicator._build_content(
        {},
        usage_groups=groups,
        dark=True,
        now=100.0,
    )

    assert tooltip is not None
    assert "collector is currently failing for this provider" in tooltip
    assert "⚠" not in content.plain


@pytest.mark.parametrize(
    ("disables", "priority", "accent"),
    [
        pytest.param(
            {"claude": _disable("claude")},
            None,
            PROVIDER_DISABLE_PALETTE.accent,
            id="hard-disable",
        ),
        pytest.param(
            {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)},
            None,
            PROVIDER_SOFT_DISABLE_PALETTE.accent,
            id="soft-disable",
        ),
        pytest.param(
            {},
            _priority("codex", expires_at=3_820.0),
            PROVIDER_PRIORITY_PALETTE.accent,
            id="priority",
        ),
        pytest.param({}, None, None, id="no-routing"),
    ],
)
def test_routing_prefix_keeps_its_style_and_usage_never_inherits_its_background(
    disables: dict[str, TemporaryProviderDisable],
    priority: TemporaryProviderPriority | None,
    accent: str | None,
) -> None:
    groups = usage_indicator_groups(
        [_usage_entry(provider="grok", remaining_percent=7.0)],
        dark=True,
        now=_FROZEN_NOW,
    )
    routing = ProviderDisablesIndicator._build_routing_content(
        disables, priority=priority, now=100.0
    )
    content = ProviderDisablesIndicator._build_content(
        disables,
        priority=priority,
        usage_groups=groups,
        dark=True,
        now=100.0,
    )

    assert content.plain.startswith(routing.plain)
    prefix_len = len(routing.plain)
    routing_segments = _segments_with_offsets(routing)
    content_segments = _segments_with_offsets(content)
    content_prefix = [seg for seg in content_segments if seg[1] <= prefix_len]
    assert content_prefix == routing_segments

    if accent is not None:
        accent_color = Color.parse(accent)
        for start, _end, style in content_segments:
            if start >= prefix_len:
                assert style is not None
                assert style.bgcolor != accent_color


def test_composed_percent_and_countdown_pairs_agree_after_composition() -> None:
    groups = usage_indicator_groups(
        [_usage_entry(provider="grok", remaining_percent=7.0)],
        dark=True,
        now=_FROZEN_NOW,
    )
    content = ProviderDisablesIndicator._build_content(
        {"claude": _disable("claude")},
        usage_groups=groups,
        dark=True,
        now=100.0,
    )

    segments = {segment.text: segment.style for segment in content.render(_CONSOLE)}
    percent_style = segments["7%"]
    countdown_style = segments["3d4h"]
    assert percent_style is not None
    assert countdown_style is not None
    assert percent_style.color == countdown_style.color
    assert percent_style.bold and countdown_style.bold


def test_collector_only_state_contributes_no_usage_content() -> None:
    groups = usage_indicator_groups(
        [],
        dark=True,
        now=100.0,
    )
    content = ProviderDisablesIndicator._build_content(
        {"claude": _disable("claude")},
        usage_groups=groups,
        dark=True,
        now=100.0,
    )

    assert content.plain == " CLAUDE off 15m "


def test_narrow_budget_collapses_then_wide_budget_restores_full_badge_packing() -> None:
    groups = usage_indicator_groups(
        [
            _usage_entry(provider="grok", remaining_percent=4.0),
            _usage_entry(provider="codex", remaining_percent=50.0),
            _usage_entry(provider="claude", remaining_percent=62.0),
        ],
        dark=True,
        now=_FROZEN_NOW,
    )
    full = ProviderDisablesIndicator._build_content(
        {}, usage_groups=groups, dark=True, now=100.0
    )
    narrow = ProviderDisablesIndicator._build_content(
        {}, usage_groups=groups, usage_budget=len(" usage 3"), dark=True, now=100.0
    )
    wide_again = ProviderDisablesIndicator._build_content(
        {}, usage_groups=groups, dark=True, now=100.0
    )

    assert narrow.plain.strip() == "usage 3"
    assert wide_again.plain == full.plain
    assert "🛰️" in full.plain and "🤖" in full.plain and "🎭" in full.plain

    tooltip = ProviderDisablesIndicator._build_tooltip(
        {}, usage_groups=groups, now=100.0
    )
    assert tooltip is not None
    for provider_upper in ("GROK", "CODEX", "CLAUDE"):
        assert provider_upper in tooltip
