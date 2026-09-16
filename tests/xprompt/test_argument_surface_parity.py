"""Parity checks for xprompt argument span consumers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.style import Style
from textual.theme import BUILTIN_THEMES
from textual.widgets._text_area import TextAreaTheme

from tests._xprompt_directive_completion_parity_lsp import (
    LspSemanticToken,
    LspSession,
)
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


def test_tui_and_real_lsp_argument_roles_match_core_spans(
    tmp_path: Path,
) -> None:
    text = (
        '#visual_batch(owner=alice, title="release", count=42, enabled=true, '
        "context={{ root }}) "
        '#visual_batch(owner=bob, title="x", count=oops, enabled=false, '
        "context=plain, owner=again, extra=nope)"
    )
    binding = require_rust_binding("xprompt_argument_spans")
    entry_wire = highlight._xprompt_arg_assist_entry_to_wire(_entry())
    entries = [entry_wire]
    core_spans = binding(text, entries)

    assert {span["role"] for span in core_spans} == set(_LSP_TOKEN_TYPE_BY_CORE_ROLE)
    assert {
        "unknown_key",
        "type_mismatch",
        "duplicate_key",
        "unresolvable",
    } <= {span["validity"] for span in core_spans}

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

    with LspSession(tmp_path, xprompt_catalog=entries) as session:
        session.complete("#vis")
        diagnostics = session.published_diagnostics(
            text,
            expected_codes=frozenset(
                {
                    "duplicate_xprompt_arg",
                    "invalid_xprompt_arg_type",
                    "unknown_xprompt_arg",
                }
            ),
        )
        tokens = session.semantic_tokens(text)

    expected_tokens = {
        *_expected_name_tokens(text, "visual_batch", "function"),
        *_expected_lsp_tokens_from_core_spans(text, core_spans),
    }
    actual_tokens = {_semantic_token_tuple(token) for token in tokens}

    assert expected_tokens == actual_tokens
    assert {_diagnostic_code(diagnostic) for diagnostic in diagnostics} >= {
        "duplicate_xprompt_arg",
        "invalid_xprompt_arg_type",
        "unknown_xprompt_arg",
    }
    _assert_no_lsp_token_overlaps(tokens)


def test_real_lsp_keeps_open_calls_structural_without_validity(
    tmp_path: Path,
) -> None:
    text = "#visual_batch(owner=alice, count="
    entry_wire = highlight._xprompt_arg_assist_entry_to_wire(_entry())
    binding = require_rust_binding("xprompt_argument_spans")
    core_spans = binding(text, [entry_wire])

    assert core_spans
    assert {span["validity"] for span in core_spans} == {"ok"}

    with LspSession(tmp_path, xprompt_catalog=[entry_wire]) as session:
        session.complete("#vis")
        tokens = session.semantic_tokens(text)

    actual_tokens = {_semantic_token_tuple(token) for token in tokens}
    assert _expected_name_tokens(text, "visual_batch", "function") <= actual_tokens
    assert _expected_lsp_tokens_from_core_spans(text, core_spans) <= actual_tokens


def test_real_lsp_covers_directive_names_arguments_and_utf16_multiline(
    tmp_path: Path,
) -> None:
    directive_text = "%queue(capacity=2, priority=3)\n%if(should_run=false)"
    binding = require_rust_binding("xprompt_argument_spans")
    directive_spans = binding(directive_text)

    with LspSession(tmp_path) as session:
        directive_tokens = session.semantic_tokens(directive_text)
        multiline_tokens = session.semantic_tokens(
            "🙂 #visual_batch(context=[[alpha\r\nbeta 🙂\r\ngamma]])"
        )

    actual_directive = {_semantic_token_tuple(token) for token in directive_tokens}
    assert _expected_name_tokens(directive_text, "queue", "macro") <= actual_directive
    assert _expected_name_tokens(directive_text, "if", "macro") <= actual_directive
    assert (
        _expected_lsp_tokens_from_core_spans(directive_text, directive_spans)
        <= actual_directive
    )
    assert any(
        token.token_type == "number" and _token_text(directive_text, token) == "2"
        for token in directive_tokens
    )
    assert any(
        token.token_type == "keyword" and _token_text(directive_text, token) == "false"
        for token in directive_tokens
    )

    assert _token_for_text(
        "🙂 #visual_batch(context=[[alpha\r\nbeta 🙂\r\ngamma]])",
        "visual_batch",
        "function",
    ) in {_semantic_token_tuple(token) for token in multiline_tokens}
    assert _token_for_text(
        "🙂 #visual_batch(context=[[alpha\r\nbeta 🙂\r\ngamma]])",
        "[[alpha",
        "string",
    ) in {_semantic_token_tuple(token) for token in multiline_tokens}
    assert _token_for_text(
        "🙂 #visual_batch(context=[[alpha\r\nbeta 🙂\r\ngamma]])",
        "beta 🙂",
        "string",
    ) in {_semantic_token_tuple(token) for token in multiline_tokens}
    assert _token_for_text(
        "🙂 #visual_batch(context=[[alpha\r\nbeta 🙂\r\ngamma]])",
        "gamma]]",
        "string",
    ) in {_semantic_token_tuple(token) for token in multiline_tokens}


def test_real_lsp_preserves_artifact_tokens_inside_argument_values(
    tmp_path: Path,
) -> None:
    text = "#visual_batch(context=pre @file:plans/launch.md post)"
    entry_wire = highlight._xprompt_arg_assist_entry_to_wire(_entry())

    with LspSession(
        tmp_path,
        xprompt_catalog=[entry_wire],
        artifact_ref_catalog=_artifact_ref_catalog(tmp_path),
    ) as session:
        session.complete("#vis")
        tokens = session.semantic_tokens(text)

    actual_tokens = {_semantic_token_tuple(token) for token in tokens}
    assert _token_for_text(text, "file", "namespace") in actual_tokens
    assert _token_for_text(text, "plans/launch.md", "string") in actual_tokens
    assert _token_for_text(text, "pre @", "string") in actual_tokens
    assert _token_for_text(text, " post", "string") in actual_tokens
    _assert_no_lsp_token_overlaps(tokens)


def _expected_lsp_tokens_from_core_spans(
    text: str,
    core_spans: object,
) -> set[tuple[int, int, int, str, frozenset[str]]]:
    expected: set[tuple[int, int, int, str, frozenset[str]]] = set()
    assert isinstance(core_spans, list)
    for raw_span in core_spans:
        assert isinstance(raw_span, Mapping)
        role = str(raw_span["role"])
        start = int(raw_span["start"])
        end = int(raw_span["end"])
        start_line, start_column = _byte_lsp_position(text, start)
        end_line, end_column = _byte_lsp_position(text, end)
        assert start_line == end_line, raw_span
        expected.add(
            (
                start_line,
                start_column,
                end_column - start_column,
                _LSP_TOKEN_TYPE_BY_CORE_ROLE[role],
                _LSP_MODIFIERS_BY_VALIDITY[str(raw_span["validity"])],
            )
        )
    return expected


def _expected_name_tokens(
    text: str,
    name: str,
    token_type: str,
) -> set[tuple[int, int, int, str, frozenset[str]]]:
    expected: set[tuple[int, int, int, str, frozenset[str]]] = set()
    offset = 0
    while True:
        start = text.find(name, offset)
        if start < 0:
            return expected
        offset = start + len(name)
        if start == 0 or text[start - 1] not in {"#", "%"}:
            continue
        expected.add(_token_for_text(text, name, token_type, start=start))


def _token_for_text(
    text: str,
    target: str,
    token_type: str,
    *,
    start: int | None = None,
) -> tuple[int, int, int, str, frozenset[str]]:
    char_start = text.index(target) if start is None else start
    char_end = char_start + len(target)
    start_line, start_column = _char_lsp_position(text, char_start)
    end_line, end_column = _char_lsp_position(text, char_end)
    assert start_line == end_line
    return (
        start_line,
        start_column,
        end_column - start_column,
        token_type,
        frozenset(),
    )


def _semantic_token_tuple(
    token: LspSemanticToken,
) -> tuple[int, int, int, str, frozenset[str]]:
    return (token.line, token.start, token.length, token.token_type, token.modifiers)


def _byte_lsp_position(text: str, byte_offset: int) -> tuple[int, int]:
    prefix = text.encode("utf-8")[:byte_offset].decode("utf-8")
    return _char_lsp_position(prefix, len(prefix))


def _char_lsp_position(text: str, char_offset: int) -> tuple[int, int]:
    prefix = text[:char_offset]
    line_text = prefix.rsplit("\n", 1)[-1]
    return (prefix.count("\n"), _utf16_len(line_text))


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _token_text(text: str, token: LspSemanticToken) -> str:
    line = text.split("\n")[token.line]
    start = _utf16_column_to_char_offset(line, token.start)
    end = _utf16_column_to_char_offset(line, token.start + token.length)
    return line[start:end]


def _utf16_column_to_char_offset(text: str, column: int) -> int:
    seen = 0
    for index, character in enumerate(text):
        next_seen = seen + _utf16_len(character)
        if next_seen > column:
            return index
        if next_seen == column:
            return index + 1
        seen = next_seen
    return len(text)


def _assert_no_lsp_token_overlaps(tokens: list[LspSemanticToken]) -> None:
    by_line: dict[int, list[LspSemanticToken]] = {}
    for token in tokens:
        by_line.setdefault(token.line, []).append(token)
    for line_tokens in by_line.values():
        ordered = sorted(line_tokens, key=lambda token: token.start)
        for left, right in zip(ordered, ordered[1:], strict=False):
            assert left.start + left.length <= right.start, ordered


def _diagnostic_code(diagnostic: Mapping[str, object]) -> str | None:
    code = diagnostic.get("code")
    if isinstance(code, Mapping):
        value = code.get("value")
        return str(value) if value is not None else None
    return str(code) if code is not None else None


def _artifact_ref_catalog(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "artifact-project"
    return {
        "schema_version": 1,
        "default_project": "sase",
        "projects": [
            {
                "name": "sase",
                "key": "sase",
                "aliases": [],
                "context": {
                    "schema_version": 1,
                    "document_roots": [],
                    "chats_root": str(root / "chats"),
                    "artifact_index_path": str(root / "artifact-index.jsonl"),
                    "repositories": [],
                    "projects": [],
                },
            }
        ],
    }


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
