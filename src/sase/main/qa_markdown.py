"""Shared markdown formatter for question/answer rendering.

Used by both the user-question TUI modal (live preview) and the
follow-up agent prompt section, so the two cannot drift apart.
"""

from __future__ import annotations

from typing import Any


def _normalize_selected(selected: Any) -> list[str]:
    if isinstance(selected, list):
        return [str(s) for s in selected]
    if isinstance(selected, str) and selected:
        return [selected]
    return []


def build_qa_markdown(
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    global_note: str | None,
) -> str:
    """Render questions + answers as a markdown Q&A section.

    Args:
        questions: Original question dicts (with ``options``, ``header``,
            ``multiSelect``, ``question``).
        answers: Per-question answer dicts. Each entry should contain
            ``selected`` (``list[str]`` of option labels — bare ``str``
            also accepted for back-compat) and optional
            ``custom_feedback`` for the "Other" line. Index-aligned with
            ``questions``; missing entries render as un-checked.
        global_note: Optional global note appended at the end.
    """

    lines: list[str] = ["### Questions and Answers", ""]

    for idx, q in enumerate(questions):
        header = q.get("header", "")
        if header:
            lines.append(f"#### Q{idx + 1}: {header}")
        else:
            lines.append(f"#### Q{idx + 1}")

        question_text = q.get("question", "")
        if question_text:
            lines.append("")
            for qline in question_text.splitlines():
                lines.append(f"> {qline}" if qline else ">")

        answer = answers[idx] if idx < len(answers) else None
        selected_labels = _normalize_selected(answer.get("selected") if answer else [])
        selected_set = set(selected_labels)
        custom_feedback = (
            (answer.get("custom_feedback") if answer else None) or ""
        ).strip()

        options = q.get("options", [])
        known_labels = {opt.get("label", "") for opt in options}

        if options:
            lines.append("")
            for opt in options:
                label = opt.get("label", "")
                desc = opt.get("description", "")
                checked = "x" if label in selected_set else " "
                display = f"**{label}** — {desc}" if desc else f"**{label}**"
                lines.append(f"- [{checked}] {display}")

            has_other = "Other" in selected_set
            if has_other and custom_feedback:
                lines.append(f'- [x] **Other:** "{custom_feedback}"')
            elif has_other:
                lines.append("- [x] **Other**")

            # Surface labels referenced by the answer that aren't in the
            # current question's options (e.g. options changed after the
            # answer was recorded) so no data is silently lost.
            for label in selected_labels:
                if label == "Other":
                    continue
                if label not in known_labels:
                    lines.append(f"- [x] **{label}**")

        if q.get("multiSelect"):
            lines.append("")
            lines.append("*Multi-select*")

        lines.append("")

    if global_note:
        lines.append("---")
        lines.append("")
        lines.append(f"> **Global Note:** {global_note}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
