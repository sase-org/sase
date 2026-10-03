"""LSP wire helpers and text-edit application for parity tests.

Public names in this already-private module are the sharing surface for the
other ``_macro_directive_completion_parity_lsp_*`` modules. New modules must
import only these public names, never ``_``-prefixed names.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tests._macro_directive_completion_parity_lsp_rows import (
    LspSemanticToken,
    LspSurfaceRow,
)


def _model_catalog_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "value": "claude-fable-5",
                "display": "claude-fable-5",
                "description": "Claude (fable)",
                "kind": "model",
                "provider": "claude",
                "aliases": ["fable"],
            },
            {
                "value": "@medium",
                "display": "@medium",
                "description": "Medium phase worker model.",
                "kind": "implicit_alias",
                "aliases": ["medium"],
                "alias_kind": "role",
                "target_provider": "claude",
                "target_model": "claude-fable-5",
                "target_effort": "high",
                "provenance": "configured",
            },
        ],
    }


model_catalog_payload = _model_catalog_payload


def _macro_catalog_payload(
    catalog: dict[str, Any] | Sequence[Mapping[str, object]] | None,
) -> dict[str, Any]:
    if isinstance(catalog, dict) and "schema_version" in catalog:
        return catalog
    entries = [] if catalog is None else [dict(entry) for entry in catalog]
    return {
        "schema_version": 1,
        "result": {
            "status": "success",
            "message": "",
            "warnings": [],
            "skipped": [],
            "partial_failure_count": None,
        },
        "context": {"project": None, "scope": "unspecified"},
        "entries": entries,
        "stats": {
            "total_count": len(entries),
            "project_count": 0,
            "skill_count": 0,
            "memory_count": 0,
            "pdf_requested": False,
        },
        "catalog_attachment": None,
    }


macro_catalog_payload = _macro_catalog_payload


def _machine_catalog_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "alias": "apollo",
                "display": "apollo",
                "provider_ref": "builtin@https",
                "installation_id": "sase_inst_v1_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "endpoint": "https://fleet.example.test",
                "status": "ok",
                "documentation": "Remote workstation",
            }
        ],
    }


machine_catalog_payload = _machine_catalog_payload


def _lsp_surface_row(item: dict[str, Any]) -> LspSurfaceRow:
    documentation = item.get("documentation")
    if isinstance(documentation, dict):
        doc_text = str(documentation.get("value") or "")
    else:
        doc_text = str(documentation or "")
    text_edit = item.get("textEdit")
    insertion = ""
    if isinstance(text_edit, dict):
        insertion = str(text_edit.get("newText") or "")
    return LspSurfaceRow(
        label=str(item.get("label") or ""),
        insertion=insertion,
        documentation=doc_text,
        detail=_lsp_row_detail(item),
        raw=item,
    )


lsp_surface_row = _lsp_surface_row


def _lsp_row_detail(item: dict[str, Any]) -> str:
    label_details = item.get("labelDetails")
    description = ""
    policy = ""
    if isinstance(label_details, dict):
        description = str(label_details.get("description") or "")
        policy = str(label_details.get("detail") or "")
    if policy.startswith(" · ") and description:
        status = policy.strip(" ·")
        parts = [part for part in description.split(" · ") if part]
        if status and status not in parts:
            parts.append(status)
        return " · ".join(parts)
    return str(item.get("detail") or description or "")


def _decode_semantic_tokens(
    data: list[int],
    *,
    token_types: Sequence[str],
    token_modifiers: Sequence[str],
) -> list[LspSemanticToken]:
    tokens: list[LspSemanticToken] = []
    line = 0
    start = 0
    for index in range(0, len(data), 5):
        delta_line = data[index]
        delta_start = data[index + 1]
        length = data[index + 2]
        token_type_index = data[index + 3]
        modifiers = data[index + 4]
        line += delta_line
        start = start + delta_start if delta_line == 0 else delta_start
        tokens.append(
            LspSemanticToken(
                line=line,
                start=start,
                length=length,
                token_type=token_types[token_type_index]
                if 0 <= token_type_index < len(token_types)
                else str(token_type_index),
                modifiers=frozenset(
                    modifier
                    for bit, modifier in enumerate(token_modifiers)
                    if modifiers & (1 << bit)
                ),
            )
        )
    return tokens


decode_semantic_tokens = _decode_semantic_tokens


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _completion_position(
    text: str,
    *,
    character: int | None = None,
    cursor: tuple[int, int] | None = None,
) -> dict[str, int]:
    """Return an LSP UTF-16 position for *text*.

    ``character`` keeps the historical line-0 prefix contract used by existing
    directive-parity tests. ``cursor`` is an ACE-style ``(row, column)`` pair
    counted in Python characters on that line.
    """
    if cursor is not None:
        row, column = cursor
        lines = text.split("\n")
        line = lines[row] if 0 <= row < len(lines) else ""
        column = max(0, min(column, len(line)))
        return {"line": row, "character": _utf16_len(line[:column])}
    return {
        "line": 0,
        "character": _utf16_len(text if character is None else text[:character]),
    }


completion_position = _completion_position


def apply_lsp_text_edit(text: str, text_edit: Mapping[str, Any]) -> tuple[str, int]:
    """Apply one LSP ``textEdit`` and return ``(new_text, caret_python_offset)``."""
    from sase.ace.tui.util.editor_offsets import editor_range_to_offsets

    offsets = editor_range_to_offsets(
        text,
        text_edit.get("range"),
        allow_empty=True,
    )
    assert offsets is not None
    start, end = offsets
    replacement = str(text_edit.get("newText") or "")
    return f"{text[:start]}{replacement}{text[end:]}", start + len(replacement)


def apply_lsp_completion_item_edits(
    text: str,
    item_raw: Mapping[str, Any],
) -> tuple[str, int]:
    """Apply an LSP item's ``textEdit`` plus ``additionalTextEdits``.

    Returns ``(new_text, caret_python_offset)``. The caret is the end of
    the primary application for the token-local case, and the end of the
    first non-empty additional edit (the destination replacement) for a
    segment replacement — mirroring the shared Rust caret contract.
    """
    from sase.ace.tui.util.editor_offsets import editor_range_to_offsets

    text_edit = item_raw.get("textEdit")
    assert isinstance(text_edit, dict)
    spans: list[tuple[int, int, str, bool]] = []

    def _span(raw: Any, *, primary: bool) -> tuple[int, int, str, bool]:
        assert isinstance(raw, dict)
        offsets = editor_range_to_offsets(
            text,
            raw.get("range"),
            allow_empty=True,
        )
        assert offsets is not None
        start, end = offsets
        return start, end, str(raw.get("newText") or ""), primary

    spans.append(_span(text_edit, primary=True))
    additional = item_raw.get("additionalTextEdits", [])
    assert isinstance(additional, list)
    for raw in additional:
        spans.append(_span(raw, primary=False))
    for first in range(len(spans)):
        for second in range(first + 1, len(spans)):
            assert not (
                spans[first][0] < spans[second][1]
                and spans[second][0] < spans[first][1]
            ), "LSP edits must be nonoverlapping"
    ordered = sorted(spans, key=lambda span: (span[0], span[1]))
    pieces: list[str] = []
    pos = 0
    caret = 0
    primary_end = 0
    destination_seen = False
    for span_start, span_end, new_text, primary in ordered:
        assert span_start >= pos
        pieces.append(text[pos:span_start])
        edit_end = sum(len(piece) for piece in pieces) + len(new_text)
        if primary:
            primary_end = edit_end
        if new_text and not destination_seen:
            # The destination replacement carries the caret: the first
            # non-empty edit in application order, whether it rides as the
            # primary (merged coincident range) or as an additional edit.
            caret = edit_end
            destination_seen = True
        pieces.append(new_text)
        pos = span_end
    pieces.append(text[pos:])
    new_text_full = "".join(pieces)
    if not destination_seen:
        caret = primary_end
    return new_text_full, caret
