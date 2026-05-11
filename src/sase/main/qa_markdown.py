"""Shared markdown formatter for question/answer rendering.

Used by both the user-question TUI modal (live preview) and the
follow-up agent prompt section, so the two cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _normalize_selected(selected: Any) -> list[str]:
    if isinstance(selected, list):
        return [str(s) for s in selected]
    if isinstance(selected, str) and selected:
        return [selected]
    return []


@dataclass
class QARound:
    """One round of Q&A — the inputs that produced one rendered section.

    A single agent run can accumulate multiple rounds when the agent
    enters the question flow more than once (or when a feedback round
    follows). The merged renderer (:func:`build_merged_qa_markdown`)
    flattens these into a single ``### Questions and Answers`` block.
    """

    questions: list[dict[str, Any]] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)
    global_note: str | None = None


def _render_question(
    lines: list[str],
    q: dict[str, Any],
    answer: dict[str, Any] | None,
    number: int,
) -> None:
    header = q.get("header", "")
    if header:
        lines.append(f"#### Q{number}: {header}")
    else:
        lines.append(f"#### Q{number}")

    question_text = q.get("question", "")
    if question_text:
        lines.append("")
        for qline in question_text.splitlines():
            lines.append(f"> {qline}" if qline else ">")

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


def build_merged_qa_markdown(rounds: list[QARound]) -> str:
    """Render one or more Q&A rounds as a single markdown section.

    Emits exactly one ``### Questions and Answers`` header. Questions
    from every round are flattened into a single monotonically
    increasing numbering (``#### Q1``, ``#### Q2``, …) — round
    boundaries are not visible in the output.

    Global notes: only the most recent non-empty ``global_note`` across
    all rounds is rendered ("last non-empty wins"). This treats the
    global note as a single steering message the user refines over time,
    not a per-round diary.
    """

    lines: list[str] = ["### Questions and Answers", ""]

    counter = 0
    for r in rounds:
        for idx, q in enumerate(r.questions):
            counter += 1
            answer = r.answers[idx] if idx < len(r.answers) else None
            _render_question(lines, q, answer, counter)

    last_note: str | None = None
    for r in rounds:
        if r.global_note:
            last_note = r.global_note

    if last_note:
        lines.append("---")
        lines.append("")
        lines.append(f"> **Global Note:** {last_note}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_qa_markdown(
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    global_note: str | None,
) -> str:
    """Render questions + answers as a markdown Q&A section.

    Thin single-round wrapper around :func:`build_merged_qa_markdown`
    kept for callers (notably the TUI modal preview) that operate on a
    single in-flight ballot.

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

    return build_merged_qa_markdown(
        [QARound(questions=questions, answers=answers, global_note=global_note)]
    )
