"""Inline-code literal-zone scanner and launch-semantics coverage."""

from __future__ import annotations

from sase.xprompt._directive_alt import split_prompt_for_alternatives
from sase.xprompt._fenced_blocks import (
    protect_fenced_blocks,
    unprotect_fenced_blocks,
)
from sase.xprompt._inline_code import inline_code_spans
from sase.xprompt._literal_zones import (
    code_literal_ranges,
    inline_literal_ranges,
    literal_zone_ranges,
)
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.processor import process_xprompt_references


def _sources(text: str, spans: list[tuple[int, int]]) -> list[str]:
    return [text[start:end] for start, end in spans]


def test_inline_scanner_matches_equal_length_runs_on_one_line() -> None:
    text = "`one `` nested`` end` and ``two ` inner` end``"

    assert _sources(text, inline_code_spans(text)) == [
        "`one `` nested`` end`",
        "``two ` inner` end``",
    ]


def test_inline_scanner_ignores_unmatched_and_multiline_runs() -> None:
    assert inline_code_spans("before `unmatched") == []
    assert inline_code_spans("`first line\nsecond line`") == []


def test_inline_scanner_requires_xprompt_leading_context() -> None:
    text = "word`no` colon:`no` (#yes) [`also`] ' `quoted`'"

    assert _sources(text, inline_code_spans(text)) == [
        "`also`",
        "`quoted`",
    ]


def test_inline_scanner_skips_masked_delimiters() -> None:
    text = "before `masked` after `active`"
    masked_start = text.index("`masked`")

    spans = inline_code_spans(
        text,
        masked_ranges=[(masked_start, masked_start + len("`masked`"))],
    )

    assert _sources(text, spans) == ["`active`"]


def test_launch_masks_reference_and_directive_argument_backticks() -> None:
    text = "#research(compare `a` and `b`) %model(alias=`custom model`)"

    assert inline_literal_ranges(text) == []


def test_colon_argument_backticks_never_open_inline_code() -> None:
    text = "#name:`arg with spaces` %model:`custom model`"

    assert inline_literal_ranges(text) == []


def test_fenced_and_disabled_regions_win_over_inline_scanning() -> None:
    text = (
        "```text\n`fenced`\n```\n"
        "%xprompts_enabled:false\n`disabled`\n%xprompts_enabled:true\n"
        "`active`"
    )

    assert _sources(text, inline_literal_ranges(text)) == ["`active`"]
    assert len(code_literal_ranges(text)) == 2
    assert len(literal_zone_ranges(text)) == 2


def test_legacy_protection_api_round_trips_inline_and_fenced_code() -> None:
    text = "before `#inline`\n```\n#fenced\n```\nafter"
    blocks: list[str] = []

    protected = protect_fenced_blocks(text, blocks)

    assert blocks == ["`#inline`", "```\n#fenced\n```"]
    assert "#inline" not in protected
    assert "#fenced" not in protected
    assert unprotect_fenced_blocks(protected, blocks) == text


def test_xprompt_reference_inside_inline_code_survives_launch_expansion() -> None:
    xprompt = XPrompt(name="foo", content="expanded")

    result = process_xprompt_references(
        "keep `#foo` but expand #foo",
        extra_xprompts={"foo": xprompt},
    )

    assert result == "keep `#foo` but expand expanded"


def test_directive_and_alt_inside_inline_code_survive_verbatim() -> None:
    prompt = "keep `%m:opus` and `%{fast | slow}`"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.model is None
    assert split_prompt_for_alternatives(prompt) is None


def test_backtick_colon_argument_still_expands_normally() -> None:
    xprompt = XPrompt(
        name="echo",
        content="Value: {{ value }}",
        inputs=[InputArg(name="value", type=InputType.LINE)],
    )

    result = process_xprompt_references(
        "#echo:`two words`",
        extra_xprompts={"echo": xprompt},
    )

    assert result == "Value: two words"
