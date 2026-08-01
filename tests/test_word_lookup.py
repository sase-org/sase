"""Tests for prompt word extraction and optional lookup tools."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest

from sase.core.word_lookup import (
    DefinitionResult,
    DefinitionSection,
    SpellCheckResult,
    WordSpan,
    check_spelling,
    extract_lookup_word,
    look_up_definitions,
    natural_word_ranges,
)


@pytest.mark.parametrize(
    ("line", "col", "expected"),
    [
        ("hello", 0, WordSpan("hello", 3, 0, 5)),
        ("hello", 2, WordSpan("hello", 3, 0, 5)),
        ("hello", 4, WordSpan("hello", 3, 0, 5)),
        ("don't", 3, WordSpan("don't", 3, 0, 5)),
        ("state-of-the-art", 5, WordSpan("state-of-the-art", 3, 0, 16)),
        ("'hello'", 2, WordSpan("hello", 3, 1, 6)),
        ("-hello-", 3, WordSpan("hello", 3, 1, 6)),
        ("café", 3, WordSpan("café", 3, 0, 4)),
    ],
)
def test_extract_lookup_word(
    line: str,
    col: int,
    expected: WordSpan,
) -> None:
    assert extract_lookup_word(line, 3, col) == expected


@pytest.mark.parametrize(
    ("line", "col"),
    [
        ("hello world", 5),
        ("hello, world", 5),
        ("foo_bar", 1),
        ("version2", 1),
        ("2version", 2),
        ("-hello", 0),
        ("hello-", 5),
        ("can't--stop", 2),
        ("", 0),
        ("hello", -1),
        ("hello", 5),
        ("a" * 65, 10),
    ],
)
def test_extract_lookup_word_rejects_non_words(line: str, col: int) -> None:
    assert extract_lookup_word(line, 0, col) is None


def test_extract_lookup_word_accepts_64_char_cap() -> None:
    word = "a" * 64
    assert extract_lookup_word(word, 0, 63) == WordSpan(word, 0, 0, 64)


@pytest.mark.parametrize("response", ["*\n", "+ root\n", "- compound\n"])
def test_check_spelling_parses_correct_responses(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")
    runner = _runner(stdout=f"@(#) aspell banner\n\n{response}")

    assert check_spelling("word", runner=runner) == SpellCheckResult(status="correct")


def test_check_spelling_parses_ranked_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")
    runner = _runner(
        stdout=(
            "@(#) aspell banner\n"
            "& accomodate 3 0: accommodate, accommodated, accommodation\n"
        )
    )

    assert check_spelling("accomodate", runner=runner) == SpellCheckResult(
        status="misspelled",
        suggestions=("accommodate", "accommodated", "accommodation"),
    )


def test_check_spelling_parses_no_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")

    assert check_spelling("zzzz", runner=_runner(stdout="# zzzz 0\n")) == (
        SpellCheckResult(status="misspelled")
    )


def test_check_spelling_is_unavailable_without_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: None)

    assert check_spelling("word", runner=_unexpected_runner) == SpellCheckResult(
        status="unavailable"
    )


def test_check_spelling_reports_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")

    def timeout_runner(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(["aspell"], 3)

    result = check_spelling("word", runner=timeout_runner)

    assert result.status == "error"
    assert "timed out" in result.detail


def test_check_spelling_reports_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")

    result = check_spelling(
        "word",
        runner=_runner(returncode=1, stderr="Error: No word lists can be found\nmore"),
    )

    assert result == SpellCheckResult(
        status="error",
        detail="Error: No word lists can be found",
    )


def test_look_up_definitions_parses_multiple_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/dict")
    stdout = (
        "2 definitions found\n\n"
        "From The Collaborative International Dictionary [gcide]:\n\n"
        "  Hello \\Hel*lo\\, interj.\n"
        "      An expression of greeting.\n\n"
        "From WordNet (r) 3.1 (2024) [wn]:\n\n"
        "  hello\n"
        "      n 1: an expression of greeting\n"
    )

    result = look_up_definitions("hello", runner=_runner(stdout=stdout))

    assert result == DefinitionResult(
        status="ok",
        sections=(
            DefinitionSection(
                source="The Collaborative International Dictionary",
                body=("  Hello \\Hel*lo\\, interj.\n      An expression of greeting."),
            ),
            DefinitionSection(
                source="WordNet (r) 3.1 (2024)",
                body="  hello\n      n 1: an expression of greeting",
            ),
        ),
    )


def test_look_up_definitions_uses_documented_no_match_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/dict")

    result = look_up_definitions(
        "zzzz",
        runner=_runner(returncode=20, stderr="No definitions found for zzzz\n"),
    )

    assert result == DefinitionResult(
        status="no_match",
        detail="No definitions found for zzzz",
    )


def test_look_up_definitions_reports_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/dict")

    result = look_up_definitions(
        "hello",
        runner=_runner(returncode=41, stderr="Connection to server failed\n"),
    )

    assert result == DefinitionResult(
        status="error",
        detail="Connection to server failed",
    )


def test_look_up_definitions_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/dict")

    def timeout_runner(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(["dict"], 5)

    result = look_up_definitions("hello", runner=timeout_runner)

    assert result.status == "error"
    assert "timed out" in result.detail


def test_look_up_definitions_is_unavailable_without_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: None)

    assert look_up_definitions(
        "hello",
        runner=_unexpected_runner,
    ) == DefinitionResult(status="unavailable")


def _runner(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(
        args: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def _unexpected_runner(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("runner should not be called")


def _offset_to_location(text: str, offset: int) -> tuple[int, int]:
    row = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    return row, offset - line_start


def test_natural_word_ranges_agrees_with_extract_lookup_word_everywhere() -> None:
    text = (
        "Hello world, don't-worry\n"
        "café state-of-the-art 'quoted'\n"
        "skip_this version2 2cool -edge- keep\n"
    )
    lines = text.split("\n")

    ranges = list(natural_word_ranges(text))
    assert ranges

    for start, end, word in ranges:
        assert text[start:end] == word
        row, start_col = _offset_to_location(text, start)
        end_row, end_col = _offset_to_location(text, end)
        assert row == end_row

        for col in range(start_col, end_col):
            span = extract_lookup_word(lines[row], row, col)
            assert span == WordSpan(word, row, start_col, end_col)


def test_natural_word_ranges_rejects_digit_and_underscore_runs() -> None:
    words = [
        word for _start, _end, word in natural_word_ranges("skip_this version2 2cool")
    ]
    assert words == []


def test_natural_word_ranges_accepts_interior_connectors_and_trims_edges() -> None:
    words = [
        word
        for _start, _end, word in natural_word_ranges(
            "-hello- don't 'quoted' state-of-the-art"
        )
    ]
    assert words == ["hello", "don't", "quoted", "state-of-the-art"]


def test_natural_word_ranges_enforces_the_64_char_cap() -> None:
    too_long = "a" * 65
    exactly_64 = "a" * 64

    assert list(natural_word_ranges(too_long)) == []
    assert list(natural_word_ranges(exactly_64)) == [(0, 64, exactly_64)]


def test_natural_word_ranges_uses_absolute_offsets_across_lines() -> None:
    text = "first line\nsecond café line\nthird line"

    ranges = list(natural_word_ranges(text))

    assert (text.index("café"), text.index("café") + len("café"), "café") in ranges
    third_start = text.index("third")
    assert (third_start, third_start + len("third"), "third") in ranges
