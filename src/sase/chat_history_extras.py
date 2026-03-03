"""Format extra sections (plan feedback, Q&A) for chat history files.

Reads JSONL files from SASE_ARTIFACTS_DIR and produces markdown sections
that go between the timestamp and the ## Prompt heading.
"""

import json
import os
from pathlib import Path


def format_extra_sections(artifacts_dir: str) -> str | None:
    """Read JSONL files from artifacts_dir and return formatted markdown.

    Returns None if no extra data is found.
    """
    parts: list[str] = []

    plan_link = _format_plan_link(artifacts_dir)
    if plan_link:
        parts.append(plan_link)

    feedback_md = _format_plan_feedback(artifacts_dir)
    if feedback_md:
        parts.append(feedback_md)

    qa_md = _format_qa_log(artifacts_dir)
    if qa_md:
        parts.append(qa_md)

    if not parts:
        return None
    return "\n".join(parts)


def _format_plan_link(artifacts_dir: str) -> str | None:
    """Format a plan file link from plan_path.json."""
    plan_path_file = os.path.join(artifacts_dir, "plan_path.json")
    if not Path(plan_path_file).exists():
        return None
    try:
        with open(plan_path_file, encoding="utf-8") as f:
            data = json.load(f)
        plan_path = data.get("plan_path")
        if plan_path:
            return f"**Plan:** {plan_path}\n"
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _format_plan_feedback(artifacts_dir: str) -> str | None:
    """Format plan_feedback.jsonl as a ## Plan Feedback section."""
    records = _read_jsonl(os.path.join(artifacts_dir, "plan_feedback.jsonl"))
    if not records:
        return None

    lines = ["## Plan Feedback", ""]
    for record in records:
        round_num = record.get("round", 0)
        feedback = record.get("feedback", "")
        lines.append(f"### Round {round_num + 1}")
        lines.append(f"> {feedback}")
        lines.append("")

    return "\n".join(lines)


def _format_qa_log(artifacts_dir: str) -> str | None:
    """Format qa_log.jsonl as a ## Questions & Answers section."""
    records = _read_jsonl(os.path.join(artifacts_dir, "qa_log.jsonl"))
    if not records:
        return None

    lines = ["## Questions & Answers", ""]
    q_num = 0
    for record in records:
        for answer in record.get("answers", []):
            q_num += 1
            question = answer.get("question", "")
            selected = answer.get("selected", [])
            custom_feedback = answer.get("custom_feedback", "")

            lines.append(f"### Q{q_num}: {question}")
            if selected:
                lines.append(f"**Selected:** {', '.join(selected)}")
            if custom_feedback:
                lines.append(f"**Custom feedback:** {custom_feedback}")
            lines.append("")

        global_note = record.get("global_note", "")
        if global_note:
            lines.append(f"**Global note:** {global_note}")
            lines.append("")

    return "\n".join(lines)


def _read_jsonl(path: str) -> list[dict]:
    """Parse a JSONL file with per-line error handling.

    Returns an empty list if the file doesn't exist.
    """
    if not Path(path).exists():
        return []

    records: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
