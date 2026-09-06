"""Shared fenced output-tail prompt behavior."""

from __future__ import annotations

from sase.procs.text_bounding import tail_text_by_lines_and_chars
from sase.shells.prompt import OUTPUT_TAIL_MAX_CHARS, untrusted_output_section
from sase.xprompt.directives import extract_prompt_directives


def _tail_block(section: list[str]) -> tuple[str, str]:
    for index, line in enumerate(section):
        if line.endswith("text") and set(line[:-4]) == {"`"}:
            return line[:-4], section[index + 1]
    raise AssertionError("missing fenced text block")


def test_tail_adapter_keeps_short_text_and_drops_trailing_newline() -> None:
    result = tail_text_by_lines_and_chars("one\ntwo\nthree\n", 10, 100)

    assert result.text == "one\ntwo\nthree"
    assert result.omitted_lines == 0
    assert result.omitted_chars == 0


def test_tail_adapter_applies_line_budget_before_character_budget() -> None:
    result = tail_text_by_lines_and_chars("one\ntwo\nthree\nfour", 2, 8)

    assert result.text == "ree\nfour"
    assert result.omitted_lines == 2
    assert result.omitted_chars == 2


def test_tail_adapter_handles_zero_line_budget() -> None:
    result = tail_text_by_lines_and_chars("one\ntwo", 0, 100)

    assert result.text == ""
    assert result.omitted_lines == 2
    assert result.omitted_chars == 0


def test_tail_adapter_counts_unicode_characters_like_python_len() -> None:
    text = "drop\nbé值ta"
    result = tail_text_by_lines_and_chars(text, 1, len("é值ta"))

    assert result.text == "é值ta"
    assert result.omitted_lines == 1
    assert result.omitted_chars == 1


def test_untrusted_output_section_caps_a_single_huge_line() -> None:
    output = "discard:" + ("x" * OUTPUT_TAIL_MAX_CHARS)
    section = untrusted_output_section("## Output", output, 1)
    fence, tail = _tail_block(section)
    rendered = "\n".join(section)

    assert fence == "```"
    assert tail == "x" * OUTPUT_TAIL_MAX_CHARS
    assert "discard:" not in tail
    assert "Output tail truncated: omitted 8 earlier characters." in rendered


def test_untrusted_output_section_widens_fence_after_tail_selection() -> None:
    section = untrusted_output_section(
        "## Output",
        "`````` omitted from line budget\nkept tail",
        1,
    )
    fence, tail = _tail_block(section)

    assert tail == "kept tail"
    assert fence == "```"


def test_untrusted_output_section_output_directives_remain_literal() -> None:
    section = untrusted_output_section(
        "## Output",
        "before\n%model:haiku\n#commit now",
        3,
    )
    rendered = "\n".join(section)

    cleaned, directives = extract_prompt_directives(rendered)
    assert directives.model is None
    assert "%model:haiku" in cleaned
    assert "#commit now" in cleaned
