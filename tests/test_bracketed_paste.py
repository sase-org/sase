"""Tests for streaming normalization of tmux-reencoded bracketed pastes."""

from __future__ import annotations

import pytest

from sase.bracketed_paste import BracketedPasteNormalizer


def _normalize_body(body: str) -> str:
    normalizer = BracketedPasteNormalizer()
    forwarded = normalizer.feed("\x1b[200~" + body + "\x1b[201~")
    return forwarded[len("\x1b[200~") : -len("\x1b[201~")]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "line1\x1b[106;5u│ line2\r\x1b[106;5u\tline3",
            "line1\n│ line2\r\n\tline3",
        ),
        (
            "Ab Z!@#~`{}|\\^_\x1b[97;5ux\x1b[104;5uy\x7fz\x1b[113;3u"
            "\x1b[32;7uw\x1b[107;5uv\x1b[108;5uu\x1b[106;5u",
            "Ab Z!@#~`{}|\\^_\x01x\x08y\x7fzqw\x0bv\x0cu\n",
        ),
        (
            "Ab Z!@#~`{}|\\^_\x1b[27;5;97~x\x1b[27;5;104~y\x7fz"
            "\x1b[27;3;113~\x1b[27;7;32~w\x1b[27;5;107~v"
            "\x1b[27;5;108~u\x1b[27;5;106~",
            "Ab Z!@#~`{}|\\^_\x01x\x08y\x7fzqw\x0bv\x0cu\n",
        ),
    ],
)
def test_normalizes_captured_tmux_paste_bodies(body: str, expected: str) -> None:
    assert _normalize_body(body) == expected


def test_strips_ansi_lone_escape_and_unsupported_modifiers() -> None:
    body = "red\x1b[31m!\x1b[0m\x1bX\x1b[97;9u\x1b[27;17;98~end"
    assert _normalize_body(body) == "red!Xend"


def test_drops_out_of_range_codepoints_and_nul() -> None:
    assert _normalize_body("a\x1b[1114112;1ub\x00c") == "abc"


def test_streaming_matches_one_shot_for_every_split_and_single_char_chunks() -> None:
    start, end = "\x1b[200~", "\x1b[201~"
    body = "line1\x1b[106;5u│ line2\r\x1b[106;5u\tline3"
    plain_body = "line1\n│ line2\r\n\tline3"
    paste = start + body + end
    stream = "ab\x1b" + paste + "\x1b[102;6u" + paste + "z"
    expected = (
        "ab\x1b"
        + start
        + plain_body
        + end
        + "\x1b[102;6u"
        + start
        + plain_body
        + end
        + "z"
    )

    for split in range(len(stream) + 1):
        normalizer = BracketedPasteNormalizer()
        forwarded = normalizer.feed(stream[:split]) + normalizer.feed(stream[split:])
        assert forwarded == expected

    normalizer = BracketedPasteNormalizer()
    forwarded = "".join(normalizer.feed(char) for char in stream)
    assert forwarded == expected


def test_never_holds_back_input_outside_a_paste() -> None:
    normalizer = BracketedPasteNormalizer()
    assert normalizer.feed("\x1b") == "\x1b"
    partial_start = "x\x1b[20"
    assert normalizer.feed(partial_start) == partial_start
