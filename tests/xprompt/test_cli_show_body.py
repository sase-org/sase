"""Tests for xprompt show body highlighting and gutters."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from sase.xprompt.cli_show_body import body_block, highlighted_body


def _plain(renderable: object, *, width: int = 80) -> str:
    stream = StringIO()
    console = Console(
        file=stream,
        no_color=True,
        force_terminal=False,
        width=width,
        markup=False,
        emoji=False,
        highlight=False,
    )
    console.print(renderable)
    return stream.getvalue()


def test_body_gutter_uses_absolute_or_local_line_numbers() -> None:
    assert _plain(body_block("first\n\nthird", first_line=45)) == (
        " 45 │ first\n 46 │ \n 47 │ third\n"
    )
    assert _plain(body_block("first\nsecond")) == ("  1 │ first\n  2 │ second\n")


def test_body_treats_markup_like_input_as_literal_text() -> None:
    body = "[bold]red[/bold]\n[\n`%model(test)`"

    rendered = _plain(body_block(body))

    assert "[bold]red[/bold]" in rendered
    assert "  2 │ [" in rendered
    assert "`%model(test)`" in rendered
    assert "\x1b" not in rendered


def test_long_line_folds_without_loss_and_tab_survives() -> None:
    body = "x" * 500 + "\tend"

    rendered = _plain(body_block(body), width=40)

    assert rendered.count("x") == 500
    assert "\t" in rendered
    assert "end" in rendered


def test_private_use_character_is_not_mistaken_for_tab() -> None:
    body = "before  after"

    assert _plain(body_block(body)) == "  1 │ before  after\n"


def test_highlighted_body_preserves_plain_bytes_and_styles_roles() -> None:
    source = "#demo(arg)\n%model(test)\n---"

    rendered = highlighted_body(source)

    assert rendered.plain == source
    assert rendered.spans


def test_fenced_body_keeps_source_and_adds_syntax_spans() -> None:
    source = "```python\nprint('ok')\n```"

    rendered = highlighted_body(source)

    assert rendered.plain == source
    assert rendered.spans
