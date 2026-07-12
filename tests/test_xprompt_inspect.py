"""Tests for frontend-agnostic xprompt syntax span inspection."""

from __future__ import annotations

from sase.xprompt import xprompt_inspect
from sase.xprompt.xprompt_inspect import XPromptSpan


def _source_by_kind(text: str, kind: str) -> list[str]:
    return [
        text[span.start : span.end]
        for span in xprompt_inspect.tokenize(text)
        if span.kind == kind
    ]


def test_tokenize_empty_and_marker_free_text() -> None:
    assert xprompt_inspect.tokenize("") == []
    assert xprompt_inspect.tokenize("ordinary prompt text") == []


def test_tokenize_all_invocation_argument_forms() -> None:
    text = (
        "#foo #!bar #ns/name #args(a, k=v) #colon:value "
        "#quoted:`two words` #plus+ #ask!! #skip??\n"
        "#short: text until blank\ncontinues\n\n"
        "#double:: one line\nnext"
    )

    assert _source_by_kind(text, "invocation") == [
        "#foo",
        "#!bar",
        "#ns/name",
        "#args",
        "#colon",
        "#quoted",
        "#plus",
        "#ask!!",
        "#skip??",
        "#short",
        "#double",
    ]
    assert _source_by_kind(text, "invocation_arg") == [
        "(a, k=v)",
        ":value",
        ":`two words`",
        "+",
        ": text until blank\ncontinues",
        ":: one line\nnext",
    ]


def test_tokenize_known_directives_aliases_and_arguments_only() -> None:
    text = "%wait:x %w %model(opus) %m:sonnet %auto %notadirective"

    assert _source_by_kind(text, "directive") == [
        "%wait",
        "%w",
        "%model",
        "%m",
        "%auto",
    ]
    assert _source_by_kind(text, "directive_arg") == [
        ":x",
        "(opus)",
        ":sonnet",
    ]


def test_tokenize_segment_separators_only_on_standalone_lines() -> None:
    text = "before --- after\n---\n  ---  \n----"

    assert _source_by_kind(text, "separator") == ["---"]


def test_tokenize_skips_fences_and_disabled_regions() -> None:
    text = (
        "```text\n#fenced %wait:fenced\n---\n```\n"
        "%xprompts_enabled:false\n#disabled %m:disabled\n---\n"
        "%xprompts_enabled:true\n"
        "#active %wait:active\n---"
    )

    assert _source_by_kind(text, "invocation") == ["#active"]
    assert _source_by_kind(text, "invocation_arg") == []
    assert _source_by_kind(text, "directive") == ["%wait"]
    assert _source_by_kind(text, "directive_arg") == [":active"]
    assert _source_by_kind(text, "separator") == ["---"]


def test_tokenize_rejects_heading_and_midword_markers() -> None:
    text = "# Heading\nword#foo word%wait"

    assert xprompt_inspect.tokenize(text) == []


def test_tokenize_uses_character_offsets_for_multibyte_text() -> None:
    text = "café #foo:value %m:opus"
    spans = xprompt_inspect.tokenize(text)

    assert spans[0] == XPromptSpan(5, 9, "invocation")
    assert text[spans[1].start : spans[1].end] == ":value"
    assert text[spans[2].start : spans[2].end] == "%m"


def test_tokenize_handles_guard_limit_sized_input() -> None:
    text = ("plain text " * 7_000)[:79_950] + "\n#final %auto"

    assert _source_by_kind(text, "invocation") == ["#final"]
    assert _source_by_kind(text, "directive") == ["%auto"]
