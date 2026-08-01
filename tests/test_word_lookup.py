"""Tests for prompt word extraction and optional lookup tools."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.core.word_lookup import (
    AddToDictionaryResult,
    DefinitionResult,
    DefinitionSection,
    SpellCheckResult,
    WordSpan,
    add_to_personal_dictionary,
    check_spelling,
    extract_lookup_word,
    look_up_definitions,
    natural_word_ranges,
)

_ASPELL_PIPE_ARGS = ["aspell", "-a", "--encoding=utf-8", "--lang=en_US"]


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


class _DictionaryRunner:
    """A fake runner that distinguishes the add call from the verify call.

    ``add_to_personal_dictionary`` threads the same injected runner through
    both its own aspell invocation (stdin starting with ``*``) and the nested
    ``check_spelling`` verify call (plain ``<word>\\n`` stdin), so a single
    fake must answer both shapes.
    """

    def __init__(
        self,
        *,
        add_returncode: int = 0,
        add_stderr: str = "",
        verify_response: str = "*\n",
    ) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self._add_returncode = add_returncode
        self._add_stderr = add_stderr
        self._verify_response = verify_response

    def __call__(
        self,
        args: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        stdin = str(kwargs.get("input", ""))
        self.calls.append((args, stdin))
        if stdin.startswith("*"):
            return subprocess.CompletedProcess(
                args=args,
                returncode=self._add_returncode,
                stdout="",
                stderr=self._add_stderr,
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=f"@(#) aspell banner\n{self._verify_response}",
            stderr="",
        )


def test_add_to_personal_dictionary_writes_and_verifies_with_shared_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")
    runner = _DictionaryRunner()

    result = add_to_personal_dictionary("Bugyi", runner=runner)

    assert result == AddToDictionaryResult(status="added")
    assert runner.calls == [
        (_ASPELL_PIPE_ARGS, "*Bugyi\n#\n"),
        (_ASPELL_PIPE_ARGS, "Bugyi\n"),
    ]


def test_add_to_personal_dictionary_never_lowercases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")
    runner = _DictionaryRunner()

    add_to_personal_dictionary("BUGYI", runner=runner)

    assert runner.calls[0] == (_ASPELL_PIPE_ARGS, "*BUGYI\n#\n")


def test_add_to_personal_dictionary_surfaces_aspell_stderr_on_verify_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")
    runner = _DictionaryRunner(
        add_stderr=(
            "Error: The word \"well-formedd\" is invalid. The character '-' "
            "(U+2D) may not appear in the middle of a word."
        ),
        verify_response="# well-formedd 0\n",
    )

    result = add_to_personal_dictionary("well-formedd", runner=runner)

    assert result == AddToDictionaryResult(
        status="error",
        detail=(
            "The word \"well-formedd\" is invalid. The character '-' "
            "(U+2D) may not appear in the middle of a word."
        ),
    )


def test_add_to_personal_dictionary_uses_generic_detail_without_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")
    runner = _DictionaryRunner(verify_response="# zzqqword 0\n")

    result = add_to_personal_dictionary("zzqqword", runner=runner)

    assert result == AddToDictionaryResult(
        status="error",
        detail="aspell did not accept the word",
    )


def test_add_to_personal_dictionary_is_unavailable_without_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: None)

    assert add_to_personal_dictionary(
        "word", runner=_unexpected_runner
    ) == AddToDictionaryResult(status="unavailable")


def test_add_to_personal_dictionary_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")

    def timeout_runner(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(["aspell"], 3)

    result = add_to_personal_dictionary("word", runner=timeout_runner)

    assert result.status == "error"
    assert "timed out" in result.detail


def test_add_to_personal_dictionary_reports_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")

    def raising_runner(*_args: object, **_kwargs: object) -> object:
        raise OSError("no such file")

    result = add_to_personal_dictionary("word", runner=raising_runner)

    assert result == AddToDictionaryResult(status="error", detail="no such file")


def test_add_to_personal_dictionary_reports_nonzero_exit_without_verifying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")

    def failing_runner(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="Error: The file can not be opened for writing.",
        )

    result = add_to_personal_dictionary("word", runner=failing_runner)

    assert result == AddToDictionaryResult(
        status="error",
        detail="Error: The file can not be opened for writing.",
    )


@pytest.mark.parametrize("word", ["", "   ", "bad\nword", "bad\rword"])
def test_add_to_personal_dictionary_rejects_unaddable_words_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
    word: str,
) -> None:
    monkeypatch.setattr("sase.core.word_lookup.shutil.which", lambda _cmd: "/aspell")

    result = add_to_personal_dictionary(word, runner=_unexpected_runner)

    assert result == AddToDictionaryResult(status="error", detail="word is not addable")


@pytest.mark.skipif(shutil.which("aspell") is None, reason="requires aspell on PATH")
def test_add_to_personal_dictionary_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    result = add_to_personal_dictionary("zzqqxword")

    assert result == AddToDictionaryResult(status="added")
    pws_files = list(tmp_path.glob(".aspell.en*.pws"))
    assert pws_files
    assert "zzqqxword" in pws_files[0].read_text()
    assert check_spelling("zzqqxword") == SpellCheckResult(status="correct")

    # Adding the same word twice is a no-op: still "added", no duplicate entry.
    second = add_to_personal_dictionary("zzqqxword")
    assert second == AddToDictionaryResult(status="added")
    assert pws_files[0].read_text().count("zzqqxword") == 1


@pytest.mark.skipif(shutil.which("aspell") is None, reason="requires aspell on PATH")
def test_add_to_personal_dictionary_end_to_end_rejects_hyphenated_word(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    # aspell's pipe-add command validates the whole string as one word and
    # rejects the interior hyphen outright, regardless of either half's
    # spelling -- unlike the plain check protocol used by check_spelling's
    # verify step, which tokenizes on the hyphen and checks each half
    # separately. Leading with a bogus segment keeps the verify's own
    # (first-response-line) reading of that tokenized result at "misspelled"
    # too, so this test's outcome doesn't depend on that separate quirk.
    result = add_to_personal_dictionary("zzqqxbogus-word")

    assert result.status == "error"
    assert "-" in result.detail


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
