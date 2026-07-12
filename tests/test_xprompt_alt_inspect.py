"""Tests for the alt fan-out span scanner."""

from __future__ import annotations

from sase.xprompt import alt_inspect
from sase.xprompt.alt_inspect import AltSpan


def _kinds(text: str) -> list[str]:
    return [span.kind for span in alt_inspect.tokenize(text)]


def _of_kind(text: str, kind: str) -> list[AltSpan]:
    return [span for span in alt_inspect.tokenize(text) if span.kind == kind]


def test_tokenize_empty_without_marker() -> None:
    assert alt_inspect.tokenize("plain prompt with (parens) and | bars") == []


def test_tokenize_marks_delimiters_and_separators() -> None:
    text = "%{a | b | c}"
    spans = alt_inspect.tokenize(text)

    delimiters = [s for s in spans if s.kind == "delimiter"]
    separators = [s for s in spans if s.kind == "separator"]

    # Opener covers "%{", closer covers the trailing "}".
    assert (delimiters[0].start, delimiters[0].end) == (0, 2)
    assert text[delimiters[0].start : delimiters[0].end] == "%{"
    assert delimiters[1].end == len(text)
    assert text[delimiters[1].start : delimiters[1].end] == "}"

    assert len(separators) == 2
    for sep in separators:
        assert text[sep.start : sep.end] == "|"


def test_tokenize_marks_named_branch_prefix() -> None:
    text = "%{fast=a | b}"
    names = _of_kind(text, "branch_name")

    assert len(names) == 1
    assert text[names[0].start : names[0].end] == "fast"


def test_tokenize_named_text_block_branches() -> None:
    text = "%{sec=[[security]] | perf=[[performance]]}"
    names = [text[s.start : s.end] for s in _of_kind(text, "branch_name")]

    assert names == ["sec", "perf"]


def test_tokenize_ignores_nested_and_quoted_pipes() -> None:
    # Mirrors the Rust ``fanout_planner_brace_nested_pipes_do_not_split`` case:
    # only the two top-level separators are real.
    text = "%{a (x | y) | b [c | d] | `e | f`}"
    separators = _of_kind(text, "separator")

    # Only the two top-level ``|`` are separators; the ones inside ``()``,
    # ``[]`` and backticks are branch text.
    assert [s.start for s in separators] == [12, 24]
    assert all(text[s.start : s.end] == "|" for s in separators)


def test_tokenize_ignores_closing_brace_inside_backticks() -> None:
    text = "%{a | `literal } brace` | b}"
    spans = alt_inspect.tokenize(text)

    delimiters = [span for span in spans if span.kind == "delimiter"]
    assert text[delimiters[-1].start : delimiters[-1].end] == "}"
    assert delimiters[-1].start == len(text) - 1


def test_tokenize_unmatched_opener_is_error() -> None:
    text = "before %{a | b after"
    spans = alt_inspect.tokenize(text)

    assert _kinds(text) == ["error"]
    error = spans[0]
    assert text[error.start : error.end] == "%{"
    # No separators emitted for an unclosed directive.
    assert not _of_kind(text, "separator")


def test_tokenize_requires_directive_valid_position() -> None:
    # ``%{`` glued to a word character is not a directive opener.
    assert alt_inspect.tokenize("foo%{a | b}") == []
    # Start of line, after whitespace, brackets/quotes, and directive-value
    # colon are valid.
    for prefix in ("", " ", "(", "[", "{", '"', "'", ":"):
        text = f"{prefix}%{{a | b}}"
        assert any(s.kind == "delimiter" for s in alt_inspect.tokenize(text))


def test_tokenize_marks_value_fanout_after_directive_colon() -> None:
    text = "%effort:%{medium | high}"
    spans = alt_inspect.tokenize(text)

    assert [span.kind for span in spans] == [
        "delimiter",
        "separator",
        "delimiter",
    ]
    assert text[spans[0].start : spans[0].end] == "%{"
    assert text[spans[1].start : spans[1].end] == "|"
    assert text[spans[2].start : spans[2].end] == "}"


def test_tokenize_skips_fenced_code_blocks() -> None:
    text = "```\n%{a | b}\n```\n%{c | d}"
    spans = alt_inspect.tokenize(text)

    # Only the directive outside the fence is highlighted.
    delimiters = [s for s in spans if s.kind == "delimiter"]
    assert len(delimiters) == 2
    assert all(s.start > text.index("```\n", 3) for s in spans)


def test_tokenize_single_branch_has_no_separator() -> None:
    text = "before %{a} after"
    assert _kinds(text) == ["delimiter", "delimiter"]


def test_tokenize_multibyte_offsets_are_character_based() -> None:
    text = "café %{a | b}"
    spans = alt_inspect.tokenize(text)
    opener = next(s for s in spans if s.kind == "delimiter")
    assert text[opener.start : opener.end] == "%{"


def test_tokenize_marks_named_paren_forms_and_commas() -> None:
    text = "%alt(fast=a, slow=call(x, y)) %(left, right)"
    spans = alt_inspect.tokenize(text)

    assert [text[s.start : s.end] for s in spans if s.kind == "delimiter"] == [
        "%alt(",
        ")",
        "%(",
        ")",
    ]
    assert [text[s.start : s.end] for s in spans if s.kind == "separator"] == [
        ",",
        ",",
    ]
    assert [text[s.start : s.end] for s in spans if s.kind == "branch_name"] == [
        "fast",
        "slow",
    ]


def test_tokenize_paren_forms_ignore_quoted_and_text_block_commas() -> None:
    text = '%alt("a,b", block=[[c,d]], last)'

    separators = _of_kind(text, "separator")
    assert [text[s.start : s.end] for s in separators] == [",", ","]
    assert [text[s.start : s.end] for s in _of_kind(text, "branch_name")] == ["block"]


def test_tokenize_marks_unmatched_paren_opener_as_error() -> None:
    for text in ("%alt(a, b", "%(a, b"):
        spans = alt_inspect.tokenize(text)
        assert [span.kind for span in spans] == ["error"]
        assert text[spans[0].start : spans[0].end].endswith("(")


def test_tokenize_skips_disabled_regions() -> None:
    text = "%xprompts_enabled:false\n%alt(a, b)\n%xprompts_enabled:true\n%(c, d)"

    assert [
        text[span.start : span.end]
        for span in alt_inspect.tokenize(text)
        if span.kind == "delimiter"
    ] == ["%(", ")"]
