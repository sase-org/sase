"""Shared Q&A follow-up prompt assembly."""

from __future__ import annotations

from typing import Any

from sase.main.qa_markdown import QARound, build_merged_qa_markdown


def build_qa_round(
    questions: list[dict[str, Any]],
    response: dict[str, Any],
) -> QARound:
    """Build a QARound from a question list and response dict."""
    response_answers = response.get("answers", []) or []
    if len(response_answers) == len(questions):
        aligned = list(response_answers)
    else:
        by_text: dict[str, dict[str, Any]] = {
            a.get("question", ""): a for a in response_answers if a.get("question")
        }
        aligned = []
        for q in questions:
            match = by_text.get(q.get("question", ""))
            aligned.append(match if match is not None else {})

    return QARound(
        questions=list(questions),
        answers=aligned,
        global_note=response.get("global_note") or None,
    )


def merge_qa_for_prompt(rounds: list[QARound]) -> str:
    """Render accumulated Q&A rounds as a single prompt-bound section."""
    body = build_merged_qa_markdown(rounds)
    return f"%xprompts_enabled:false\n{body}\n%xprompts_enabled:true"


def assemble_question_followup_prompt(
    base_prompt: str,
    rounds: list[QARound],
) -> str:
    """Append rendered Q&A rounds to the prompt used by the follow-up agent."""
    return base_prompt + "\n\n" + merge_qa_for_prompt(rounds)


def _qa_rounds_from_payload(payload: object) -> list[QARound]:
    """Normalize public ``#with_q_and_a`` JSON payloads into Q&A rounds."""
    raw_rounds = _raw_rounds_from_payload(payload)
    rounds = [
        _qa_round_from_mapping(raw_round, index)
        for index, raw_round in enumerate(raw_rounds, start=1)
    ]
    if not rounds:
        raise ValueError("qa_file must contain at least one Q&A round")
    return rounds


def _raw_rounds_from_payload(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rounds = payload.get("rounds")
        if rounds is not None:
            if not isinstance(rounds, list):
                raise ValueError("qa_file field 'rounds' must be a list")
            return _ensure_mapping_list(rounds, label="rounds")
        return [payload]

    if isinstance(payload, list):
        return _ensure_mapping_list(payload, label="top-level list")

    raise ValueError("qa_file must contain a JSON object or list")


def _ensure_mapping_list(items: list[object], *, label: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"qa_file {label} item {index} must be an object")
        out.append(item)
    return out


def _qa_round_from_mapping(raw: dict[str, Any], index: int) -> QARound:
    questions = raw.get("questions")
    if not isinstance(questions, list):
        raise ValueError(f"qa_file round {index} must contain a 'questions' list")
    if not all(isinstance(question, dict) for question in questions):
        raise ValueError(f"qa_file round {index} questions must be objects")

    response = raw.get("response")
    if response is None:
        response = {
            "answers": raw.get("answers", []),
            "global_note": raw.get("global_note"),
        }
    if not isinstance(response, dict):
        raise ValueError(f"qa_file round {index} response must be an object")

    return build_qa_round(list(questions), response)


# Keep a same-file reference so symvision accepts this YAML-only entry point.
_QA_XPROMPT_ENTRYPOINTS = (_qa_rounds_from_payload,)
