"""Prompt search match-count readout tests."""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.color import Color as RichColor
from rich.color import ColorSystem
from rich.style import Style
from textual.app import App, ComposeResult
from textual.color import Color
from textual.theme import BUILTIN_THEMES
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets._prompt_search_readout import (
    _FALLBACK_COLORS,
    _contrast_ratio,
    PromptSearchReadout,
    format_search_count_segment,
    format_search_readout,
    _display_query,
    _readout_sigil,
    _search_readout_palette,
    _theme_var,
    stack_match_position,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _PromptSearchReadoutApp(App[None]):
    """Host a prompt bar and app-level slash/question-mark bindings."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("slash", "edit_query", "Edit Query"),
        ("question_mark", "show_help", "Help"),
    ]

    def __init__(
        self,
        initial_value: str = "",
        *,
        initial_panes: list[str] | None = None,
        initial_selected_pane: int | None = None,
    ) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._initial_panes = initial_panes
        self._initial_selected_pane = initial_selected_pane
        self.notifications: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            initial_panes=self._initial_panes,
            initial_selected_pane=self._initial_selected_pane,
        )

    def action_edit_query(self) -> None:
        pass

    def action_show_help(self) -> None:
        pass

    def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.notifications.append(message)


def _search_panel(bar: PromptInputBar) -> Static:
    return bar.query_one("#prompt-search-command", Static)


def _subtitle_plain(bar: PromptInputBar) -> str:
    return bar._render_subtitle(bar._subtitle_base).plain


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


def _variables(
    *,
    surface: str = "#1E1E1E",
    foreground: str = "#E0E0E0",
    background: str = "#121212",
    accent: str = "#6B4FBB",
    warning: str = "#FFA62B",
) -> dict[str, str]:
    return {
        "surface": surface,
        "foreground": foreground,
        "background": background,
        "accent": accent,
        "warning": warning,
    }


def _synthetic_variables(value: str) -> dict[str, str]:
    return _variables(
        surface=value,
        foreground=value,
        background=value,
        accent=value,
        warning=value,
    )


def _theme_variables(name: str) -> dict[str, str]:
    theme = BUILTIN_THEMES[name]
    return {**theme.to_color_system().generate(), **theme.variables}


def _rich_to_textual(color: RichColor) -> Color:
    truecolor = color.get_truecolor()
    return Color(truecolor.red, truecolor.green, truecolor.blue)


def _style_colors(style: Style) -> tuple[RichColor, RichColor]:
    assert style.color is not None
    assert style.bgcolor is not None
    return style.color, style.bgcolor


def _xterm_256_index(color: RichColor) -> int | None:
    return color.downgrade(ColorSystem.EIGHT_BIT).number


_THEME_VARIABLE_CASES = [
    pytest.param(name, _theme_variables(name), id=name) for name in BUILTIN_THEMES
] + [
    pytest.param("pure-black", _synthetic_variables("#000000"), id="pure-black"),
    pytest.param("pure-white", _synthetic_variables("#FFFFFF"), id="pure-white"),
]


@pytest.mark.parametrize(
    ("direction", "whole_word", "expected"),
    [
        ("forward", False, "/"),
        ("reverse", False, "?"),
        ("forward", True, "*"),
        ("reverse", True, "#"),
    ],
)
def test_readout_sigil(direction: str, whole_word: bool, expected: str) -> None:
    assert _readout_sigil(direction, whole_word) == expected


def test_display_query_sanitizes_and_elides_by_cell_width() -> None:
    assert _display_query("a\nb\tc\x01") == "a↵b⇥c·"

    value = _display_query("alpha你好omega", max_cells=8)

    assert cell_len(value) <= 8
    assert value.endswith("…")
    assert value.startswith("alpha")


@pytest.mark.parametrize(
    ("counts", "origin", "local", "expected"),
    [
        ((3,), 0, 1, (2, 3)),
        ((2, 0, 3), 2, 1, (4, 5)),
        ((2, 0, 3), 1, None, (None, 5)),
        ((0, 0), 0, None, (None, 0)),
    ],
)
def test_stack_match_position(
    counts: tuple[int, ...],
    origin: int,
    local: int | None,
    expected: tuple[int | None, int],
) -> None:
    assert stack_match_position(counts, origin, local) == expected


def test_format_search_readout_plain_text_and_count_only() -> None:
    readout = PromptSearchReadout(
        query="alpha",
        direction="forward",
        whole_word=False,
        ordinal=2,
        total=3,
        pane_text="alpha beta alpha",
    )

    assert (
        format_search_readout(readout, variables=_variables()).plain == " /alpha  2/3 "
    )
    assert (
        format_search_readout(
            readout,
            variables=_variables(),
            include_query=False,
        ).plain
        == " 2/3 "
    )


def test_search_readout_count_background_uses_theme_warning() -> None:
    readout = PromptSearchReadout(
        query="alpha",
        direction="forward",
        whole_word=False,
        ordinal=2,
        total=3,
        pane_text="alpha beta alpha",
    )
    variables = _variables(warning="#FFA62B")

    count = format_search_readout(readout, variables=variables, include_query=False)

    assert count.spans
    assert count.spans[0].style.bgcolor == RichColor.parse(variables["warning"])


def test_query_and_count_backgrounds_differ_when_theme_reuses_colors() -> None:
    palette = _search_readout_palette(_variables(accent="#FFA62B", warning="#FFA62B"))

    assert palette.query.bgcolor != palette.ordinal.bgcolor


def test_flexoki_count_ink_avoids_base16_black_regression() -> None:
    palette = _search_readout_palette(_theme_variables("flexoki"))
    count_fg, _count_bg = _style_colors(palette.ordinal)

    assert count_fg != RichColor.parse("#000000")
    assert count_fg == RichColor.parse("#100F0F")
    assert _xterm_256_index(count_fg) != 16


@pytest.mark.parametrize(("name", "variables"), _THEME_VARIABLE_CASES)
def test_palette_colors_avoid_base16_repurposed_indices(
    name: str,
    variables: dict[str, str],
) -> None:
    palette = _search_readout_palette(variables)

    for style in (palette.query, palette.sigil, palette.ordinal, palette.total):
        for color in _style_colors(style):
            assert _xterm_256_index(color) not in range(16, 22), name


@pytest.mark.parametrize(("name", "variables"), _THEME_VARIABLE_CASES)
def test_palette_contrast_budget(name: str, variables: dict[str, str]) -> None:
    palette = _search_readout_palette(variables)
    query_fg, query_bg = _style_colors(palette.query)
    sigil_fg, sigil_bg = _style_colors(palette.sigil)
    count_fg, count_bg = _style_colors(palette.ordinal)

    assert (
        _contrast_ratio(_rich_to_textual(query_fg), _rich_to_textual(query_bg)) >= 4.5
    ), name
    assert (
        _contrast_ratio(_rich_to_textual(sigil_fg), _rich_to_textual(sigil_bg)) >= 3.0
    ), name
    assert (
        _contrast_ratio(_rich_to_textual(count_fg), _rich_to_textual(count_bg)) >= 4.0
    ), name


def test_count_segment_styles_ordinal_bold_total_regular() -> None:
    count = format_search_count_segment(12, 137, variables=_variables())

    assert count.plain == " 12/137 "
    ordinal_span, total_span = count.spans
    assert count.plain[ordinal_span.start : ordinal_span.end] == " 12"
    assert ordinal_span.style.bold is True
    assert count.plain[total_span.start : total_span.end] == "/137 "
    assert total_span.style.bold is None


@pytest.mark.parametrize(
    "variables",
    [
        {},
        {"surface": "auto 87%"},
        {"surface": "rgba(1,2,3,0.5)"},
        {"surface": "ansi_default"},
    ],
)
def test_theme_var_falls_back_for_missing_unparseable_translucent_and_ansi(
    variables: dict[str, str],
) -> None:
    assert _theme_var(variables, "surface").hex == _FALLBACK_COLORS["surface"]


async def test_typing_count_moves_to_bar_pill_and_repeats_update_it() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha beta alpha")

    async with app.run_test(size=(88, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)

        await pilot.press("slash", "a", "l", "p", "h", "a")
        await pilot.pause()

        panel = _search_panel(bar)
        panel_plain = panel.render().plain
        assert "2/3" in panel_plain
        assert "[2/3]" not in panel_plain
        assert "/alpha" not in _subtitle_plain(bar)

        await pilot.press("enter")
        await pilot.pause()

        plain = _subtitle_plain(bar)
        assert "/alpha" in plain
        assert plain.index("2/3") < plain.index("Ln ")

        await pilot.press("n")
        await pilot.pause()
        assert "3/3" in _subtitle_plain(bar)

        await pilot.press("N")
        await pilot.pause()
        assert "2/3" in _subtitle_plain(bar)

        await pilot.press("n", "n")
        await pilot.pause()
        assert "1/3" in _subtitle_plain(bar)
        assert app.notifications[-1] == "search hit BOTTOM, continuing at TOP"


async def test_search_readout_clears_and_safety_net_ignores_unchanged_text() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha")

    async with app.run_test(size=(88, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert "/alpha" in _subtitle_plain(bar)
        text_area.post_message(TextArea.Changed(text_area))
        await pilot.pause()
        assert "/alpha" in _subtitle_plain(bar)

        text_area.load_text("beta only")
        await pilot.pause()
        assert "/alpha" not in _subtitle_plain(bar)
        assert text_area._search_match_spans == ()
        assert not any(
            name.startswith("search.") for name in _highlight_names(text_area)
        )

        await pilot.press("n")
        await pilot.pause()
        assert "pattern not found" in app.notifications[-1]


async def test_search_readout_clears_on_escape_insert_edit_and_new_search() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha")

    async with app.run_test(size=(88, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()
        assert "/alpha" in _subtitle_plain(bar)

        await pilot.press("escape")
        await pilot.pause()
        assert "/alpha" not in _subtitle_plain(bar)

        await pilot.press("n", "i")
        await pilot.pause()
        assert "/alpha" not in _subtitle_plain(bar)

        await pilot.press("escape", "n")
        await pilot.pause()
        assert "/alpha" in _subtitle_plain(bar)

        await pilot.press("x")
        await pilot.pause()
        assert "/alpha" not in _subtitle_plain(bar)

        await pilot.press("slash", "a")
        await pilot.pause()
        assert bar._search_command_visible
        assert "/alpha" not in _subtitle_plain(bar)


async def test_word_and_reverse_search_sigils() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha")

    async with app.run_test(size=(88, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()
        assert "*alpha" in _subtitle_plain(bar)

        await pilot.press("escape")
        text_area.cursor_location = (0, 11)
        await pilot.press("#")
        await pilot.pause()
        assert "#alpha" in _subtitle_plain(bar)

        await pilot.press("escape")
        text_area.cursor_location = (0, 0)
        await pilot.press("g", "*")
        await pilot.pause()
        assert "/alpha" in _subtitle_plain(bar)

        await pilot.press("question_mark", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()
        assert "?alpha" in _subtitle_plain(bar)


async def test_multi_pane_stack_global_counts_and_no_local_match_status() -> None:
    app = _PromptSearchReadoutApp(
        initial_panes=["alpha x alpha", "alpha"],
        initial_selected_pane=1,
    )

    async with app.run_test(size=(88, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")

        await pilot.press("slash", "a", "l", "p", "h", "a")
        await pilot.pause()
        assert "3/3" in _search_panel(bar).render().plain

        await pilot.press("enter")
        await pilot.pause()
        assert "3/3" in _subtitle_plain(bar)

        await pilot.press("n")
        await pilot.pause()
        assert bar._stack.selected_index == 0
        assert "1/3" in _subtitle_plain(bar)

        await pilot.press("n")
        await pilot.pause()
        assert "2/3" in _subtitle_plain(bar)

        bar.focus_item(1)
        await pilot.pause()
        await pilot.press("slash", "x")
        await pilot.pause()
        assert "no match in this pane · 1 in stack" in _search_panel(bar).render().plain


async def test_narrow_subtitle_keeps_count_and_cursor_readout() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha")

    async with app.run_test(size=(48, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        plain = _subtitle_plain(bar)
        assert "2/2" in plain
        assert "Ln " in plain


async def test_search_panel_subtitle_renders_literal_enter_hint() -> None:
    app = _PromptSearchReadoutApp("alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape", "slash", "a")
        await pilot.pause()

        subtitle = _search_panel(bar).border_subtitle
        plain = subtitle.plain if hasattr(subtitle, "plain") else str(subtitle)
        assert "[enter] accept" in plain
