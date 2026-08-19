"""Every notification tab resolves to one stable color and one icon."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from rich.cells import cell_len

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
    _BUILTIN_TAB_ICONS,
    _KIND_TAB_ICONS,
    _LAST_RESORT_TAB_ICON,
    _default_notification_tab_color,
    notification_indicator_max_counts,
    _notification_tab_config_key,
    _notification_tab_key,
    notification_tab_label,
    resolve_notification_tab_color,
    resolve_notification_tab_icons,
)
from sase.bead_type_presentation import bead_type_presentation
from sase.task_type_presentation import task_type_presentation


@pytest.fixture(autouse=True)
def _no_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start every test from an empty ``ace`` block, cached per test."""
    _use_config(monkeypatch, {})
    yield
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()


def _use_config(monkeypatch: pytest.MonkeyPatch, ace: dict[str, Any]) -> None:
    """Point the resolver at *ace* with a token that busts its own cache."""
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()
    monkeypatch.setattr(
        notification_tab_style,
        "load_merged_config",
        lambda: {"ace": ace},
    )


def _resolve_notification_tab_icon(tab: NotificationTagTab) -> str:
    return resolve_notification_tab_icons((tab,))[tab.tag]


def _tab(
    tag: str | None,
    *,
    color: str | None = None,
    icon: str | None = None,
    kind: str = "",
) -> NotificationTagTab:
    return NotificationTagTab(
        tag=tag,
        label="Label" if tag is None else tag,
        count=1,
        kind=kind,
        color=color,
        icon=icon,
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


def test_flag_notification_tag_uses_flag_task_type_presentation() -> None:
    presentation = task_type_presentation("flag")
    tab = _tab("flag", kind="tag")

    assert resolve_notification_tab_color(tab) == presentation.accent_color
    assert _resolve_notification_tab_icon(tab) == presentation.glyph


def test_a_task_type_slug_notification_tag_uses_task_type_presentation() -> None:
    presentation = task_type_presentation("flake")
    tab = _tab("flake", kind="tag")

    assert resolve_notification_tab_color(tab) == presentation.accent_color
    assert _resolve_notification_tab_icon(tab) == presentation.glyph


def test_a_tag_matching_no_task_type_slug_never_borrows_task_type_styling() -> None:
    tab = _tab("not-a-real-task-type", kind="tag")

    assert resolve_notification_tab_color(tab) == _default_notification_tab_color(
        "not-a-real-task-type"
    )


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
    assert _notification_tab_config_key(_tab(tag)) == config_key


def test_a_configured_snoozed_color_reaches_the_synthetic_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"snoozed": {"color": "#123456"}}})

    assert resolve_notification_tab_color(_tab(SNOOZED_TAB_KEY)) == "#123456"


def test_the_general_tab_keys_off_its_core_name() -> None:
    assert _notification_tab_key(_tab(None)) == "general"
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

    colors = {_default_notification_tab_color(tag) for tag in tags}

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
    assert {key: value["icon"] for key, value in configured.items()} == (
        _BUILTIN_TAB_ICONS
    )


def test_a_configured_icon_outranks_a_sender_declared_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"beads": {"icon": "★"}}})

    assert _resolve_notification_tab_icon(_tab("beads", icon="✦")) == "★"


def test_a_sender_declared_icon_outranks_the_builtin_default() -> None:
    assert _resolve_notification_tab_icon(_tab("beads", icon="✦")) == "✦"
    assert _resolve_notification_tab_icon(_tab("beads")) == _BUILTIN_TAB_ICONS["beads"]


def test_a_builtin_icon_outranks_the_kind_default() -> None:
    """A known key keeps its own glyph even when the kind offers one."""
    tab = _tab("beads", kind="panel")

    assert _KIND_TAB_ICONS["panel"] != _BUILTIN_TAB_ICONS["beads"]
    assert _resolve_notification_tab_icon(tab) == _BUILTIN_TAB_ICONS["beads"]


def test_a_kind_icon_outranks_the_last_resort() -> None:
    """A tab ACE has never heard of still says something about itself."""
    assert (
        _resolve_notification_tab_icon(_tab("deployments", kind="panel"))
        == (_KIND_TAB_ICONS["panel"])
    )
    assert (
        _resolve_notification_tab_icon(_tab("plan-review", kind="tag"))
        == (_KIND_TAB_ICONS["tag"])
    )


def test_a_tab_with_no_kind_at_all_falls_to_the_last_resort() -> None:
    assert _resolve_notification_tab_icon(_tab("deployments")) == _LAST_RESORT_TAB_ICON


def test_two_tag_tabs_resolve_to_distinct_icons() -> None:
    tabs = [_tab("axe", kind="tag"), _tab("done", kind="tag")]

    icons = resolve_notification_tab_icons(tabs)

    assert icons["axe"] != icons["done"]
    assert {cell_len(icon) for icon in icons.values()} == {1}


def test_shared_initial_tag_tabs_still_resolve_to_distinct_icons() -> None:
    tabs = [_tab("axe", kind="tag"), _tab("agents", kind="tag")]

    icons = resolve_notification_tab_icons(tabs)

    assert icons["axe"] != icons["agents"]


def test_explicit_icon_duplicates_are_never_rederived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"human": {"icon": "★"}}})

    icons = resolve_notification_tab_icons(
        [_tab("human", kind="tag"), _tab("sender", icon="★", kind="tag")]
    )

    assert icons["human"] == "★"
    assert icons["sender"] == "★"


def test_a_builtin_icon_is_not_rederived_when_an_explicit_icon_matches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_icon = _BUILTIN_TAB_ICONS["beads"]
    _use_config(monkeypatch, {"notification_tabs": {"custom": {"icon": beads_icon}}})

    icons = resolve_notification_tab_icons([_tab("beads"), _tab("custom", kind="tag")])

    assert icons["beads"] == beads_icon
    assert icons["custom"] == beads_icon


def test_key_exhaustion_keeps_the_generic_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"taken": {"icon": "a"}}})

    icons = resolve_notification_tab_icons(
        [_tab("taken"), _tab("first", kind="tag"), _tab("a", kind="tag")]
    )

    assert icons["taken"] == "a"
    assert icons["first"] == _KIND_TAB_ICONS["tag"]
    assert icons["a"] == _KIND_TAB_ICONS["tag"]


def test_icon_disambiguation_is_order_stable() -> None:
    tabs = [_tab("axe", kind="tag"), _tab("done", kind="tag")]

    first = resolve_notification_tab_icons(tabs)
    second = resolve_notification_tab_icons(tabs)
    extended = resolve_notification_tab_icons([*tabs, _tab("later", kind="tag")])

    assert first == second
    assert extended["axe"] == first["axe"]
    assert extended["done"] == first["done"]


def test_an_empty_configured_icon_falls_through_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty string is the documented "restore the built-in" spelling."""
    _use_config(monkeypatch, {"notification_tabs": {"beads": {"icon": ""}}})

    assert _resolve_notification_tab_icon(_tab("beads")) == _BUILTIN_TAB_ICONS["beads"]


@pytest.mark.parametrize("configured", ["ab", " ◈ ", "\n", "x" * 40, 7, None, "🇺🇸🇬🇧"])
def test_a_junk_configured_icon_falls_through_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
    configured: object,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"beads": {"icon": configured}}})

    assert _resolve_notification_tab_icon(_tab("beads")) == _BUILTIN_TAB_ICONS["beads"]


@pytest.mark.parametrize("stored", ["ab", "  ", 7, ""])
def test_a_junk_stored_icon_degrades_instead_of_raising(stored: object) -> None:
    tab = NotificationTagTab(tag="beads", label="Beads", count=1, icon=stored)  # type: ignore[arg-type]

    assert _resolve_notification_tab_icon(tab) == _BUILTIN_TAB_ICONS["beads"]


def test_no_icon_wide_enough_to_blow_out_the_top_bar_survives() -> None:
    """ACE's own width guard, beyond what the gate path cares about."""
    from rich.cells import cell_len

    wide = "你你"
    assert cell_len(wide) > 2

    assert notification_tab_style._sanitize_icon(wide) == ""


def test_a_configured_snoozed_icon_reaches_the_synthetic_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"snoozed": {"icon": "★"}}})

    assert _resolve_notification_tab_icon(_tab(SNOOZED_TAB_KEY)) == "★"


def test_every_bundled_glyph_is_single_cell() -> None:
    """A two-cell glyph would make every chip in the top bar wider."""
    glyphs = set(_BUILTIN_TAB_ICONS.values()) | set(_KIND_TAB_ICONS.values())

    assert {glyph for glyph in glyphs if cell_len(glyph) != 1} == set()
    assert cell_len(_LAST_RESORT_TAB_ICON) == 1


def test_sase_owned_default_icons_are_pairwise_distinct() -> None:
    glyphs = [
        *_BUILTIN_TAB_ICONS.values(),
        *_KIND_TAB_ICONS.values(),
        _LAST_RESORT_TAB_ICON,
    ]

    assert len(glyphs) == len(set(glyphs))
