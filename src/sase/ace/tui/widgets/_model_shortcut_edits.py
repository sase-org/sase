"""Shared multi-edit plans for ``=alias``/``==model`` shortcut acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui.util.editor_offsets import editor_range_to_offsets


@dataclass(frozen=True, slots=True)
class ModelShortcutExtraEdit:
    """One non-primary edit in a shortcut acceptance.

    Carries the destination replacement (the earliest eligible standalone
    ``%model``/``%m`` directive rewritten with the selected value) or one
    further standalone-directive removal, in original-document offsets.
    """

    replacement_start: int
    replacement_end: int
    replacement: str


@dataclass(frozen=True, slots=True)
class ModelShortcutPlannedEdit:
    """Full validated edit set for accepting one shortcut row.

    ``replacement_start``/``replacement_end``/``replacement`` cover the typed
    shortcut token; ``additional_edits`` carries the destination replacement
    plus any further removals, all in original-document offsets. An empty
    ``additional_edits`` is the token-local expansion: applying the primary
    edit alone reproduces the final document.
    """

    replacement_start: int
    replacement_end: int
    replacement: str
    caret_offset: int
    additional_edits: tuple[ModelShortcutExtraEdit, ...] = ()


def parse_model_shortcut_edit_payload(
    text: str,
    payload: Any,
) -> ModelShortcutPlannedEdit | None:
    """Parse a shared Rust shortcut edit payload into document offsets.

    Returns None when the payload is malformed or the edit set overlaps, so
    callers fail closed: dismiss the menu and change nothing. Payloads
    planned before ``additional_edits`` existed parse as the single-edit
    case, keeping older bindings working.
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return None
    edit = payload.get("edit")
    if not isinstance(edit, dict):
        return None
    replacement = edit.get("new_text")
    if not isinstance(replacement, str):
        return None
    primary = editor_range_to_offsets(
        text,
        edit.get("range"),
        allow_empty=True,
    )
    if primary is None:
        return None
    raw_additional = payload.get("additional_edits", [])
    if not isinstance(raw_additional, list):
        return None
    additional: list[ModelShortcutExtraEdit] = []
    for raw in raw_additional:
        if not isinstance(raw, dict):
            return None
        new_text = raw.get("new_text")
        if not isinstance(new_text, str):
            return None
        span = editor_range_to_offsets(
            text,
            raw.get("range"),
            allow_empty=True,
        )
        if span is None:
            return None
        additional.append(
            ModelShortcutExtraEdit(
                replacement_start=span[0],
                replacement_end=span[1],
                replacement=new_text,
            )
        )
    start, end = primary
    planned_additional = tuple(additional)
    preview = apply_model_shortcut_edit(
        text,
        start,
        end,
        replacement,
        planned_additional,
    )
    if preview is None:
        return None
    caret = editor_range_to_offsets(
        preview,
        {"start": payload.get("caret"), "end": payload.get("caret")},
        allow_empty=True,
    )
    if caret is None:
        return None
    return ModelShortcutPlannedEdit(
        replacement_start=start,
        replacement_end=end,
        replacement=replacement,
        caret_offset=caret[0],
        additional_edits=planned_additional,
    )


def apply_model_shortcut_edit(
    text: str,
    start: int,
    end: int,
    replacement: str,
    additional_edits: tuple[ModelShortcutExtraEdit, ...],
) -> str | None:
    """Apply the full edit set to *text*; None when spans are invalid.

    Every span is in original-document offsets. Overlapping spans fail
    closed so a corrupt plan never produces a half-applied document.
    """
    spans = [(start, end, replacement)] + [
        (edit.replacement_start, edit.replacement_end, edit.replacement)
        for edit in additional_edits
    ]
    for span_start, span_end, _ in spans:
        if not 0 <= span_start <= span_end <= len(text):
            return None
    ordered = sorted(spans, key=lambda span: (span[0], span[1]))
    pieces: list[str] = []
    pos = 0
    for span_start, span_end, new_text in ordered:
        if span_start < pos:
            return None
        pieces.append(text[pos:span_start])
        pieces.append(new_text)
        pos = span_end
    pieces.append(text[pos:])
    return "".join(pieces)


__all__ = [
    "ModelShortcutExtraEdit",
    "ModelShortcutPlannedEdit",
    "apply_model_shortcut_edit",
    "parse_model_shortcut_edit_payload",
]
