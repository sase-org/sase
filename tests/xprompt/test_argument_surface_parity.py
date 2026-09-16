"""Parity checks for xprompt argument span consumers."""

from __future__ import annotations

from collections.abc import Mapping

from sase.ace.tui.widgets._xprompt_syntax_highlight import _text_area_style_name
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)
from sase.core.rust import require_rust_binding
from sase.xprompt import highlight
from sase.xprompt.highlight import HighlightSpan

_LSP_TOKEN_TYPE_BY_CORE_ROLE = {
    "arg_delimiter": "operator",
    "arg_assign": "operator",
    "arg_key": "parameter",
    "arg_value": "string",
    "arg_value_string": "string",
    "arg_value_number": "number",
    "arg_value_bool": "keyword",
}

_LSP_MODIFIERS_BY_VALIDITY = {
    "unknown_key": frozenset({"deprecated"}),
    "ok": frozenset(),
    "type_mismatch": frozenset(),
    "duplicate_key": frozenset(),
    "unresolvable": frozenset(),
}


def _input(
    name: str,
    type_: str,
    *,
    position: int,
) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=position,
    )


def _entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="visual_batch",
        insertion="#visual_batch",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(
            _input("owner", "agent", position=0),
            _input("title", "string", position=1),
            _input("count", "int", position=2),
            _input("enabled", "bool", position=3),
            _input("context", "string", position=4),
        ),
        content_preview=None,
        description=None,
    )


def test_tui_and_lsp_argument_roles_are_total_mappings_from_core_spans() -> None:
    text = (
        '#visual_batch(owner, title="release", count=42, enabled=true, '
        "context=@file:plans/launch.md+{{ root }}, extra=nope)"
    )
    binding = require_rust_binding("xprompt_argument_spans")
    entries = [highlight._xprompt_arg_assist_entry_to_wire(_entry())]
    core_spans = binding(text, entries)

    assert {span["role"] for span in core_spans} == set(_LSP_TOKEN_TYPE_BY_CORE_ROLE)
    assert {"unknown_key", "unresolvable"} <= {span["validity"] for span in core_spans}

    for raw_span in core_spans:
        assert isinstance(raw_span, Mapping)
        core_role = str(raw_span["role"])
        validity = str(raw_span["validity"])
        tui_role = highlight._ARGUMENT_ROLE_BY_CORE_ROLE[core_role]
        tui_style = _text_area_style_name(
            HighlightSpan(
                int(raw_span["start"]),
                int(raw_span["end"]),
                tui_role,
                validity=highlight._validity_value(validity),
                source=highlight._source_value(raw_span.get("source")),
            )
        )
        lsp_type = _LSP_TOKEN_TYPE_BY_CORE_ROLE[core_role]
        lsp_modifiers = _LSP_MODIFIERS_BY_VALIDITY[validity]

        assert tui_style.startswith("xprompt.arg_")
        assert lsp_type in {"operator", "parameter", "string", "number", "keyword"}
        if validity in {"unknown_key", "type_mismatch", "duplicate_key"}:
            assert tui_style.endswith(".invalid")
        else:
            assert not tui_style.endswith(".invalid")
        if validity == "unknown_key":
            assert lsp_modifiers == frozenset({"deprecated"})
        else:
            assert lsp_modifiers == frozenset()
