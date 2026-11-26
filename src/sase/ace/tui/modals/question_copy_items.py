"""Pure presentation helpers for the question copy panel.

``user_question_modal.py`` is close to the ``toobig`` limit, so all row
construction, key allocation, and truncation lives here where it can be
unit-tested without a TUI.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.question_copy_facade import QuestionCopyItem

from .copy_as_types import CopyAsContext, CopyAsRow, CopyAsSection

SNIPPET_KEY_POOL: tuple[str, ...] = tuple("1234567890") + tuple("bcdefghilmnprsuvwxz")
RESERVED_PANEL_KEYS: frozenset[str] = frozenset({"a", "j", "k", "o", "q", "t", "y"})

SNIPPETS_SECTION_ID = "snippets"
QUESTION_SECTION_ID = "question"

_ROW_PREVIEW_MAX_CHARS = 48
_TOAST_VALUE_MAX_CHARS = 48

assert not (set(SNIPPET_KEY_POOL) & RESERVED_PANEL_KEYS), (
    "snippet key pool must never include reserved panel keys"
)
assert len(SNIPPET_KEY_POOL) == 29


def _allocate_snippet_keys(count: int) -> tuple[str, ...]:
    """Return the first ``count`` stable snippet keys from the pool."""
    if count < 0:
        raise ValueError("count must be non-negative")
    return SNIPPET_KEY_POOL[:count]


def _first_line_summary(value: str) -> tuple[str, int]:
    """Return the first non-empty line and the count of remaining lines."""
    lines = value.split("\n")
    first = ""
    first_idx = 0
    for idx, line in enumerate(lines):
        if line.strip():
            first = line
            first_idx = idx
            break
    else:
        first = lines[0] if lines else ""
        first_idx = 0
    remaining = len(lines) - first_idx - 1
    return first, max(0, remaining)


def _truncate_preview_text(text: str, max_chars: int = _ROW_PREVIEW_MAX_CHARS) -> str:
    """Truncate one line for a palette row preview.

    Path-like values (starting with ``/`` or ``~/``) are middle-truncated so
    the root and the distinctive trailing segments survive. Everything else
    is end-truncated with an ellipsis.
    """
    if len(text) <= max_chars:
        return text
    if text.startswith("/") or text.startswith("~/"):
        parts = text.split("/")
        root = (
            parts[0] if parts[0] != "" else "/" + (parts[1] if len(parts) > 1 else "")
        )
        trailing = parts[2:] if parts[0] == "" else parts[1:]
        if not trailing:
            return text[: max_chars - 1] + "…"
        kept: list[str] = []
        for segment in reversed(trailing):
            candidate = kept + [segment]
            trial = root + "/…" + "".join("/" + s for s in reversed(candidate))
            if len(trial) <= max_chars:
                kept = candidate
            else:
                break
        if kept:
            return root + "/…" + "".join("/" + s for s in reversed(kept))
    return text[: max_chars - 1] + "…"


def _row_preview_for_value(value: str) -> tuple[str, str | None]:
    """Return ``(preview, badge)`` for one exact copy value."""
    first, remaining = _first_line_summary(value)
    preview = _truncate_preview_text(first)
    badge = f"+{remaining} lines" if remaining else None
    return preview, badge


def _snippet_toast_label(item: QuestionCopyItem) -> str:
    """Return the clipboard toast label for one snippet."""
    if item.label:
        return item.label
    first, _ = _first_line_summary(item.text)
    return _truncate_preview_text(first, _TOAST_VALUE_MAX_CHARS)


@dataclass(frozen=True)
class QuestionCopySnapshot:
    """Everything the copy panel needs, captured before it opens."""

    question_index: int
    total_questions: int
    header: str
    question_text: str
    highlighted_label: str | None
    highlighted_description: str | None
    highlighted_is_other: bool
    has_options: bool
    items: tuple[QuestionCopyItem, ...]
    unavailable: int
    copied_texts: frozenset[str]
    qa_value: str


def _subtitle(snapshot: QuestionCopySnapshot) -> str:
    position = f"Q{snapshot.question_index + 1}/{snapshot.total_questions}"
    total = len(snapshot.items)
    if total == 0:
        tail = "no snippets"
    else:
        copied = sum(1 for item in snapshot.items if item.text in snapshot.copied_texts)
        tail = f"{copied} of {total} snippets copied"
    if snapshot.header:
        return f"{position} · {snapshot.header} · {tail}"
    return f"{position} · {tail}"


def _footer(snippet_keys: tuple[str, ...], snippet_count: int) -> str:
    parts: list[str] = []
    if snippet_count == 1:
        parts.append("1 copy")
    elif snippet_count:
        parts.append(f"1–{snippet_keys[-1]} copy")
    if snippet_count >= 2:
        parts.append("a all")
    parts.extend(["⏎ highlighted", "j/k move", "esc close"])
    return " · ".join(parts)


def _unknown_key_message(snippet_keys: tuple[str, ...], snippet_count: int) -> str:
    keys = list(snippet_keys)
    if snippet_count >= 2:
        keys.append("a")
    keys.extend(["t", "o", "y"])
    return f"Unknown copy key — use {', '.join(keys)}"


def build_question_copy_context(snapshot: QuestionCopySnapshot) -> CopyAsContext:
    """Build the sectioned palette context for one question snapshot."""
    items = snapshot.items
    snippet_keys = _allocate_snippet_keys(len(items))
    total = len(items)
    copied = snapshot.copied_texts

    rows: list[CopyAsRow] = []
    for key, item in zip(snippet_keys, items, strict=True):
        preview, badge = _row_preview_for_value(item.text)
        rows.append(
            CopyAsRow(
                key=key,
                key_display=key,
                target=f"snippet:{item.text}",
                label=item.label or "",
                section=SNIPPETS_SECTION_ID,
                marker="✓" if item.text in copied else None,
                badge=badge,
                value=item.text,
                preview=preview,
            )
        )

    if snapshot.unavailable > 0:
        n = snapshot.unavailable
        noun = "snippet" if n == 1 else "snippets"
        rows.append(
            CopyAsRow(
                key="unavailable",
                key_display=" ",
                target="unavailable",
                label=f"{n} {noun} unavailable",
                section=SNIPPETS_SECTION_ID,
                preview="malformed copy metadata",
                disabled_reason=f"{n} {noun} unavailable — malformed copy metadata",
            )
        )

    all_copied = bool(items) and all(item.text in copied for item in items)
    if total >= 2:
        joined = "\n".join(item.text for item in items)
        rows.append(
            CopyAsRow(
                key="a",
                key_display="a",
                target="all",
                label=f"All {total} snippets",
                section=SNIPPETS_SECTION_ID,
                marker="✓" if all_copied else None,
                value=joined,
                preview=f"one per line · {total} lines",
            )
        )

    question_first, _ = _first_line_summary(snapshot.question_text)
    rows.append(
        CopyAsRow(
            key="t",
            key_display="t",
            target="question",
            label="Question text",
            section=QUESTION_SECTION_ID,
            value=snapshot.question_text,
            preview=_truncate_preview_text(question_first),
        )
    )

    if not snapshot.has_options:
        rows.append(
            CopyAsRow(
                key="o",
                key_display="o",
                target="option",
                label="Highlighted option",
                section=QUESTION_SECTION_ID,
                preview="no options",
                disabled_reason="No options to copy",
            )
        )
    elif snapshot.highlighted_is_other or snapshot.highlighted_label is None:
        rows.append(
            CopyAsRow(
                key="o",
                key_display="o",
                target="option",
                label="Highlighted option",
                section=QUESTION_SECTION_ID,
                preview="Other…",
                disabled_reason="Other answer is typed, not copyable",
            )
        )
    else:
        label = snapshot.highlighted_label
        desc = snapshot.highlighted_description or ""
        display = f"{label} — {desc}" if desc else label
        rows.append(
            CopyAsRow(
                key="o",
                key_display="o",
                target=f"option:{label}",
                label="Highlighted option",
                section=QUESTION_SECTION_ID,
                value=display,
                preview=_truncate_preview_text(display),
            )
        )

    qa_preview = f"Markdown · {snapshot.total_questions} question"
    if snapshot.total_questions != 1:
        qa_preview += "s"
    qa_preview += " · current picks"
    rows.append(
        CopyAsRow(
            key="y",
            key_display="y",
            target="qa",
            label="Questions & answers",
            section=QUESTION_SECTION_ID,
            value=snapshot.qa_value,
            preview=qa_preview,
        )
    )

    label_width = max((len(row.label) for row in rows), default=0)

    if total == 0:
        initial: str | None = "y"
    else:
        initial = None
        for key, item in zip(snippet_keys, items, strict=True):
            if item.text not in copied:
                initial = key
                break
        if initial is None:
            initial = "y"

    return CopyAsContext(
        group="question",
        subtitle=_subtitle(snapshot),
        unknown_context="question",
        rows=tuple(rows),
        title="Copy from question",
        sections=(
            CopyAsSection(id=SNIPPETS_SECTION_ID, title="SNIPPETS", dim=True),
            CopyAsSection(id=QUESTION_SECTION_ID, title="QUESTION", dim=True),
        ),
        footer=_footer(snippet_keys, total),
        unknown_key_message=_unknown_key_message(snippet_keys, total),
        initial_row_key=initial,
        key_width=3,
        label_width=label_width or None,
        preview_pane=True,
        show_marker_gutter=True,
    )


def toast_label_for_target(
    target: str,
    snapshot: QuestionCopySnapshot,
    row: CopyAsRow | None = None,
) -> str:
    """Return the clipboard toast label for a dismissed copy row."""
    if target.startswith("snippet:"):
        text = target[len("snippet:") :]
        for item in snapshot.items:
            if item.text == text:
                return _snippet_toast_label(item)
        if row is not None:
            return row.label or row.preview
        return "snippet"
    if target == "all":
        return f"{len(snapshot.items)} snippets"
    if target == "question":
        return "question text"
    if target.startswith("option:"):
        return f'option "{target[len("option:") :]}"'
    if target == "option":
        return "highlighted option"
    if target == "qa":
        return "questions & answers"
    if row is not None:
        return row.label or row.preview or target
    return target


__all__ = [
    "QUESTION_SECTION_ID",
    "RESERVED_PANEL_KEYS",
    "SNIPPETS_SECTION_ID",
    "SNIPPET_KEY_POOL",
    "QuestionCopySnapshot",
    "build_question_copy_context",
    "toast_label_for_target",
]
