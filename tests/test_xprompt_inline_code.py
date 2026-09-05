"""Inline-code literal-zone scanner and launch-semantics coverage."""

from __future__ import annotations

from typing import Any

from sase.xprompt import _inline_code
from sase.xprompt._directive_alt import split_prompt_for_alternatives
from sase.xprompt._fenced_blocks import (
    protect_fenced_blocks,
    unprotect_fenced_blocks,
)
from sase.xprompt._jinja import render_toplevel_jinja2
from sase.xprompt._inline_code import inline_code_spans
from sase.xprompt._literal_zones import (
    code_literal_ranges,
    inline_literal_ranges,
    literal_zone_ranges,
)
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.loader import load_xprompts_from_internal
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


def test_inline_scanner_accepts_punctuation_and_word_adjacency() -> None:
    text = "`foo`/`bar` `foo`,`bar` prefix`value`suffix"

    assert _sources(text, inline_code_spans(text)) == [
        "`foo`",
        "`bar`",
        "`foo`",
        "`bar`",
        "`value`",
    ]


def test_inline_scanner_skips_masked_delimiters() -> None:
    text = "before `masked` after `active`"
    masked_start = text.index("`masked`")

    spans = inline_code_spans(
        text,
        masked_ranges=[(masked_start, masked_start + len("`masked`"))],
    )

    assert _sources(text, spans) == ["`active`"]


def test_inline_scanner_converts_unicode_offsets_at_binding_boundary() -> None:
    text = "é`值`/`ß`"

    assert inline_code_spans(text) == [(1, 4), (5, 8)]
    assert _sources(text, inline_code_spans(text)) == ["`值`", "`ß`"]
    assert inline_code_spans(text, masked_ranges=[(1, 4)]) == [(5, 8)]


def test_inline_scanner_batches_unicode_offset_conversion(monkeypatch: Any) -> None:
    character_calls: list[list[int]] = []
    byte_calls: list[list[int]] = []
    real_character_convert = _inline_code._character_offsets_to_byte_offsets
    real_byte_convert = _inline_code._byte_offsets_to_character_offsets
    text = "é " + " ".join(f"`值{i}`" for i in range(20))
    masked = (text.index("`值0`"), text.index("`值0`") + len("`值0`"))

    def counted_character(text: str, offsets: Any) -> dict[int, int]:
        values = list(offsets)
        character_calls.append(values)
        return real_character_convert(text, values)

    def counted_byte(text: str, offsets: Any) -> dict[int, int]:
        values = list(offsets)
        byte_calls.append(values)
        return real_byte_convert(text, values)

    monkeypatch.setattr(
        _inline_code,
        "_character_offsets_to_byte_offsets",
        counted_character,
    )
    monkeypatch.setattr(
        _inline_code,
        "_byte_offsets_to_character_offsets",
        counted_byte,
    )

    spans = inline_code_spans(text, masked_ranges=[masked])

    assert len(spans) == 19
    assert character_calls == [[masked[0], masked[1]]]
    assert len(byte_calls) == 1
    assert len(byte_calls[0]) == len(spans) * 2


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
        "keep:`#foo`/`#foo` but expand #foo",
        extra_xprompts={"foo": xprompt},
    )

    assert result == "keep:`#foo`/`#foo` but expand expanded"


def test_directive_and_alt_inside_inline_code_survive_verbatim() -> None:
    prompt = "keep:`%m:opus`/`%{fast | slow}`/`{{ 1 + 1 }}`"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.model is None
    assert split_prompt_for_alternatives(prompt) is None
    assert render_toplevel_jinja2(prompt) == prompt


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


def test_typed_xprompt_input_renders_inside_inline_code() -> None:
    xprompt = XPrompt(
        name="show_path",
        content="Open `{{ file_path }}`.",
        inputs=[InputArg(name="file_path", type=InputType.PATH)],
    )

    result = process_xprompt_references(
        "#show_path:src/example.py",
        extra_xprompts={"show_path": xprompt},
    )

    assert result == "Open `src/example.py`."


def test_rendered_value_does_not_activate_neighboring_inline_xprompt() -> None:
    wrapper = XPrompt(
        name="wrapper",
        content="Keep `{{ value }} #child` literal.",
        inputs=[InputArg(name="value", type=InputType.WORD)],
    )
    child = XPrompt(name="child", content="expanded")

    result = process_xprompt_references(
        "#wrapper:rendered",
        extra_xprompts={"wrapper": wrapper, "child": child},
    )

    assert result == "Keep `rendered #child` literal."


def test_packaged_split_file_renders_colon_path_inside_inline_code() -> None:
    split_file = load_xprompts_from_internal()["split_file"]

    result = process_xprompt_references(
        "#split_file:src/sase/ace/tui/modals/projects_pane.py",
        extra_xprompts={"split_file": split_file},
    )

    assert "`src/sase/ace/tui/modals/projects_pane.py`" in result
    assert "{{ file_path }}" not in result
