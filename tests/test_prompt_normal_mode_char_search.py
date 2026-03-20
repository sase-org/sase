"""Tests for PromptTextArea NORMAL-mode f/F/t/T character search motions."""

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _TestApp(App[None]):
    """Minimal app for testing PromptTextArea in isolation."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


# =============================================================================
# f — find char forward (inclusive)
# =============================================================================


async def test_f_moves_to_char() -> None:
    """f) moves cursor to the next ')' on the line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("f", ")")
        assert ta.cursor_location == (0, 7)


async def test_f_with_count() -> None:
    """2f, finds the 2nd comma."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a, b, c, d"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("2", "f", ",")
        assert ta.cursor_location == (0, 4)


async def test_f_no_match_stays() -> None:
    """fz with no 'z' on line does not move cursor."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("f", "z")
        assert ta.cursor_location == (0, 3)


# =============================================================================
# F — find char backward (inclusive)
# =============================================================================


async def test_F_moves_to_char() -> None:
    """F( moves cursor backward to '('."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 10)
        ta._enter_normal_mode()

        await pilot.press("F", "(")
        assert ta.cursor_location == (0, 3)


async def test_F_with_count() -> None:
    """2F, finds the 2nd comma backward."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a, b, c, d"
        ta.cursor_location = (0, 9)
        ta._enter_normal_mode()

        await pilot.press("2", "F", ",")
        assert ta.cursor_location == (0, 4)


async def test_F_no_match_stays() -> None:
    """Fz with no 'z' before cursor does not move."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("F", "z")
        assert ta.cursor_location == (0, 3)


# =============================================================================
# t — till char forward (exclusive)
# =============================================================================


async def test_t_moves_before_char() -> None:
    """t) moves cursor to one before the next ')'."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("t", ")")
        assert ta.cursor_location == (0, 6)


async def test_t_with_count() -> None:
    """2t, finds one before the 2nd comma."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a, b, c, d"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("2", "t", ",")
        assert ta.cursor_location == (0, 3)


async def test_t_no_match_stays() -> None:
    """tz with no 'z' does not move cursor."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("t", "z")
        assert ta.cursor_location == (0, 3)


# =============================================================================
# T — till char backward (exclusive)
# =============================================================================


async def test_T_moves_after_char() -> None:
    """T( moves cursor to one after the previous '('."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 10)
        ta._enter_normal_mode()

        await pilot.press("T", "(")
        assert ta.cursor_location == (0, 4)


async def test_T_with_count() -> None:
    """2T, finds one after the 2nd comma backward."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a, b, c, d"
        ta.cursor_location = (0, 9)
        ta._enter_normal_mode()

        await pilot.press("2", "T", ",")
        assert ta.cursor_location == (0, 5)


async def test_T_no_match_stays() -> None:
    """Tz with no 'z' before cursor does not move."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("T", "z")
        assert ta.cursor_location == (0, 3)


# =============================================================================
# Operator combinations (df, dt, dF, dT, cf, ct)
# =============================================================================


async def test_df_deletes_through_char() -> None:
    """df) deletes from cursor through ')' inclusive."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("d", "f", ")")
        assert ta.text == "foo baz"
        assert ta.cursor_location == (0, 3)


async def test_dt_deletes_up_to_char() -> None:
    """dt) deletes from cursor up to but not including ')'."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("d", "t", ")")
        assert ta.text == "foo) baz"
        assert ta.cursor_location == (0, 3)


async def test_dF_deletes_backward_through_char() -> None:
    """dF( deletes backward from cursor through '(' inclusive."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 7)
        ta._enter_normal_mode()

        await pilot.press("d", "F", "(")
        assert ta.text == "foo baz"
        assert ta.cursor_location == (0, 3)


async def test_dT_deletes_backward_till_char() -> None:
    """dT( deletes backward to one after '('."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 7)
        ta._enter_normal_mode()

        await pilot.press("d", "T", "(")
        assert ta.text == "foo( baz"
        assert ta.cursor_location == (0, 4)


async def test_cf_changes_through_char() -> None:
    """cf) deletes through ')' and enters INSERT mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "foo(bar) baz"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("c", "f", ")")
        assert ta.text == "foo baz"
        assert ta._vim_mode == "insert"


async def test_operator_no_match_preserves_text() -> None:
    """dfz with no 'z' should not modify text."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("d", "f", "z")
        assert ta.text == "hello world"
        assert ta.cursor_location == (0, 3)


# =============================================================================
# ; — repeat last character search (same direction)
# =============================================================================


async def test_semicolon_repeats_f() -> None:
    """; after f) repeats the search forward."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("f", ")")
        assert ta.cursor_location == (0, 1)
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 4)
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 7)


async def test_semicolon_repeats_F() -> None:
    """; after F) repeats the search backward."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 9)
        ta._enter_normal_mode()

        await pilot.press("F", ")")
        assert ta.cursor_location == (0, 7)
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 4)


async def test_semicolon_repeats_t() -> None:
    """; after t) repeats till-forward."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("t", ")")
        assert ta.cursor_location == (0, 0)  # one before col 1
        await pilot.press("semicolon")
        # From col 0, next ) is at 1, but t stops before → still 0
        # Let's move cursor first to make this clearer
        ta.cursor_location = (0, 2)
        await pilot.press("t", ")")
        assert ta.cursor_location == (0, 3)  # one before col 4
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 6)  # one before col 7


async def test_semicolon_repeats_T() -> None:
    """; after T) repeats till-backward."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 9)
        ta._enter_normal_mode()

        await pilot.press("T", ")")
        assert ta.cursor_location == (0, 8)  # one after col 7
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 5)  # one after col 4


async def test_semicolon_with_count() -> None:
    """2; skips to the 2nd match."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a, b, c, d, e"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("f", ",")
        assert ta.cursor_location == (0, 1)
        await pilot.press("2", "semicolon")
        assert ta.cursor_location == (0, 7)


async def test_semicolon_no_prior_search() -> None:
    """; with no prior search does nothing."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 3)


# =============================================================================
# , — repeat last character search (reverse direction)
# =============================================================================


async def test_comma_reverses_f() -> None:
    """, after f) searches backward."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("f", ")")
        assert ta.cursor_location == (0, 1)
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 4)
        await pilot.press("comma")
        assert ta.cursor_location == (0, 1)


async def test_comma_reverses_F() -> None:
    """, after F) searches forward."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 9)
        ta._enter_normal_mode()

        await pilot.press("F", ")")
        assert ta.cursor_location == (0, 7)
        await pilot.press("comma")
        # , reverses F → f, so searches forward — no ) after col 7 except none
        # Actually there's no ) after col 7, so cursor stays
        assert ta.cursor_location == (0, 7)


async def test_comma_reverses_t() -> None:
    """, after t) does T) (till-backward)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 2)
        ta._enter_normal_mode()

        await pilot.press("t", ")")
        assert ta.cursor_location == (0, 3)  # one before ) at col 4
        await pilot.press("comma")
        assert ta.cursor_location == (0, 2)  # T) → one after ) at col 1


async def test_comma_with_count() -> None:
    """2, reverses with count."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a, b, c, d, e"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("f", ",")
        assert ta.cursor_location == (0, 1)
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 4)
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 7)
        await pilot.press("2", "comma")
        assert ta.cursor_location == (0, 1)


async def test_comma_no_prior_search() -> None:
    """, with no prior search does nothing."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("comma")
        assert ta.cursor_location == (0, 3)


# =============================================================================
# ;/, with operators (d;, c,, etc.)
# =============================================================================


async def test_d_semicolon_deletes_to_next_match() -> None:
    """d; after f) deletes through the next )."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("f", ")")
        assert ta.cursor_location == (0, 1)
        await pilot.press("d", "semicolon")
        # d; repeats f) → deletes from col 1 through col 4 (inclusive)
        assert ta.text == "a c) d"


async def test_c_comma_changes_in_reverse() -> None:
    """c, after f) changes backward to previous match."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "a) b) c) d"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("f", ")")
        await pilot.press("semicolon")
        assert ta.cursor_location == (0, 4)
        await pilot.press("c", "comma")
        # c, reverses f) → F), deletes from col 1 through col 4 (inclusive)
        assert ta._vim_mode == "insert"
        assert ta.text == "a c) d"
