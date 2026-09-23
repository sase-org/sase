"""ProviderDisablesIndicator routing pill and tooltip tests."""

from __future__ import annotations

from sase.ace.tui.widgets._override_pill import (
    PROVIDER_SOFT_DISABLE_PALETTE,
)
from sase.ace.tui.widgets.provider_disables_indicator import (
    ProviderDisablesIndicator,
    _ACTIVE_STYLE,
)
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_MODE_SOFT
from tests._provider_disables_indicator_helpers import (
    _disable,
)


def test_group_label_is_disabled() -> None:
    assert ProviderDisablesIndicator.GROUP_LABEL == "disabled"


def test_no_provider_disables_renders_empty() -> None:
    assert ProviderDisablesIndicator._build_content({}).plain == ""


def test_single_provider_disable_renders_countdown() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=3_820.0)},
        now=100.0,
    )

    assert text.plain == " CLAUDE off 1h2m "
    assert str(text.style) == _ACTIVE_STYLE


def test_multi_day_provider_disable_renders_day_unit() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"codex": _disable("codex", expires_at=100.0 + 3 * 86400 + 4 * 3600)},
        now=100.0,
    )

    assert text.plain == " CODEX off 3d4h "


def test_single_provider_disable_until_cleared_renders_infinity() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=None)},
        now=100.0,
    )

    assert text.plain == " CLAUDE off ∞ "


def test_multiple_provider_disables_name_first_provider_and_count_rest() -> None:
    text = ProviderDisablesIndicator._build_content(
        {
            "grok": _disable("grok", expires_at=3_820.0),
            "claude": _disable("claude", expires_at=None),
            "codex": _disable("codex", expires_at=5_000.0),
        },
        now=100.0,
    )

    assert text.plain == " CLAUDE +2 "


def test_expired_provider_disable_renders_empty() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=99.0)},
        now=100.0,
    )

    assert text.plain == ""


def test_tooltip_lists_active_provider_disables() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {
            "claude": _disable("claude", expires_at=None, source="ace"),
            "codex": _disable("codex", expires_at=3_820.0, source="usage_limit"),
            "grok": _disable("grok", expires_at=4_000.0, source="external_plugin"),
        },
        now=100.0,
    )

    assert tooltip == (
        "Disabled providers:\n"
        "CLAUDE - hard · manual, until cleared\n"
        "CODEX - hard · usage-limit automatic, 1h2m left\n"
        "GROK - hard · external plugin, 1h5m left\n"
        "Hard disables skip the provider on new launches; "
        "running processes continue.\n"
        "Pools spare a soft provider while another member can cover; "
        "|| fallbacks and explicit %model still use it.\n"
        "Press ,m for Config > Launch."
    )


def test_tooltip_renders_day_unit_for_multi_day_disable() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {
            "codex": _disable(
                "codex",
                expires_at=100.0 + 3 * 86400 + 4 * 3600,
                source="usage_limit",
            ),
        },
        now=100.0,
    )

    assert tooltip == (
        "Disabled providers:\n"
        "CODEX - hard · usage-limit automatic, 3d4h left\n"
        "Hard disables skip the provider on new launches; "
        "running processes continue.\n"
        "Pools spare a soft provider while another member can cover; "
        "|| fallbacks and explicit %model still use it.\n"
        "Press ,m for Config > Launch."
    )


def test_soft_provider_disable_renders_soft_countdown() -> None:
    text = ProviderDisablesIndicator._build_content(
        {
            "claude": _disable(
                expires_at=3_820.0,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            )
        },
        now=100.0,
    )

    assert text.plain == " CLAUDE soft 1h2m "
    assert str(text.style) == PROVIDER_SOFT_DISABLE_PALETTE.base_style


def test_mixed_provider_disables_prefer_hard_in_pill() -> None:
    text = ProviderDisablesIndicator._build_content(
        {
            "claude": _disable(
                "claude",
                expires_at=None,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
            "codex": _disable("codex", expires_at=5_000.0),
        },
        now=100.0,
    )

    assert text.plain == " CODEX +1 "
    assert str(text.style) == _ACTIVE_STYLE


def test_soft_only_multiple_provider_disables_use_soft_palette() -> None:
    text = ProviderDisablesIndicator._build_content(
        {
            "claude": _disable(
                "claude",
                expires_at=None,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
            "codex": _disable(
                "codex",
                expires_at=5_000.0,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
        },
        now=100.0,
    )

    assert text.plain == " CLAUDE +1 "
    assert str(text.style) == PROVIDER_SOFT_DISABLE_PALETTE.base_style


def test_tooltip_lists_soft_mode() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {
            "claude": _disable(
                "claude",
                expires_at=None,
                source="ace",
                mode=PROVIDER_DISABLE_MODE_SOFT,
            )
        },
        now=100.0,
    )

    assert tooltip is not None
    assert "CLAUDE - soft · manual, until cleared" in tooltip
    assert "Pools spare a soft provider" in tooltip
