"""Pure fitting of an xprompt into the collapsed agent-header preview."""

from __future__ import annotations

import time

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets.agent_header_preview import (
    PREVIEW_BAR_GLYPH,
    PREVIEW_BAR_STYLE,
    PREVIEW_BREAK_GLYPH,
    PREVIEW_DIM_STYLE,
    XpromptPreviewFit,
    fit_xprompt_preview,
    preview_row_budget,
)

GUTTER = f"{PREVIEW_BAR_GLYPH} "
MARK = PREVIEW_BREAK_GLYPH


def _rows(fit: XpromptPreviewFit) -> list[str]:
    return fit.text.plain.split("\n") if fit.rows else []


def _flow(source: str, *, width: int = 300) -> str:
    """Return the single-row reflow of ``source`` without its gutter."""
    fit = fit_xprompt_preview(Text(source), width=width, max_rows=1)
    assert fit.rows == 1
    assert not fit.truncated
    (row,) = _rows(fit)
    assert row.startswith(GUTTER)
    return row[len(GUTTER) :]


def _styles_at(text: Text, index: int) -> list[str]:
    return [str(span.style) for span in text.spans if span.start <= index < span.end]


# --- reflow ---------------------------------------------------------------


def test_soft_line_breaks_join_with_one_space() -> None:
    assert _flow("one two\nthree\nfour five") == "one two three four five"


def test_blank_lines_become_one_dim_mark() -> None:
    assert _flow("one\n\ntwo") == f"one {MARK} two"
    assert _flow("one\n\n\n  \n\t\ntwo") == f"one {MARK} two"


def test_leading_and_trailing_blank_lines_are_dropped() -> None:
    assert _flow("\n\n  \none\ntwo\n\n \n") == "one two"


@pytest.mark.parametrize(
    "block_line",
    [
        "- item",
        "* item",
        "+ item",
        "1. item",
        "9) item",
        "10. item",
        "# Heading",
        "###### Heading",
        "> quote",
        "| a | b |",
        "```python",
        "  - nested item",
    ],
)
def test_block_constructs_start_a_hard_break(block_line: str) -> None:
    flow = _flow(f"prose line\n{block_line}")
    assert flow == f"prose line {MARK} {block_line.strip()}"


@pytest.mark.parametrize(
    "prose_line",
    [
        "+sase %id(3, clan=x) %auto",
        "#gh",
        "#plan sase-1",
        "-x flag",
        "*bold* text",
        "1.5 seconds",
        "####### seven hashes",
        ">not a quote",
        "+1 vote",
    ],
)
def test_lines_that_only_look_like_blocks_soft_join(prose_line: str) -> None:
    assert _flow(f"prose line\n{prose_line}") == f"prose line {prose_line}"


def test_directive_stacks_pack_densely() -> None:
    src = "+sase %id(3, clan=sase-18f) %model:@medium %auto\n%w:sase-18f.1 #gh\n#bd/x:1"
    assert _flow(src) == (
        "+sase %id(3, clan=sase-18f) %model:@medium %auto %w:sase-18f.1 #gh #bd/x:1"
    )


def test_fenced_blocks_break_at_every_line_boundary() -> None:
    src = "before\n```py\nfirst = 1\nsecond = 2\n```\nafter\nmore"
    assert _flow(src) == (
        f"before {MARK} ```py {MARK} first = 1 {MARK} second = 2 {MARK} ``` {MARK} "
        "after more"
    )


def test_block_sigils_inside_a_fence_do_not_add_extra_marks() -> None:
    src = "```\n- not a list\n# not a heading\n```"
    assert _flow(src) == f"``` {MARK} - not a list {MARK} # not a heading {MARK} ```"


def test_thematic_breaks_break_only_after_the_line() -> None:
    assert _flow("above\n---\nbelow") == f"above --- {MARK} below"
    assert _flow("above\n\n***\n\nbelow") == f"above {MARK} *** {MARK} below"
    assert _flow("above\n_ _ _\nbelow") == f"above _ _ _ {MARK} below"


def test_indentation_tabs_and_trailing_whitespace_are_normalized() -> None:
    assert _flow("    indented   \n\t\ttabbed\t\nplain") == "indented tabbed plain"
    assert _flow("a\tb") == "a   b"


def test_marks_are_dim_and_gutters_use_the_accent() -> None:
    fit = fit_xprompt_preview(Text("one\n\ntwo"), width=40, max_rows=3)
    plain = fit.text.plain
    assert PREVIEW_DIM_STYLE in _styles_at(fit.text, plain.index(MARK))
    assert PREVIEW_BAR_STYLE in _styles_at(fit.text, 0)
    assert PREVIEW_BAR_STYLE in _styles_at(fit.text, 1)
    assert _styles_at(fit.text, plain.index("one")) == []


def test_style_spans_survive_reflow_and_wrapping() -> None:
    source = Text(
        "+sase %model:@medium %auto\n%w:sase-18f.1\n\nsee #gh here and `code`",
    )
    styled = {"%model:@medium": "bold cyan", "%w:sase-18f.1": "green", "#gh": "red"}
    for word, style in styled.items():
        start = source.plain.index(word)
        source.stylize(style, start, start + len(word))

    for width in (80, 24, 14):
        fit = fit_xprompt_preview(source, width=width, max_rows=20)
        assert not fit.truncated
        joined = fit.text.plain
        for word, style in styled.items():
            # A token too long for a row folds, so match only whole occurrences.
            if word not in joined:
                continue
            start = joined.index(word)
            for offset in range(len(word)):
                assert style in _styles_at(fit.text, start + offset)
        # Unstyled text stays unstyled.
        assert _styles_at(fit.text, joined.index("here")) == []


def test_base_text_style_is_kept() -> None:
    fit = fit_xprompt_preview(Text("word", style="italic"), width=20, max_rows=2)
    assert "italic" in _styles_at(fit.text, len(GUTTER))


# --- fitting --------------------------------------------------------------


@pytest.mark.parametrize("width", [8, 12, 21, 40, 80])
def test_rows_never_exceed_width_and_start_with_the_gutter(width: int) -> None:
    source = Text(
        "\n".join(
            [
                "A long paragraph of prose that has to wrap onto several rows.",
                "",
                "- a list item with_a_token_that_is_far_too_long_for_one_row_at_all",
                "```",
                "code_line_one",
                "```",
            ]
            * 3
        )
    )
    for max_rows in (1, 2, 5, 50):
        fit = fit_xprompt_preview(source, width=width, max_rows=max_rows)
        rows = _rows(fit)
        assert fit.rows == len(rows) <= max_rows
        assert rows
        for row in rows:
            assert row.startswith(GUTTER)
            assert cell_len(row) <= width


def test_result_text_is_single_no_wrap_ellipsis_text() -> None:
    fit = fit_xprompt_preview(Text("some words here"), width=30, max_rows=3)
    assert fit.text.no_wrap is True
    assert fit.text.overflow == "ellipsis"


def test_short_source_uses_only_the_rows_it_needs() -> None:
    fit = fit_xprompt_preview(Text("short prompt"), width=80, max_rows=7)
    assert fit.rows == 1
    assert fit.text.plain == f"{GUTTER}short prompt"
    assert (fit.truncated, fit.hidden_lines) == (False, 0)


def test_long_paragraph_wraps_at_word_boundaries() -> None:
    words = " ".join(f"word{i:02d}" for i in range(12))
    fit = fit_xprompt_preview(Text(words), width=22, max_rows=10)
    rows = _rows(fit)
    assert len(rows) > 1
    assert " ".join(row[len(GUTTER) :] for row in rows) == words


def test_tokens_too_long_for_a_row_are_folded() -> None:
    fit = fit_xprompt_preview(Text("x" * 45), width=22, max_rows=10)
    rows = _rows(fit)
    assert [row[len(GUTTER) :] for row in rows] == ["x" * 20, "x" * 20, "x" * 5]
    assert not fit.truncated


def test_exact_fit_shows_no_ellipsis() -> None:
    source = Text("aaaa bbbb cccc dddd")
    fit = fit_xprompt_preview(source, width=12, max_rows=2)
    assert _rows(fit) == [f"{GUTTER}aaaa bbbb", f"{GUTTER}cccc dddd"]
    assert (fit.rows, fit.truncated, fit.hidden_lines) == (2, False, 0)


def test_overflow_ends_in_an_ellipsis_after_the_last_whole_word() -> None:
    source = Text("aaaa bbbb cccc dddd eeee")
    fit = fit_xprompt_preview(source, width=11, max_rows=2)
    # Row two would be "cccc dddd"; "…" after it needs 10 cells of 9, so "dddd" drops.
    assert _rows(fit) == [f"{GUTTER}aaaa bbbb", f"{GUTTER}cccc…"]
    assert fit.truncated
    assert fit.rows == 2


def test_overflow_keeps_the_ellipsis_flush_when_it_fits() -> None:
    source = Text("aaaa bbbb cccc dddd eeee")
    fit = fit_xprompt_preview(source, width=12, max_rows=2)
    assert _rows(fit) == [f"{GUTTER}aaaa bbbb", f"{GUTTER}cccc dddd…"]


def test_overflow_cuts_inside_a_single_long_token() -> None:
    fit = fit_xprompt_preview(Text("x" * 100), width=12, max_rows=2)
    assert _rows(fit) == [f"{GUTTER}{'x' * 10}", f"{GUTTER}{'x' * 9}…"]
    assert fit.truncated


def test_hidden_lines_counts_source_lines_not_fully_shown() -> None:
    fit = fit_xprompt_preview(Text("aa\nbb\n\n\ncc\ndd"), width=12, max_rows=1)
    assert _rows(fit) == [f"{GUTTER}aa bb {MARK}…"]
    # aa, bb and the collapsed blank run are shown; cc and dd are not.
    assert fit.hidden_lines == 2
    assert fit.truncated


def test_a_partly_shown_line_counts_as_hidden() -> None:
    fit = fit_xprompt_preview(Text("aa bb\ncc dd ee ff gg"), width=12, max_rows=1)
    assert _rows(fit) == [f"{GUTTER}aa bb cc…"]
    assert fit.hidden_lines == 1


def test_hidden_lines_is_exact_for_long_hard_wrapped_prompts() -> None:
    lines = [f"line {i}" for i in range(40)]
    fit = fit_xprompt_preview(Text("\n".join(lines)), width=30, max_rows=3)
    assert fit.truncated
    shown = " ".join(row[len(GUTTER) :] for row in _rows(fit)).rstrip("…").split()
    assert fit.hidden_lines == 40 - len(shown) // 2


def test_long_run_of_blank_lines_is_still_reflowed_completely() -> None:
    fit = fit_xprompt_preview(Text("a" + "\n" * 5000 + "b"), width=20, max_rows=1)
    assert _rows(fit) == [f"{GUTTER}a {MARK} b"]
    assert (fit.truncated, fit.hidden_lines) == (False, 0)


def test_blank_heavy_prefix_still_fills_the_budget() -> None:
    lines = ["p1"] + [""] * 3000 + ["p2 " * 5] + [""] * 3000 + ["tail"]
    fit = fit_xprompt_preview(Text("\n".join(lines)), width=12, max_rows=3)
    assert _rows(fit) == [
        f"{GUTTER}p1 {MARK} p2 p2",
        f"{GUTTER}p2 p2 p2 {MARK}",
        f"{GUTTER}tail",
    ]
    assert (fit.truncated, fit.hidden_lines) == (False, 0)


def test_max_rows_zero_and_negative_return_an_empty_fit() -> None:
    for max_rows in (0, -3):
        fit = fit_xprompt_preview(Text("some prompt"), width=40, max_rows=max_rows)
        assert fit == XpromptPreviewFit(Text(), 0, False, 0)
        assert fit.text.plain == ""


def test_blank_source_returns_an_empty_fit() -> None:
    for source in ("", "\n\n", "  \t \n "):
        fit = fit_xprompt_preview(Text(source), width=40, max_rows=4)
        assert (fit.text.plain, fit.rows, fit.truncated, fit.hidden_lines) == (
            "",
            0,
            False,
            0,
        )


def test_single_row_budget_truncates_with_a_count() -> None:
    fit = fit_xprompt_preview(Text("aaaa bbbb\ncccc\ndddd"), width=12, max_rows=1)
    assert fit.rows == 1
    assert fit.truncated
    assert _rows(fit) == [f"{GUTTER}aaaa bbbb…"]
    assert fit.hidden_lines == 2


def test_tiny_widths_never_crash() -> None:
    source = Text("wide 你好 chars and a_very_long_token_here\n\n- item")
    for width in (-5, 0, 1, 2, 3, 5, 6):
        fit = fit_xprompt_preview(source, width=width, max_rows=4)
        assert 1 <= fit.rows <= 4
        for row in _rows(fit):
            assert row.startswith(GUTTER)


def test_wide_characters_are_measured_in_cells() -> None:
    fit = fit_xprompt_preview(Text("你好" * 4), width=10, max_rows=5)
    rows = _rows(fit)
    assert [row[len(GUTTER) :] for row in rows] == ["你好你好"] * 2
    assert all(cell_len(row) <= 10 for row in rows)
    assert not fit.truncated


def test_wide_characters_and_emoji_truncate_within_the_width() -> None:
    source = Text("\U0001f600你 " * 20 + "你" * 50)
    for width in (9, 10, 17):
        fit = fit_xprompt_preview(source, width=width, max_rows=2)
        rows = _rows(fit)
        assert len(rows) == 2
        assert fit.truncated
        assert rows[-1].endswith("…")
        assert all(cell_len(row) <= width for row in rows)


def test_source_text_is_not_mutated() -> None:
    source = Text("  keep   me\t\n\n- item \n```\ncode\n```  \n", style="italic")
    source.stylize("bold", 2, 6)
    source.stylize("red", 14, 18)
    before = source.copy()
    spans_before = list(source.spans)
    fit_xprompt_preview(source, width=12, max_rows=2)
    fit_xprompt_preview(source, width=80, max_rows=20)
    assert source.plain == before.plain
    assert source.spans == spans_before
    assert source.style == before.style
    assert source == before


def test_huge_sources_only_reflow_a_prefix() -> None:
    count = 100_000
    source = Text("\n".join(f"line {i}" for i in range(count)))
    started = time.perf_counter()
    fit = fit_xprompt_preview(source, width=60, max_rows=6)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0
    assert fit.rows == 6
    assert fit.truncated
    shown = " ".join(row[len(GUTTER) :] for row in _rows(fit)).rstrip("…").split()
    assert shown[:4] == ["line", "0", "line", "1"]
    assert fit.hidden_lines == count - len(shown) // 2


def test_huge_styled_sources_keep_styles_in_the_prefix() -> None:
    source = Text("\n".join(f"#tag{i} some words" for i in range(20_000)))
    for i in range(0, 20_000, 500):
        start = source.plain.index(f"#tag{i} ")
        source.stylize("bold", start, start + 4)
    fit = fit_xprompt_preview(source, width=40, max_rows=3)
    assert fit.truncated
    assert "bold" in _styles_at(fit.text, fit.text.plain.index("#tag0"))


# --- budget ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("column_rows", "share", "expected"),
    [
        (32, 0.35, 7),
        (47, 0.35, 12),
        (20, 0.35, 3),
        (100, 0.35, 31),
        (40, 0.5, 16),
        (40, 0.6, 20),
        # The cap at or under the chrome rows still leaves one preview row.
        (10, 0.35, 1),
        (8, 0.35, 1),
        (1, 0.01, 1),
        # A non-positive share or column turns the preview off.
        (32, 0, 0),
        (32, 0.0, 0),
        (32, -0.5, 0),
        (0, 0.35, 0),
        (-4, 0.35, 0),
    ],
)
def test_preview_row_budget(column_rows: int, share: float, expected: int) -> None:
    assert preview_row_budget(column_rows, share) == expected
