"""Deck panel chrome: deterministic Main accent and border-label budget."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.theme import Theme

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from sase.ace.tui.widgets.decks.panel_chrome import DeckPanelChromeMixin
from sase.ace.tui.widgets.decks.titles import CardTab, deck_title
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent
from tests.ace.tui.widgets.decks._deck_spread_test_helpers import pin_paged

_ROOT = Path(__file__).resolve().parents[5]

_STALE_SECONDARY = "#004578"
_THEME_SECONDARY = "#24837B"
_OTHER_SECONDARY = "#B4637A"


class _Chrome(DeckPanelChromeMixin):
    """Bare mixin host with just the attributes the resolver reads."""

    def __init__(self, app: object, width: int = 0) -> None:
        self.app = app
        self.size = SimpleNamespace(width=width)


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _register_themes(app: App[None]) -> None:
    for name, secondary in (
        ("chrome-a", _THEME_SECONDARY),
        ("chrome-b", _OTHER_SECONDARY),
    ):
        app.register_theme(
            Theme(name=name, primary="#111111", secondary=secondary, dark=True)
        )


def _rgb(hex_color: str) -> str:
    """Return ``hex_color`` as the ``rgb(r,g,b)`` form Textual markup uses."""
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgb({r},{g},{b})"


def _title_plain(panel: Any) -> str:
    return panel._border_title.plain


def _subtitle_plain(panel: Any) -> str:
    return panel._border_subtitle.plain


def test_main_accent_comes_from_current_theme_not_stale_variables() -> None:
    app = SimpleNamespace(
        current_theme=SimpleNamespace(secondary=_THEME_SECONDARY),
        theme_variables={"secondary": _STALE_SECONDARY},
    )

    assert _Chrome(app)._resolve_accent(DeckId.MAIN) == _THEME_SECONDARY


@pytest.mark.parametrize("secondary", [None, ""])
def test_main_accent_falls_back_when_theme_has_no_secondary(
    secondary: str | None,
) -> None:
    app = SimpleNamespace(
        current_theme=SimpleNamespace(secondary=secondary),
        theme_variables={"secondary": _STALE_SECONDARY},
    )

    assert _Chrome(app)._resolve_accent(DeckId.MAIN) == "#B48EAD"


def test_main_accent_falls_back_without_a_theme() -> None:
    assert _Chrome(SimpleNamespace())._resolve_accent(DeckId.MAIN) == "#B48EAD"


@pytest.mark.parametrize(
    ("size_width", "expected"),
    [(0, 80), (3, 1), (5, 1), (6, 2), (98, 94)],
)
def test_chrome_width_is_the_border_label_budget(
    size_width: int, expected: int
) -> None:
    assert _Chrome(SimpleNamespace(), width=size_width)._chrome_width() == expected


async def test_pilot_main_accent_ignores_a_stale_theme_variables_dict() -> None:
    app = _DetailApp()
    _register_themes(app)
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        app.theme = "chrome-a"
        await pilot.pause()
        app.theme_variables["secondary"] = _STALE_SECONDARY
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)

        assert panel._resolve_accent(DeckId.MAIN) == _THEME_SECONDARY
        panel.refresh_chrome()
        assert _rgb(_THEME_SECONDARY) in str(panel.border_title)
        assert _rgb(_STALE_SECONDARY) not in str(panel.border_title)


async def test_pilot_theme_switch_recolors_chrome_and_spread_separators(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    _register_themes(app)
    async with app.run_test(size=(100, 30)) as pilot:
        app.theme = "chrome-a"
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        assert panel.main_view.render_mode is RenderMode.SPREAD
        assert panel.main_view._last_render_key[-1] == _THEME_SECONDARY
        assert _rgb(_THEME_SECONDARY) in str(panel.border_title)

        app.theme = "chrome-b"
        await pilot.pause()
        await pilot.pause()

        assert panel.main_view._last_render_key[-1] == _OTHER_SECONDARY
        assert _rgb(_OTHER_SECONDARY) in str(panel.border_title)
        assert _rgb(_THEME_SECONDARY) not in str(panel.border_title)


async def test_pilot_title_within_four_cells_of_width_drops_to_compact(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        tabs = tuple(CardTab(c.card_id, c.title) for c in panel._main_document.cards)
        assert len(tabs) >= 2
        full = deck_title(
            DeckId.MAIN, tabs, 0, width=0, accent="#fff", focused=True
        ).plain
        full_len = len(full)

        # Content width == full title length: the old fit check accepted the
        # full tier, but Textual would clip it to ``size.width - 4`` cells.
        panel.styles.width = full_len + 2
        await pilot.pause()
        assert panel.size.width == full_len
        panel.refresh_chrome()

        title = _title_plain(panel)
        assert "…" not in title
        assert title != full
        assert title.startswith("◆ MAIN ┃ ‹ 1/")
        assert len(title) <= panel.size.width - 4


async def test_pilot_subtitle_is_trimmed_to_the_label_budget(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        panel.refresh_chrome()
        wide = _subtitle_plain(panel)

        panel.styles.width = len(wide) + 2
        await pilot.pause()
        assert panel.size.width == len(wide)
        panel.refresh_chrome()

        assert len(_subtitle_plain(panel)) <= panel.size.width - 4
