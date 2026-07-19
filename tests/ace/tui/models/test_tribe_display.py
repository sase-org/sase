"""Per-tribe Agents-panel display configuration tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from rich.cells import cell_len

import sase.ace.tui.models.tribe_display as display


@pytest.fixture(autouse=True)
def _clear_display_cache() -> Iterator[None]:
    display._tribe_displays_for_token.cache_clear()
    yield
    display._tribe_displays_for_token.cache_clear()


def _install_config(
    monkeypatch: pytest.MonkeyPatch,
    tribes: dict[str, Any],
    *,
    token: tuple[Any, ...] = ("config", 1),
) -> None:
    monkeypatch.setattr(
        display,
        "load_merged_config",
        lambda: {"ace": {"tribes": tribes}},
    )
    monkeypatch.setattr(display, "current_config_token", lambda: token)


def test_default_panel_mapping_and_unknown_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config(
        monkeypatch,
        {
            "default": {"icon": " 🏠 "},
            "chop": {"icon": "🪓", "initially_expanded": False},
        },
    )

    assert display.tribe_display_for(None) == display._TribeDisplay(icon="🏠")
    assert display.tribe_display_for("chop") == display._TribeDisplay(
        icon="🪓", initially_expanded=False
    )
    assert display.tribe_display_for("custom") == display.DEFAULT_TRIBE_DISPLAY


def test_empty_and_hostile_icons_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config(
        monkeypatch,
        {
            "empty": {"icon": ""},
            "newline": {"icon": "x\ny"},
            "escape": {"icon": "\x1b[31m"},
            "long": {"icon": "abcdefghijk"},
        },
    )

    assert display.tribe_display_for("empty").icon == ""
    assert display.tribe_display_for("newline").icon == ""
    assert display.tribe_display_for("escape").icon == ""
    bounded = display.tribe_display_for("long").icon
    assert bounded == "abcd"
    assert cell_len(bounded) <= display.MAX_TRIBE_ICON_CELLS


def test_resolution_is_memoized_per_config_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = [1]
    loads = 0

    def _load() -> dict[str, Any]:
        nonlocal loads
        loads += 1
        return {"ace": {"tribes": {"chop": {"icon": str(loads)}}}}

    monkeypatch.setattr(display, "load_merged_config", _load)
    monkeypatch.setattr(
        display,
        "current_config_token",
        lambda: ("config", token[0]),
    )

    assert display.tribe_display_for("chop").icon == "1"
    assert display.tribe_display_for("chop").icon == "1"
    assert display.tribe_display_for("other").icon == ""
    assert loads == 1

    token[0] = 2
    assert display.tribe_display_for("chop").icon == "2"
    assert loads == 2


def test_effective_collapse_precedence_does_not_materialize_seeded_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config(
        monkeypatch,
        {
            "chop": {"initially_expanded": False},
            "research": {"initially_expanded": True},
            "untouched": {"initially_expanded": False},
        },
    )
    collapsed_intent = {"research"}
    expanded_intent = {"chop"}

    effective = display.effective_collapsed_panel_keys(
        {"chop", "research", "untouched", "new"},
        collapsed_intent=collapsed_intent,
        expanded_intent=expanded_intent,
    )

    assert effective == {"research", "untouched"}
    assert collapsed_intent == {"research"}
    assert expanded_intent == {"chop"}


def test_explicit_intent_survives_later_config_flip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = [1]
    configs = {
        1: {
            "chop": {"initially_expanded": False},
            "research": {"initially_expanded": True},
        },
        2: {
            "chop": {"initially_expanded": True},
            "research": {"initially_expanded": False},
        },
    }
    monkeypatch.setattr(
        display,
        "load_merged_config",
        lambda: {"ace": {"tribes": configs[token[0]]}},
    )
    monkeypatch.setattr(
        display,
        "current_config_token",
        lambda: ("config", token[0]),
    )

    for current_token in (1, 2):
        token[0] = current_token
        assert display.effective_collapsed_panel_keys(
            {"chop", "research"},
            collapsed_intent={"research"},
            expanded_intent={"chop"},
        ) == {"research"}


def test_newly_appearing_panel_uses_current_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config(
        monkeypatch,
        {"later": {"initially_expanded": False}},
    )

    assert display.effective_collapsed_panel_keys({"first"}) == set()
    assert display.effective_collapsed_panel_keys({"first", "later"}) == {"later"}
