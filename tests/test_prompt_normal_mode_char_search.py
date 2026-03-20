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
