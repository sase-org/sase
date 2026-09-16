"""Parity checks for xprompt argument span consumers."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

import pytest
from rich.style import Style
from textual.theme import BUILTIN_THEMES
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.widgets._xprompt_syntax_highlight import (
    XPromptSyntaxHighlightMixin,
    _text_area_style_name,
)
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)
from sase.core.rust import require_rust_binding
from sase.xprompt import highlight
from sase.xprompt.highlight import HighlightSpan
from sase.xprompt.highlight_theme import xprompt_argument_palette

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


def test_text_area_style_name_preserves_argument_source() -> None:
    assert (
        _text_area_style_name(
            HighlightSpan(0, 3, "xprompt.arg_key", source="directive")
        )
        == "xprompt.directive.arg_key"
    )
    assert (
        _text_area_style_name(
            HighlightSpan(
                0,
                3,
                "xprompt.arg_key",
                validity="unknown_key",
                source="directive",
            )
        )
        == "xprompt.directive.arg_key.invalid"
    )
    assert (
        _text_area_style_name(HighlightSpan(0, 3, "xprompt.arg_key", source="xprompt"))
        == "xprompt.arg_key"
    )


def test_text_area_reuses_warm_catalog_wire_for_same_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = XPromptSyntaxHighlightMixin()
    entries = [_entry()]
    calls: list[list[XPromptAssistEntry]] = []

    def fake_to_wire(
        passed_entries: list[XPromptAssistEntry],
    ) -> list[dict[str, object]]:
        calls.append(passed_entries)
        return [{"call": len(calls)}]

    monkeypatch.setattr(
        highlight,
        "xprompt_arg_assist_entries_to_wire",
        fake_to_wire,
    )

    first = widget._xprompt_arg_assist_entries_wire(entries)
    second = widget._xprompt_arg_assist_entries_wire(entries)
    refreshed = widget._xprompt_arg_assist_entries_wire(list(entries))

    assert first is second
    assert first == [{"call": 1}]
    assert refreshed == [{"call": 2}]
    assert calls[0] is entries
    assert calls[1] is not entries
    assert calls[1] == entries


@pytest.mark.parametrize("theme_name", ["textual-dark", "textual-light"])
def test_text_area_registers_source_aware_argument_styles(theme_name: str) -> None:
    app_theme = BUILTIN_THEMES[theme_name]
    widget = _FakeSyntaxWidget(app_theme)

    widget._register_xprompt_text_area_theme()

    assert widget.registered_theme is not None
    styles = widget.registered_theme.syntax_styles
    background = app_theme.background or "#000000"
    xprompt_colors = xprompt_argument_palette(
        app_theme.success,
        foreground=app_theme.foreground,
        background=background,
        secondary=app_theme.secondary,
        accent=app_theme.accent,
        primary=app_theme.primary,
    )
    directive_colors = xprompt_argument_palette(
        app_theme.warning,
        foreground=app_theme.foreground,
        background=background,
        secondary=app_theme.secondary,
        accent=app_theme.accent,
        primary=app_theme.primary,
    )

    assert styles["xprompt.arg_key"] == Style(color=xprompt_colors["xprompt.arg_key"])
    assert styles["xprompt.directive.arg_key"] == Style(
        color=directive_colors["xprompt.arg_key"]
    )
    assert styles["xprompt.directive.arg_key"] != styles["xprompt.arg_key"]
    assert styles["xprompt.directive.arg_key.invalid"] == Style(
        color=directive_colors["xprompt.arg_key"],
        underline=True,
    )
    assert styles["xprompt.directive.arg_value_string"] == Style(
        color=directive_colors["xprompt.arg_value_string"]
    )


class _FakeSyntaxWidget(XPromptSyntaxHighlightMixin):
    def __init__(self, current_theme: object) -> None:
        self.app = SimpleNamespace(current_theme=current_theme)
        self.theme = "css"
        self.registered_theme: TextAreaTheme | None = None
        self.applied_theme: str | None = None

    def _resolve_xprompt_base_theme(self, theme_name: str) -> TextAreaTheme:
        del theme_name
        theme = TextAreaTheme.get_builtin_theme("css")
        assert theme is not None
        return theme

    def register_theme(self, theme: TextAreaTheme) -> None:
        self.registered_theme = theme

    def _set_theme(self, name: str) -> None:
        self.applied_theme = name
