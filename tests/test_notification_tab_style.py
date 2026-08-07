"""Every notification tab resolves to one stable, accessible color."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    SNOOZED_TAB_KEY,
    NotificationTagTab,
)
from sase.ace.tui.widgets import notification_tab_style
from sase.ace.tui.widgets.notification_tab_style import (
    DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS,
    _AUTO_PALETTE,
    _BUILTIN_TAB_COLORS,
    default_notification_tab_color,
    notification_indicator_max_counts,
    notification_tab_config_key,
    notification_tab_key,
    notification_tab_label,
    resolve_notification_tab_color,
)


@pytest.fixture(autouse=True)
def _no_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start every test from an empty ``ace`` block, cached per test."""
    _use_config(monkeypatch, {})
    yield
    notification_tab_style._configured_tab_colors_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()


def _use_config(monkeypatch: pytest.MonkeyPatch, ace: dict[str, Any]) -> None:
    """Point the resolver at *ace* with a token that busts its own cache."""
    notification_tab_style._configured_tab_colors_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()
    monkeypatch.setattr(
        notification_tab_style,
        "load_merged_config",
        lambda: {"ace": ace},
    )


def _tab(tag: str | None, *, color: str | None = None) -> NotificationTagTab:
    return NotificationTagTab(
        tag=tag,
        label="Label" if tag is None else tag,
        count=1,
        color=color,
    )


def test_a_configured_color_outranks_a_sender_declared_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"beads": {"color": "#010203"}}})

    assert resolve_notification_tab_color(_tab("beads", color="#AABBCC")) == "#010203"


def test_a_sender_declared_color_outranks_the_builtin_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch

    assert resolve_notification_tab_color(_tab("beads", color="#AABBCC")) == "#AABBCC"
    assert resolve_notification_tab_color(_tab("beads")) == _BUILTIN_TAB_COLORS["beads"]


def test_an_empty_configured_color_falls_through_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty string is the documented "restore the built-in" spelling."""
    _use_config(monkeypatch, {"notification_tabs": {"beads": {"color": ""}}})

    assert resolve_notification_tab_color(_tab("beads")) == _BUILTIN_TAB_COLORS["beads"]


@pytest.mark.parametrize("stored", ["red", "#FFF", "#GGGGGG", "  ", 7, None])
def test_a_junk_stored_color_degrades_instead_of_raising(stored: object) -> None:
    tab = NotificationTagTab(tag="beads", label="Beads", count=1, color=stored)  # type: ignore[arg-type]

    assert resolve_notification_tab_color(tab) == _BUILTIN_TAB_COLORS["beads"]


@pytest.mark.parametrize(
    ("tag", "config_key"),
    [
        (None, "general"),
        (SNOOZED_TAB_KEY, "snoozed"),
        (MUTED_TAB_KEY, "muted"),
        ("hitl", "hitl"),
        ("beads", "beads"),
    ],
)
def test_config_keys_use_the_user_facing_tab_names(
    tag: str | None,
    config_key: str,
) -> None:
    """Nobody should have to type ``__snoozed__`` in their config."""
    assert notification_tab_config_key(_tab(tag)) == config_key


def test_a_configured_snoozed_color_reaches_the_synthetic_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"snoozed": {"color": "#123456"}}})

    assert resolve_notification_tab_color(_tab(SNOOZED_TAB_KEY)) == "#123456"


def test_the_general_tab_keys_off_its_core_name() -> None:
    assert notification_tab_key(_tab(None)) == "general"
    assert resolve_notification_tab_color(_tab(None)) == _BUILTIN_TAB_COLORS["general"]


def test_an_unknown_tab_gets_a_stable_auto_palette_color() -> None:
    """The same tag must look the same across processes, not just renders."""
    first = resolve_notification_tab_color(_tab("plan-review"))

    assert first in _AUTO_PALETTE
    assert first == resolve_notification_tab_color(_tab("plan-review"))
    # Pinned so a palette or hash change cannot silently reshuffle every tag.
    assert first == "#FF87D7"


def test_the_auto_palette_never_collides_with_a_builtin_default() -> None:
    assert not set(_AUTO_PALETTE) & set(_BUILTIN_TAB_COLORS.values())


def test_distinct_tags_spread_across_the_auto_palette() -> None:
    tags = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]

    colors = {default_notification_tab_color(tag) for tag in tags}

    assert len(colors) > 1


def test_labels_are_width_bounded() -> None:
    tab = NotificationTagTab(tag="x", label="a" * 40, count=1)

    assert notification_tab_label(tab) == "a" * 15 + "..."


def test_the_indicator_max_counts_comes_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_indicator_max_counts": 2})

    assert notification_indicator_max_counts() == 2


@pytest.mark.parametrize("configured", [0, -1, "4", True, None])
def test_a_nonsense_indicator_max_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
    configured: object,
) -> None:
    _use_config(monkeypatch, {"notification_indicator_max_counts": configured})

    assert (
        notification_indicator_max_counts() == DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS
    )


def test_the_bundled_defaults_match_the_builtin_fallbacks() -> None:
    """The shipped config and the in-code fallbacks must not drift apart."""
    from sase.config.core import _load_default_config

    configured = _load_default_config()["ace"]["notification_tabs"]

    assert {key: value["color"] for key, value in configured.items()} == (
        _BUILTIN_TAB_COLORS
    )
