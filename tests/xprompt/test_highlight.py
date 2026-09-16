from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from sase.xprompt import highlight
from sase.xprompt.highlight import (
    MAX_HIGHLIGHT_BYTES,
    MAX_HIGHLIGHT_LINES,
    HighlightSpan,
    highlight_spans,
)


def _parts(text: str) -> list[tuple[str, str]]:
    return [(text[span.start : span.end], span.role) for span in highlight_spans(text)]


def test_flattens_overlapping_invocation_and_jinja_by_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        highlight,
        "_get_xprompt_argument_spans_binding",
        lambda: None,
    )
    text = "#foo({{ bar | upper }})"

    assert _parts(text) == [
        ("#foo", "xprompt.invocation"),
        ("(", "xprompt.invocation_arg"),
        ("{{", "jinja.delimiter"),
        (" ", "xprompt.invocation_arg"),
        ("bar", "jinja.variable"),
        (" ", "xprompt.invocation_arg"),
        ("|", "jinja.operator"),
        (" ", "xprompt.invocation_arg"),
        ("upper", "jinja.filter"),
        (" ", "xprompt.invocation_arg"),
        ("}}", "jinja.delimiter"),
        (")", "xprompt.invocation_arg"),
    ]


def test_flattens_directive_argument_over_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        highlight,
        "_get_xprompt_argument_spans_binding",
        lambda: None,
    )
    text = "%model(<model>)"

    assert _parts(text) == [
        ("%model", "xprompt.directive"),
        ("(", "xprompt.directive_arg"),
        ("<model>", "placeholder"),
        (")", "xprompt.directive_arg"),
    ]


def test_core_argument_spans_are_layered_over_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = '#foo(é=12,label="x")'

    def byte_span(start: int, end: int) -> tuple[int, int]:
        return len(text[:start].encode()), len(text[:end].encode())

    def raw(start: int, end: int, role: str, validity: str = "ok") -> dict[str, object]:
        start_byte, end_byte = byte_span(start, end)
        return {
            "start": start_byte,
            "end": end_byte,
            "role": role,
            "validity": validity,
            "source": "xprompt",
            "call_name": "foo",
        }

    def fake_binding(
        passed_text: str,
        entries: list[dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        assert passed_text == text
        assert entries is None
        return [
            raw(4, 5, "arg_delimiter"),
            raw(5, 6, "arg_key", "unknown_key"),
            raw(6, 7, "arg_assign"),
            raw(7, 9, "arg_value_number"),
            raw(9, 10, "arg_delimiter"),
            raw(10, 15, "arg_key"),
            raw(15, 16, "arg_assign"),
            raw(16, 19, "arg_value_string"),
            raw(19, 20, "arg_delimiter"),
        ]

    monkeypatch.setattr(
        highlight,
        "_get_xprompt_argument_spans_binding",
        lambda: fake_binding,
    )

    spans = highlight_spans(text)

    assert [(text[span.start : span.end], span.role) for span in spans] == [
        ("#foo", "xprompt.invocation"),
        ("(", "xprompt.arg_delimiter"),
        ("é", "xprompt.arg_key"),
        ("=", "xprompt.arg_assign"),
        ("12", "xprompt.arg_value_number"),
        (",", "xprompt.arg_delimiter"),
        ("label", "xprompt.arg_key"),
        ("=", "xprompt.arg_assign"),
        ('"x"', "xprompt.arg_value_string"),
        (")", "xprompt.arg_delimiter"),
    ]
    key_span = next(span for span in spans if text[span.start : span.end] == "é")
    assert key_span.validity == "unknown_key"
    assert key_span.source == "xprompt"


def test_alt_block_preserves_nested_invocations() -> None:
    text = "%{left= #foo | right= #bar}"

    assert _parts(text) == [
        ("%{", "alt.delimiter"),
        ("left", "alt.branch_name"),
        ("#foo", "xprompt.invocation"),
        ("|", "alt.separator"),
        ("right", "alt.branch_name"),
        ("#bar", "xprompt.invocation"),
        ("}", "alt.delimiter"),
    ]


def test_code_literals_suppress_xprompt_roles() -> None:
    text = "```text\n#fenced\n```\n`#inline` #outside"

    assert _parts(text) == [
        ("```text\n#fenced\n```", "code.fence"),
        ("`#inline`", "code.inline"),
        ("#outside", "xprompt.invocation"),
    ]


def test_placeholder_utf16_and_artifact_byte_ranges_become_character_offsets() -> None:
    text = "😀 <topic> @file:notes/é.md"

    assert _parts(text) == [
        ("<topic>", "placeholder"),
        ("@file:notes/é.md", "artifact_ref"),
    ]


def test_artifact_scanning_can_be_disabled() -> None:
    assert highlight_spans("@file:notes/example.md", include_artifact_refs=False) == []


@pytest.mark.parametrize(
    "text",
    [
        "x" * (MAX_HIGHLIGHT_BYTES + 1),
        "\n" * (MAX_HIGHLIGHT_LINES + 1),
    ],
    ids=["over-byte-limit", "over-line-limit"],
)
def test_size_guards_return_no_spans(text: str) -> None:
    assert highlight_spans(text) == []


def test_one_scanner_failure_degrades_to_remaining_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("scanner unavailable")

    monkeypatch.setattr(highlight.xprompt_inspect, "tokenize", fail)

    assert _parts("#foo {{ value }}") == [
        ("{{", "jinja.delimiter"),
        ("value", "jinja.variable"),
        ("}}", "jinja.delimiter"),
    ]


def test_identical_spans_resolve_by_role_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_scanners(monkeypatch)
    monkeypatch.setattr(
        highlight.xprompt_inspect,
        "tokenize",
        lambda text, *, known_skills: [
            SimpleNamespace(start=0, end=4, kind="invocation")
        ],
    )
    monkeypatch.setattr(
        highlight.jinja_inspect,
        "tokenize",
        lambda text: [SimpleNamespace(start=0, end=4, kind="variable")],
    )

    assert highlight_spans("#foo") == [HighlightSpan(0, 4, "xprompt.invocation")]


def test_adjacent_same_role_spans_are_not_merged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_scanners(monkeypatch)
    monkeypatch.setattr(
        highlight.xprompt_inspect,
        "tokenize",
        lambda text, *, known_skills: [
            SimpleNamespace(start=0, end=1, kind="invocation"),
            SimpleNamespace(start=1, end=2, kind="invocation"),
        ],
    )

    assert highlight_spans("##") == [
        HighlightSpan(0, 1, "xprompt.invocation"),
        HighlightSpan(1, 2, "xprompt.invocation"),
    ]


def test_clamps_ranges_and_drops_zero_width_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_scanners(monkeypatch)
    monkeypatch.setattr(
        highlight.xprompt_inspect,
        "tokenize",
        lambda text, *, known_skills: [
            SimpleNamespace(start=-10, end=2, kind="invocation"),
            SimpleNamespace(start=2, end=100, kind="directive"),
            SimpleNamespace(start=1, end=1, kind="skill"),
        ],
    )

    assert highlight_spans("abcd") == [
        HighlightSpan(0, 2, "xprompt.invocation"),
        HighlightSpan(2, 4, "xprompt.directive"),
    ]


def test_calls_each_scanner_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, int] = {}

    def once(name: str, result: Any) -> Callable[..., Any]:
        def scanner(*args: object, **kwargs: object) -> Any:
            calls[name] = calls.get(name, 0) + 1
            return result

        return scanner

    monkeypatch.setattr(highlight.xprompt_inspect, "tokenize", once("xprompt", []))
    monkeypatch.setattr(highlight.jinja_inspect, "tokenize", once("jinja", []))
    monkeypatch.setattr(highlight.alt_inspect, "tokenize", once("alt", []))
    monkeypatch.setattr(highlight, "placeholder_spans", once("placeholder", ()))
    monkeypatch.setattr(highlight, "scan_artifact_refs", once("artifact", ()))
    monkeypatch.setattr(highlight, "fenced_block_details", once("fenced", []))
    monkeypatch.setattr(highlight, "inline_literal_ranges", once("inline", []))

    assert highlight_spans("ordinary text") == []
    assert calls == {
        "xprompt": 1,
        "jinja": 1,
        "alt": 1,
        "placeholder": 1,
        "artifact": 1,
        "fenced": 1,
        "inline": 1,
    }


def test_output_is_strictly_ordered_and_non_overlapping() -> None:
    text = "#foo(arg) {{ value | upper }} %alt(#one, #two) <topic> @file:a.md"
    spans = highlight_spans(text)

    assert all(span.start < span.end for span in spans)
    assert all(
        left.end <= right.start for left, right in zip(spans, spans[1:], strict=False)
    )


def _isolate_scanners(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        highlight.xprompt_inspect,
        "tokenize",
        lambda text, *, known_skills: [],
    )
    monkeypatch.setattr(highlight.jinja_inspect, "tokenize", lambda text: [])
    monkeypatch.setattr(highlight.alt_inspect, "tokenize", lambda text: [])
    monkeypatch.setattr(highlight, "placeholder_spans", lambda text: ())
    monkeypatch.setattr(highlight, "scan_artifact_refs", lambda text: ())
    monkeypatch.setattr(highlight, "fenced_block_details", lambda text: [])
    monkeypatch.setattr(highlight, "inline_literal_ranges", lambda text: [])
