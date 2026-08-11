"""Interactive tests for vim ``*`` / ``#`` / ``g*`` / ``g#`` prompt search."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets._vim_search import PromptSearchQuery
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _StarSearchApp(App[None]):
    """Host a prompt bar and the app-level bindings ``*`` / ``#`` could leak to."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("asterisk", "open_saved_query_picker", "Saved Queries"),
        ("number_sign", "open_config_center", "SASE Admin Center"),
    ]

    def __init__(self, initial_value: str) -> None:
        super().__init__()
        self._initial_value = initial_value
        self.open_saved_query_picker_count = 0
        self.open_config_center_count = 0
        self.notifications: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value)

    def action_open_saved_query_picker(self) -> None:
        self.open_saved_query_picker_count += 1

    def action_open_config_center(self) -> None:
        self.open_config_center_count += 1

    def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.notifications.append(message)


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


async def test_star_jumps_to_next_occurrence_and_records_register() -> None:
    app = _StarSearchApp("foo bar foo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 8)
        assert any(name.startswith("search.") for name in _highlight_names(text_area))
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="foo",
            direction="forward",
            whole_word=True,
            smartcase=False,
        )
        assert app.open_saved_query_picker_count == 0


async def test_star_matches_whole_word_only() -> None:
    app = _StarSearchApp("log login catalog log")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 18)


async def test_g_star_matches_substring() -> None:
    app = _StarSearchApp("log login catalog log")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("g", "*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 4)
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="log",
            direction="forward",
            whole_word=False,
            smartcase=False,
        )

        text_area.cursor_location = (0, 0)
        await pilot.press("2", "g", "*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 14)


async def test_hash_searches_backward_for_whole_word() -> None:
    app = _StarSearchApp("cat one cat two cat three cat")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 16)

        await pilot.press("#")
        await pilot.pause()

        assert text_area.cursor_location == (0, 8)
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="cat",
            direction="reverse",
            whole_word=True,
            smartcase=False,
        )
        assert app.open_config_center_count == 0


async def test_counted_star_honors_count() -> None:
    app = _StarSearchApp("cat one cat two cat three cat")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("3", "*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 26)


async def test_n_after_star_keeps_whole_word_and_case_sensitive_semantics() -> None:
    app = _StarSearchApp("log login catalog log")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()
        assert text_area.cursor_location == (0, 18)

        await pilot.press("n")
        await pilot.pause()

        # Whole-word semantics must survive into ``n``: a plain substring
        # search would land on "login" at column 4 instead of wrapping.
        assert text_area.cursor_location == (0, 0)
        assert app.notifications[-1] == "search hit BOTTOM, continuing at TOP"


async def test_star_on_uppercase_word_skips_lowercase_match() -> None:
    app = _StarSearchApp("Foo foo Foo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 8)


async def test_star_on_lowercase_word_skips_uppercase_match() -> None:
    app = _StarSearchApp("Foo foo Foo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 4)

        await pilot.press("*")
        await pilot.pause()

        # Only one case-sensitive match exists, so the single occurrence wraps
        # onto itself rather than reaching either "Foo".
        assert text_area.cursor_location == (0, 4)
        assert app.notifications[-1] == "search hit BOTTOM, continuing at TOP"


async def test_star_mid_word_and_on_first_char_reach_same_destination() -> None:
    text = "cat one cat two cat three cat"

    app_first_char = _StarSearchApp(text)
    async with app_first_char.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app_first_char.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)
        await pilot.press("*")
        await pilot.pause()
        first_char_destination = text_area.cursor_location

    app_mid_word = _StarSearchApp(text)
    async with app_mid_word.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app_mid_word.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)
        await pilot.press("*")
        await pilot.pause()
        mid_word_destination = text_area.cursor_location

    assert first_char_destination == mid_word_destination == (0, 8)


async def test_star_from_whitespace_scans_forward_on_line() -> None:
    app = _StarSearchApp("   cat dog cat")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 11)


async def test_star_with_no_keyword_after_cursor_notifies_without_touching_state() -> (
    None
):
    app = _StarSearchApp("cat dog cat\n!!!")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()
        assert text_area.cursor_location == (0, 8)
        register_before = bar.prompt_search_register()
        spans_before = text_area._search_match_spans

        text_area.cursor_location = (1, 1)
        await pilot.press("*")
        await pilot.pause()

        assert text_area.cursor_location == (1, 1)
        assert bar.prompt_search_register() == register_before
        assert text_area._search_match_spans == spans_before
        assert app.notifications[-1] == "no string under cursor"


async def test_single_occurrence_wraps_with_vim_style_feedback() -> None:
    app = _StarSearchApp("solo word")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 0)
        assert app.notifications[-1] == "search hit BOTTOM, continuing at TOP"


async def test_star_crosses_prompt_panes_and_focuses_destination() -> None:
    app = _StarSearchApp("top cat\n---\nbottom cat")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape", "g", "k")
        await pilot.pause()

        top = bar.active_text_area()
        assert bar._stack.selected_index == 0
        top.cursor_location = (0, 4)

        await pilot.press("*")
        await pilot.pause()

        bottom = bar.active_text_area()
        assert bar._stack.selected_index == 1
        assert bottom is not top
        assert bottom.cursor_location == (0, 7)
        assert bottom._vim_mode == "normal"
        assert app.focused is bottom


async def test_f_star_and_dt_star_treat_asterisk_as_literal_target() -> None:
    app = _StarSearchApp("ab*cd")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("f", "*")
        await pilot.pause()
        assert text_area.cursor_location == (0, 2)
        assert app.open_saved_query_picker_count == 0

        text_area.cursor_location = (0, 0)
        await pilot.press("d", "t", "*")
        await pilot.pause()
        assert text_area.text == "*cd"
        assert app.open_saved_query_picker_count == 0


async def test_d_star_moves_without_deleting() -> None:
    app = _StarSearchApp("cat dog cat")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("d", "*")
        await pilot.pause()

        assert text_area.text == "cat dog cat"
        assert text_area.cursor_location == (0, 8)


async def test_insert_mode_star_inserts_literal_character() -> None:
    app = _StarSearchApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape", "i")
        await pilot.press("*")
        await pilot.pause()

        assert text_area.text == "*"
        assert text_area._vim_mode == "insert"
        assert app.open_saved_query_picker_count == 0


async def test_visual_star_searches_charwise_selection_literally() -> None:
    app = _StarSearchApp("cat dog cat")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("v", "l", "l", "*")
        await pilot.pause()

        assert text_area.cursor_location == (0, 8)
        assert text_area._vim_mode == "normal"
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="cat",
            direction="forward",
            whole_word=False,
            smartcase=False,
        )


async def test_visual_star_searches_v_line_selection_literally() -> None:
    app = _StarSearchApp("cat\ndog\ncat")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("V", "*")
        await pilot.pause()

        assert text_area.cursor_location == (2, 0)
        assert text_area._vim_mode == "normal"


async def test_visual_star_on_empty_selection_notifies_without_register() -> None:
    app = _StarSearchApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")

        await pilot.press("v", "*")
        await pilot.pause()

        assert text_area._vim_mode == "normal"
        assert bar.prompt_search_register() is None
        assert app.notifications[-1] == "no string under cursor"
