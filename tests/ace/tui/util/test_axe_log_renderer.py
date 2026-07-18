"""Tests for the semantic AXE output highlighter."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.util import axe_log_renderer


def _render_lumberjack(output: str) -> Text:
    axe_log_renderer._render_cache.clear()
    return axe_log_renderer.render_axe_output("lumberjack:test", output, "lumberjack")


def _styles_at(text: Text, substring: str) -> set[str]:
    """Return the styles applied over ``substring`` in ``text``.

    Rich stores style spans as ``(start, end, style)`` triples on ``Text``;
    we walk them and keep the ones whose range covers any byte of the
    substring's first occurrence so the assertions stay robust against
    overlapping highlight passes.
    """
    plain = text.plain
    start = plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


def test_lumberjack_log_preserves_plain_text() -> None:
    """The semantic renderer keeps the original characters intact."""
    sample = (
        "[2026-05-11 12:34:56] [hooks] Lumberjack 'hooks' started "
        "(PID 9123, interval: 5s, chops: ack, send)\n"
        "[2026-05-11 12:34:57] [hooks] Launched agent chop 'send' (PID 9201)\n"
    )
    text = _render_lumberjack(sample)
    assert text.plain == sample


def test_lumberjack_ansi_wrapped_line_strips_escapes_and_preserves_width() -> None:
    sample = (
        "\x1b[33m[2026-05-11 12:34:56] [hooks] "
        "Tick overrun: took 6.0s but interval is 5s\x1b[0m"
    )
    expected = (
        "[2026-05-11 12:34:56] [hooks] Tick overrun: took 6.0s but interval is 5s"
    )

    text = _render_lumberjack(sample)

    assert text.plain == expected
    assert "\x1b" not in text.plain
    assert text.cell_len == cell_len(expected)


def test_lumberjack_ansi_wrapped_header_keeps_semantic_styles() -> None:
    text = _render_lumberjack(
        "\x1b[33m[2026-05-11 12:34:56] [hooks] "
        "Tick overrun: took 6.0s but interval is 5s\x1b[0m\n"
    )

    timestamp_styles = _styles_at(text, "2026-05-11 12:34:56")
    name_styles = _styles_at(text, "hooks")

    assert any("dim" in s for s in timestamp_styles)
    assert any("#FFD700" in s for s in name_styles)


def test_semantic_paths_strip_embedded_chop_ansi_codes() -> None:
    body = "\x1b[33munsent=0 sent=0\x1b[0m failures=0"

    lumberjack_text = _render_lumberjack(f"[2026-05-11 12:34:56] [telegram] {body}\n")
    assert lumberjack_text.plain == (
        "[2026-05-11 12:34:56] [telegram] unsent=0 sent=0 failures=0\n"
    )
    assert "\x1b" not in lumberjack_text.plain


def test_lumberjack_crlf_input_strips_carriage_returns() -> None:
    text = _render_lumberjack("[2026-05-11 12:34:56] [hooks] success\r\n")

    assert text.plain == "[2026-05-11 12:34:56] [hooks] success\n"
    assert "\r" not in text.plain


def test_lumberjack_timestamp_dim() -> None:
    """Timestamps get the dim treatment so the message text dominates."""
    text = _render_lumberjack("[2026-05-11 12:34:56] [hooks] success\n")
    styles = _styles_at(text, "2026-05-11 12:34:56")
    assert any("dim" in s for s in styles)


def test_lumberjack_name_uses_taxonomy_color() -> None:
    """Lumberjack header name is styled with the gold sidebar accent."""
    text = _render_lumberjack("[2026-05-11 12:34:56] [hooks] running\n")
    styles = _styles_at(text, "hooks")
    assert any("#FFD700" in s for s in styles)


def test_status_word_failure_red() -> None:
    """The literal word ``failure`` is colored as a severity marker."""
    text = _render_lumberjack(
        "[2026-05-11 12:34:56] [hooks] Chop failed: failure on ack\n"
    )
    styles = _styles_at(text, "failure")
    assert any("red" in s for s in styles)


def test_status_word_success_green() -> None:
    text = _render_lumberjack("[2026-05-11 12:34:56] [hooks] tick complete: success\n")
    styles = _styles_at(text, "success")
    assert any("green" in s for s in styles)


def test_pid_token_styled() -> None:
    """``PID NNN`` should pop relative to surrounding prose."""
    text = _render_lumberjack(
        "[2026-05-11 12:34:56] [hooks] Launched agent chop 'send' (PID 9201)\n"
    )
    styles = _styles_at(text, "PID 9201")
    assert any("#FF87D7" in s for s in styles)


def test_quoted_chop_name_styled() -> None:
    text = _render_lumberjack(
        "[2026-05-11 12:34:56] [hooks] Launched agent chop 'send' (PID 9201)\n"
    )
    styles = _styles_at(text, "'send'")
    assert any("#D7AF87" in s for s in styles)


def test_duration_styled() -> None:
    text = _render_lumberjack(
        "[2026-05-11 12:34:56] [hooks] Tick overrun: took 7.4s but interval is 5s\n"
    )
    styles = _styles_at(text, "7.4s")
    assert any("#00D7AF" in s for s in styles)


def test_exit_code_styled() -> None:
    text = _render_lumberjack(
        "[2026-05-11 12:34:56] [hooks] chop returned exit code 137\n"
    )
    styles = _styles_at(text, "exit code 137")
    assert any("red" in s for s in styles)


def test_lumberjack_line_without_header_still_highlights_tokens() -> None:
    """A line that doesn't match the ``[ts] [name]`` header still gets body
    tokens highlighted so error tails read coherently."""
    text = _render_lumberjack("Lumberjack tick raised: timeout after 30s\n")
    styles = _styles_at(text, "timeout")
    assert any("yellow" in s for s in styles)


def test_classify_source_lumberjack_prefix() -> None:
    assert axe_log_renderer.classify_source("lumberjack:hooks") == "lumberjack"


def test_classify_source_default_to_ansi() -> None:
    assert axe_log_renderer.classify_source("bgcmd:5") == "ansi"
    assert axe_log_renderer.classify_source("axe-output") == "ansi"
    assert axe_log_renderer.classify_source("chop:lj:cp:r") == "ansi"


def test_render_axe_output_caps_huge_input() -> None:
    """The semantic path goes through ``cap_ansi_output`` like ANSI does so
    huge logs stay bounded."""
    big = ("x" * 80_000) + "\n[2026-05-11 12:34:56] [hooks] success\n"
    text = _render_lumberjack(big)
    # Output is capped to a tail window, so the rendered length is much
    # smaller than the input.
    assert len(text.plain) < len(big)
    # The recognizable header still appears in the tail.
    assert "[hooks]" in text.plain
