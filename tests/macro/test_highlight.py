from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from sase.macro import highlight
from sase.macro.highlight import (
    MAX_HIGHLIGHT_BYTES,
    MAX_HIGHLIGHT_LINES,
    HighlightSpan,
    highlight_spans,
)


def _parts(text: str) -> list[tuple[str, str]]:
    return [(text[span.start : span.end], span.role) for span in highlight_spans(text)]


def test_macro_input_hint_wire_copies_rich_and_legacy_metadata() -> None:
    enriched = {
        "name": "environment",
        "type": "enum",
        "choices": [
            {
                "value": "staging",
                "label": "Staging",
                "description": "Pre-production.",
            }
        ],
        "named_type": "deploy_environment",
        "value_role": None,
    }

    wire = highlight._macro_input_hint_to_wire(enriched)
    assert wire["choices"] == enriched["choices"]
    assert wire["named_type"] == "deploy_environment"
    assert wire["value_role"] is None

    object_hint = SimpleNamespace(
        name="environment",
        type="enum",
        choices=(
            SimpleNamespace(
                value="prod", label="Production", description="Customer traffic."
            ),
        ),
        named_type="deploy_environment",
        value_role=None,
    )
    object_wire = highlight._macro_input_hint_to_wire(object_hint)
    assert object_wire["choices"] == [
        {
            "value": "prod",
            "label": "Production",
            "description": "Customer traffic.",
        }
    ]
    assert object_wire["named_type"] == "deploy_environment"

    legacy = highlight._macro_input_hint_to_wire({"name": "topic", "type": "text"})
    assert legacy["choices"] == []
    assert legacy["named_type"] is None
    assert legacy["value_role"] is None


def test_flattens_overlapping_invocation_and_jinja_by_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        highlight,
        "_get_macro_argument_spans_binding",
        lambda: None,
    )
    text = "#foo({{ bar | upper }})"

    assert _parts(text) == [
        ("#foo", "macro.invocation"),
        ("(", "macro.invocation_arg"),
        ("{{", "jinja.delimiter"),
        (" ", "macro.invocation_arg"),
        ("bar", "jinja.variable"),
        (" ", "macro.invocation_arg"),
        ("|", "jinja.operator"),
        (" ", "macro.invocation_arg"),
        ("upper", "jinja.filter"),
        (" ", "macro.invocation_arg"),
        ("}}", "jinja.delimiter"),
        (")", "macro.invocation_arg"),
    ]


def test_flattens_directive_argument_over_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        highlight,
        "_get_macro_argument_spans_binding",
        lambda: None,
    )
    text = "%model(<model>)"

    assert _parts(text) == [
        ("%model", "macro.directive"),
        ("(", "macro.directive_arg"),
        ("<model>", "placeholder"),
        (")", "macro.directive_arg"),
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
            "source": "macro",
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
        "_get_macro_argument_spans_binding",
        lambda: fake_binding,
    )

    spans = highlight_spans(text)

    assert [(text[span.start : span.end], span.role) for span in spans] == [
        ("#foo", "macro.invocation"),
        ("(", "macro.arg_delimiter"),
        ("é", "macro.arg_key"),
        ("=", "macro.arg_assign"),
        ("12", "macro.arg_value_number"),
        (",", "macro.arg_delimiter"),
        ("label", "macro.arg_key"),
        ("=", "macro.arg_assign"),
        ('"x"', "macro.arg_value_string"),
        (")", "macro.arg_delimiter"),
    ]
    key_span = next(span for span in spans if text[span.start : span.end] == "é")
    assert key_span.validity == "unknown_key"
    assert key_span.source == "macro"


def test_source_value_maps_legacy_xprompt_to_macro() -> None:
    assert highlight._source_value("xprompt") == "macro"
    assert highlight._source_value("macro") == "macro"
    assert highlight._source_value("directive") == "directive"
    assert highlight._source_value("unknown") is None
    assert highlight._source_value(None) is None


def test_alt_block_preserves_nested_invocations() -> None:
    text = "%{left= #foo | right= #bar}"

    assert _parts(text) == [
        ("%{", "alt.delimiter"),
        ("left", "alt.branch_name"),
        ("#foo", "macro.invocation"),
        ("|", "alt.separator"),
        ("right", "alt.branch_name"),
        ("#bar", "macro.invocation"),
        ("}", "alt.delimiter"),
    ]


def test_code_literals_suppress_macro_roles() -> None:
    text = "```text\n#fenced\n```\n`#inline` #outside"

    assert _parts(text) == [
        ("```text\n#fenced\n```", "code.fence"),
        ("`#inline`", "code.inline"),
        ("#outside", "macro.invocation"),
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

    monkeypatch.setattr(highlight.macro_inspect, "tokenize", fail)

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
        highlight.macro_inspect,
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

    assert highlight_spans("#foo") == [HighlightSpan(0, 4, "macro.invocation")]


def test_adjacent_same_role_spans_are_not_merged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_scanners(monkeypatch)
    monkeypatch.setattr(
        highlight.macro_inspect,
        "tokenize",
        lambda text, *, known_skills: [
            SimpleNamespace(start=0, end=1, kind="invocation"),
            SimpleNamespace(start=1, end=2, kind="invocation"),
        ],
    )

    assert highlight_spans("##") == [
        HighlightSpan(0, 1, "macro.invocation"),
        HighlightSpan(1, 2, "macro.invocation"),
    ]


def test_clamps_ranges_and_drops_zero_width_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_scanners(monkeypatch)
    monkeypatch.setattr(
        highlight.macro_inspect,
        "tokenize",
        lambda text, *, known_skills: [
            SimpleNamespace(start=-10, end=2, kind="invocation"),
            SimpleNamespace(start=2, end=100, kind="directive"),
            SimpleNamespace(start=1, end=1, kind="skill"),
        ],
    )

    assert highlight_spans("abcd") == [
        HighlightSpan(0, 2, "macro.invocation"),
        HighlightSpan(2, 4, "macro.directive"),
    ]


def test_calls_each_scanner_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, int] = {}

    def once(name: str, result: Any) -> Callable[..., Any]:
        def scanner(*args: object, **kwargs: object) -> Any:
            calls[name] = calls.get(name, 0) + 1
            return result

        return scanner

    monkeypatch.setattr(highlight.macro_inspect, "tokenize", once("macro", []))
    monkeypatch.setattr(highlight.jinja_inspect, "tokenize", once("jinja", []))
    monkeypatch.setattr(highlight.alt_inspect, "tokenize", once("alt", []))
    monkeypatch.setattr(highlight, "placeholder_spans", once("placeholder", ()))
    monkeypatch.setattr(highlight, "scan_artifact_refs", once("artifact", ()))
    monkeypatch.setattr(highlight, "fenced_block_details", once("fenced", []))
    monkeypatch.setattr(highlight, "inline_literal_ranges", once("inline", []))

    assert highlight_spans("ordinary text") == []
    assert calls == {
        "macro": 1,
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


def _warm_tag_catalog(
    monkeypatch: pytest.MonkeyPatch,
    *accents: tuple[str, str],
) -> None:
    """Point the tag tokenizer's catalog peek at fake targets.

    Each ``(key, accent)`` pair becomes one enabled ``gh`` target, so
    adjacent tags keep distinguishable accents through flattening.
    """
    from sase.project_tags.catalog import ProjectTagCatalog, ProjectTagTarget

    pairs = accents or (("sase", "#C75A31"),)
    catalog = ProjectTagCatalog(
        targets=tuple(
            ProjectTagTarget(
                key=key,
                name=key,
                tag=f"+{key}",
                workflow_type="gh",
                accent=accent,
            )
            for key, accent in pairs
        ),
        accent_palette=(),
    )
    monkeypatch.setattr(
        "sase.project_tags.catalog.peek_project_tag_catalog",
        lambda: catalog,
    )


def test_project_tag_splits_sigil_and_name_with_accent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _warm_tag_catalog(monkeypatch)

    assert highlight_spans("+sase run") == [
        HighlightSpan(0, 1, "macro.project_tag.sigil", accent="#C75A31"),
        HighlightSpan(1, 5, "macro.project_tag.name", accent="#C75A31"),
    ]


def test_project_tag_unknown_only_for_anchored_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _warm_tag_catalog(monkeypatch)

    assert _parts("+ssae run") == [("+ssae", "macro.project_tag.unknown")]
    assert _parts("run +ssae") == []


def test_project_tag_spans_keep_their_accents_through_flattening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _warm_tag_catalog(monkeypatch, ("sase", "#C75A31"), ("bob", "#4379D3"))

    assert highlight_spans("+sase +bob") == [
        HighlightSpan(0, 1, "macro.project_tag.sigil", accent="#C75A31"),
        HighlightSpan(1, 5, "macro.project_tag.name", accent="#C75A31"),
        HighlightSpan(6, 7, "macro.project_tag.sigil", accent="#4379D3"),
        HighlightSpan(7, 10, "macro.project_tag.name", accent="#4379D3"),
    ]


def test_project_tags_coexist_with_alt_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _warm_tag_catalog(monkeypatch, ("sase", "#C75A31"), ("bob", "#4379D3"))
    text = "%{+sase | +bob}"

    assert _parts(text) == [
        ("%{", "alt.delimiter"),
        ("+", "macro.project_tag.sigil"),
        ("sase", "macro.project_tag.name"),
        ("|", "alt.separator"),
        ("+", "macro.project_tag.sigil"),
        ("bob", "macro.project_tag.name"),
        ("}", "alt.delimiter"),
    ]


def test_alt_callers_share_one_binding_scan_per_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One rebuild's alt callers share a single core scan; plain text skips FFI."""
    from rich.style import Style

    from sase.ace.tui.util import semantic_overlay, macro_syntax
    from sase.ace.tui.util.semantic_styles import SemanticHighlightStyles
    from sase.macro import alt_inspect

    calls: list[str] = []

    def fake_scan(text: str) -> list[dict[str, object]]:
        calls.append(text)
        return [
            {
                "form": "brace",
                "marker_start": 3,
                "opener_end": 5,
                "close": 14,
                "separators": [9],
                "branch_names": [],
                "depth": 0,
            }
        ]

    monkeypatch.setattr(alt_inspect, "_get_alternation_scan_binding", lambda: fake_scan)
    alt_inspect._cached_records.cache_clear()
    try:
        text = "foo%{bar | baz}qux"
        assert highlight_spans(text)
        assert macro_syntax.macro_overlay_spans(text)
        target = SimpleNamespace(stylize=lambda *args, **kwargs: None)
        semantic_overlay.apply_semantic_overlays(
            target,
            text,
            styles=SemanticHighlightStyles(glossary=Style(), repo=Style()),
            skip_macro=True,
        )
        delimiters = [
            span for span in alt_inspect.tokenize(text) if span.kind == "delimiter"
        ]
        assert len(delimiters) > 0
        assert len(tuple(alt_inspect.groups(text))) > 0
        assert calls == [text]

        calls.clear()
        plain = "ordinary text with 50% effort"
        assert highlight_spans(plain) == []
        assert macro_syntax.macro_overlay_spans(plain) == ()
        semantic_overlay.apply_semantic_overlays(
            target,
            plain,
            styles=SemanticHighlightStyles(glossary=Style(), repo=Style()),
            skip_macro=True,
        )
        assert alt_inspect.tokenize(plain) == []
        assert alt_inspect.groups(plain) == ()
        assert calls == []
    finally:
        alt_inspect._cached_records.cache_clear()


def _isolate_scanners(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        highlight.macro_inspect,
        "tokenize",
        lambda text, *, known_skills: [],
    )
    monkeypatch.setattr(highlight.jinja_inspect, "tokenize", lambda text: [])
    monkeypatch.setattr(highlight.alt_inspect, "tokenize", lambda text: [])
    monkeypatch.setattr(highlight, "placeholder_spans", lambda text: ())
    monkeypatch.setattr(highlight, "scan_artifact_refs", lambda text: ())
    monkeypatch.setattr(highlight, "fenced_block_details", lambda text: [])
    monkeypatch.setattr(highlight, "inline_literal_ranges", lambda text: [])


def test_double_colon_eol_layers_delimiter_and_next_line_value() -> None:
    text = "#foo(a=1)::\nbody"
    parts = _parts(text)
    assert ("::", "macro.arg_delimiter") in parts
    assert ("body", "macro.arg_value") in parts
