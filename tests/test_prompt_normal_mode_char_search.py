"""Tests for PromptTextArea NORMAL-mode f/F/t/T character search motions."""

from sase.ace.testing import PromptPage


# =============================================================================
# f — find char forward (inclusive)
# =============================================================================


async def test_f_moves_to_char() -> None:
    """f) moves cursor to the next ')' on the line."""
    async with PromptPage("foo(bar) baz") as page:
        await page.press("f", ")")
        assert page.cursor == (0, 7)


async def test_f_with_count() -> None:
    """2f, finds the 2nd comma."""
    async with PromptPage("a, b, c, d") as page:
        await page.press("2", "f", ",")
        assert page.cursor == (0, 4)


async def test_f_no_match_stays() -> None:
    """fz with no 'z' on line does not move cursor."""
    async with PromptPage("hello world", cursor=(0, 3)) as page:
        await page.press("f", "z")
        assert page.cursor == (0, 3)


# =============================================================================
# F — find char backward (inclusive)
# =============================================================================


async def test_F_moves_to_char() -> None:
    """F( moves cursor backward to '('."""
    async with PromptPage("foo(bar) baz", cursor=(0, 10)) as page:
        await page.press("F", "(")
        assert page.cursor == (0, 3)


async def test_F_with_count() -> None:
    """2F, finds the 2nd comma backward."""
    async with PromptPage("a, b, c, d", cursor=(0, 9)) as page:
        await page.press("2", "F", ",")
        assert page.cursor == (0, 4)


async def test_F_no_match_stays() -> None:
    """Fz with no 'z' before cursor does not move."""
    async with PromptPage("hello world", cursor=(0, 3)) as page:
        await page.press("F", "z")
        assert page.cursor == (0, 3)


# =============================================================================
# t — till char forward (exclusive)
# =============================================================================


async def test_t_moves_before_char() -> None:
    """t) moves cursor to one before the next ')'."""
    async with PromptPage("foo(bar) baz") as page:
        await page.press("t", ")")
        assert page.cursor == (0, 6)


async def test_t_with_count() -> None:
    """2t, finds one before the 2nd comma."""
    async with PromptPage("a, b, c, d") as page:
        await page.press("2", "t", ",")
        assert page.cursor == (0, 3)


async def test_t_no_match_stays() -> None:
    """tz with no 'z' does not move cursor."""
    async with PromptPage("hello world", cursor=(0, 3)) as page:
        await page.press("t", "z")
        assert page.cursor == (0, 3)


# =============================================================================
# T — till char backward (exclusive)
# =============================================================================


async def test_T_moves_after_char() -> None:
    """T( moves cursor to one after the previous '('."""
    async with PromptPage("foo(bar) baz", cursor=(0, 10)) as page:
        await page.press("T", "(")
        assert page.cursor == (0, 4)


async def test_T_with_count() -> None:
    """2T, finds one after the 2nd comma backward."""
    async with PromptPage("a, b, c, d", cursor=(0, 9)) as page:
        await page.press("2", "T", ",")
        assert page.cursor == (0, 5)


async def test_T_no_match_stays() -> None:
    """Tz with no 'z' before cursor does not move."""
    async with PromptPage("hello world", cursor=(0, 3)) as page:
        await page.press("T", "z")
        assert page.cursor == (0, 3)


# =============================================================================
# Operator combinations (df, dt, dF, dT, cf, ct)
# =============================================================================


async def test_df_deletes_through_char() -> None:
    """df) deletes from cursor through ')' inclusive."""
    async with PromptPage("foo(bar) baz", cursor=(0, 3)) as page:
        await page.press("d", "f", ")")
        assert page.text == "foo baz"
        assert page.cursor == (0, 3)


async def test_dt_deletes_up_to_char() -> None:
    """dt) deletes from cursor up to but not including ')'."""
    async with PromptPage("foo(bar) baz", cursor=(0, 3)) as page:
        await page.press("d", "t", ")")
        assert page.text == "foo) baz"
        assert page.cursor == (0, 3)


async def test_dF_deletes_backward_through_char() -> None:
    """dF( deletes backward from cursor through '(' inclusive."""
    async with PromptPage("foo(bar) baz", cursor=(0, 7)) as page:
        await page.press("d", "F", "(")
        assert page.text == "foo baz"
        assert page.cursor == (0, 3)


async def test_dT_deletes_backward_till_char() -> None:
    """dT( deletes backward to one after '('."""
    async with PromptPage("foo(bar) baz", cursor=(0, 7)) as page:
        await page.press("d", "T", "(")
        assert page.text == "foo( baz"
        assert page.cursor == (0, 4)


async def test_cf_changes_through_char() -> None:
    """cf) deletes through ')' and enters INSERT mode."""
    async with PromptPage("foo(bar) baz", cursor=(0, 3)) as page:
        await page.press("c", "f", ")")
        assert page.text == "foo baz"
        assert page.mode == "insert"


async def test_operator_no_match_preserves_text() -> None:
    """dfz with no 'z' should not modify text."""
    async with PromptPage("hello world", cursor=(0, 3)) as page:
        await page.press("d", "f", "z")
        assert page.text == "hello world"
        assert page.cursor == (0, 3)


# =============================================================================
# ; — repeat last character search (same direction)
# =============================================================================


async def test_semicolon_repeats_f() -> None:
    """; after f) repeats the search forward."""
    async with PromptPage("a) b) c) d") as page:
        await page.press("f", ")")
        assert page.cursor == (0, 1)
        await page.press("semicolon")
        assert page.cursor == (0, 4)
        await page.press("semicolon")
        assert page.cursor == (0, 7)


async def test_semicolon_repeats_F() -> None:
    """; after F) repeats the search backward."""
    async with PromptPage("a) b) c) d", cursor=(0, 9)) as page:
        await page.press("F", ")")
        assert page.cursor == (0, 7)
        await page.press("semicolon")
        assert page.cursor == (0, 4)


async def test_semicolon_repeats_t() -> None:
    """; after t) repeats till-forward."""
    async with PromptPage("a) b) c) d") as page:
        await page.press("t", ")")
        assert page.cursor == (0, 0)  # one before col 1
        await page.press("semicolon")
        # From col 0, next ) is at 1, but t stops before -> still 0
        # Let's move cursor first to make this clearer
        page.cursor = (0, 2)
        await page.press("t", ")")
        assert page.cursor == (0, 3)  # one before col 4
        await page.press("semicolon")
        assert page.cursor == (0, 6)  # one before col 7


async def test_semicolon_repeats_T() -> None:
    """; after T) repeats till-backward."""
    async with PromptPage("a) b) c) d", cursor=(0, 9)) as page:
        await page.press("T", ")")
        assert page.cursor == (0, 8)  # one after col 7
        await page.press("semicolon")
        assert page.cursor == (0, 5)  # one after col 4


async def test_semicolon_with_count() -> None:
    """2; skips to the 2nd match."""
    async with PromptPage("a, b, c, d, e") as page:
        await page.press("f", ",")
        assert page.cursor == (0, 1)
        await page.press("2", "semicolon")
        assert page.cursor == (0, 7)


async def test_semicolon_no_prior_search() -> None:
    """; with no prior search does nothing."""
    async with PromptPage("hello world", cursor=(0, 3)) as page:
        await page.press("semicolon")
        assert page.cursor == (0, 3)


# =============================================================================
# , — repeat last character search (reverse direction)
# =============================================================================


async def test_comma_reverses_f() -> None:
    """, after f) searches backward."""
    async with PromptPage("a) b) c) d") as page:
        await page.press("f", ")")
        assert page.cursor == (0, 1)
        await page.press("semicolon")
        assert page.cursor == (0, 4)
        await page.press("comma")
        assert page.cursor == (0, 1)


async def test_comma_reverses_F() -> None:
    """, after F) searches forward."""
    async with PromptPage("a) b) c) d", cursor=(0, 9)) as page:
        await page.press("F", ")")
        assert page.cursor == (0, 7)
        await page.press("comma")
        # , reverses F -> f, so searches forward -- no ) after col 7 except none
        # Actually there's no ) after col 7, so cursor stays
        assert page.cursor == (0, 7)


async def test_comma_reverses_t() -> None:
    """, after t) does T) (till-backward)."""
    async with PromptPage("a) b) c) d", cursor=(0, 2)) as page:
        await page.press("t", ")")
        assert page.cursor == (0, 3)  # one before ) at col 4
        await page.press("comma")
        assert page.cursor == (0, 2)  # T) -> one after ) at col 1


async def test_comma_with_count() -> None:
    """2, reverses with count."""
    async with PromptPage("a, b, c, d, e") as page:
        await page.press("f", ",")
        assert page.cursor == (0, 1)
        await page.press("semicolon")
        assert page.cursor == (0, 4)
        await page.press("semicolon")
        assert page.cursor == (0, 7)
        await page.press("2", "comma")
        assert page.cursor == (0, 1)


async def test_comma_no_prior_search() -> None:
    """, with no prior search does nothing."""
    async with PromptPage("hello world", cursor=(0, 3)) as page:
        await page.press("comma")
        assert page.cursor == (0, 3)


# =============================================================================
# ;/, with operators (d;, c,, etc.)
# =============================================================================


async def test_d_semicolon_deletes_to_next_match() -> None:
    """d; after f) deletes through the next )."""
    async with PromptPage("a) b) c) d") as page:
        await page.press("f", ")")
        assert page.cursor == (0, 1)
        await page.press("d", "semicolon")
        # d; repeats f) -> deletes from col 1 through col 4 (inclusive)
        assert page.text == "a c) d"


async def test_c_comma_changes_in_reverse() -> None:
    """c, after f) changes backward to previous match."""
    async with PromptPage("a) b) c) d") as page:
        await page.press("f", ")")
        await page.press("semicolon")
        assert page.cursor == (0, 4)
        await page.press("c", "comma")
        # c, reverses f) -> F), deletes from col 1 through col 4 (inclusive)
        assert page.mode == "insert"
        assert page.text == "a c) d"
