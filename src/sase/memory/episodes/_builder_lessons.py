"""Legacy lesson derivation for deterministic episode building."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sase.core.episode_wire import EpisodeLessonWire, EpisodeSourceRefWire
from sase.memory.episodes._builder_support import (
    collapse,
    is_agent_meta_source,
    is_done_source,
    is_feedback_source,
    is_housekeeping_source,
    is_memory_source,
    is_question_source,
    is_verification_text_source,
    join_limited,
    read_json_object,
    read_text,
    recorded_outcomes,
    source_label,
    sources_matching,
    stable_id,
    str_list,
    str_value,
    truncate,
)
from sase.memory.episodes.collector import EpisodeDraft
from sase.memory.episodes.title import EpisodeGoal

_LESSON_KIND_ORDER = {
    "goal": 0,
    "decision": 1,
    "feedback": 2,
    "question_answer": 3,
    "implementation": 4,
    "verification": 5,
    "failure": 6,
    "retry": 7,
    "artifact": 8,
    "memory_context": 9,
    "open_question": 10,
}
_SUCCESS_OUTCOMES = {"completed", "noop", "success", "succeeded"}
_VERIFICATION_PATTERNS = (
    re.compile(r"\bjust\s+(?:check|test-cov|test-visual|test|lint|fmt|install)\b"),
    re.compile(r"\bpytest\b(?:\s+[-\w./:=]+){0,6}"),
    re.compile(r"\bruff\s+check\b"),
    re.compile(r"\bmypy\b"),
    re.compile(r"\bcargo\s+(?:test|clippy|fmt)\b"),
    re.compile(r"\buv\s+run\s+pytest\b(?:\s+[-\w./:=]+){0,6}"),
)


def derive_lessons(
    draft: EpisodeDraft,
    goal: EpisodeGoal,
) -> list[EpisodeLessonWire]:
    candidates: list[_LessonCandidate] = []
    if goal.text and goal.evidence_ids:
        candidates.append(
            _LessonCandidate("goal", f"Goal: {goal.text}", goal.evidence_ids)
        )

    candidates.extend(_plan_decision_lessons(draft.sources))
    candidates.extend(_feedback_lessons(draft.sources))
    candidates.extend(_question_answer_lessons(draft.sources))
    candidates.extend(_implementation_lessons(draft.sources))
    candidates.extend(_outcome_lessons(draft.sources))
    candidates.extend(_verification_lessons(draft.sources))
    candidates.extend(_failure_lessons(draft.sources))
    candidates.extend(_retry_lessons(draft.sources))
    candidates.extend(_artifact_lessons(draft.sources))
    candidates.extend(_memory_context_lessons(draft.sources))
    candidates.extend(_open_question_lessons(draft.sources))

    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    lessons: list[EpisodeLessonWire] = []
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            _LESSON_KIND_ORDER.get(candidate.kind, 99),
            candidate.text,
            tuple(candidate.evidence_ids),
        ),
    )
    for candidate in ordered:
        evidence_ids = sorted({item for item in candidate.evidence_ids if item})
        if not evidence_ids:
            continue
        key = (candidate.kind, candidate.text, tuple(evidence_ids))
        if key in seen:
            continue
        seen.add(key)
        lessons.append(
            EpisodeLessonWire(
                id=stable_id("lesson", candidate.kind, candidate.text, *evidence_ids),
                kind=candidate.kind,
                text=candidate.text,
                evidence_ids=evidence_ids,
                source_confidence="deterministic",
            )
        )
    return lessons


class _LessonCandidate:
    def __init__(self, kind: str, text: str, evidence_ids: Iterable[str]) -> None:
        self.kind = kind
        self.text = collapse(text)
        self.evidence_ids = list(evidence_ids)


def _plan_decision_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    lessons: list[_LessonCandidate] = []
    for source in sources_matching(sources, is_agent_meta_source):
        meta = read_json_object(source)
        action = str_value(meta.get("plan_action")) or str_value(
            meta.get("auto_approve_plan_action")
        )
        approved = bool(meta.get("plan_approved"))
        if not action and not approved:
            continue
        if action and approved:
            text = f"Plan decision recorded action `{action}` with approval."
        elif action:
            text = f"Plan decision recorded action `{action}`."
        else:
            text = "Plan approval was recorded."
        lessons.append(_LessonCandidate("decision", text, [source.id]))
    return lessons


def _feedback_lessons(sources: list[EpisodeSourceRefWire]) -> list[_LessonCandidate]:
    feedback_sources = sources_matching(sources, is_feedback_source)
    if not feedback_sources:
        return []
    excerpts = _jsonl_excerpts(feedback_sources, ("feedback", "message", "text"))
    text = "Feedback was recorded"
    if excerpts:
        text += f": {join_limited(excerpts)}"
    else:
        text += f" in {len(feedback_sources)} source file(s)"
    return [_LessonCandidate("feedback", text + ".", [s.id for s in feedback_sources])]


def _question_answer_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    question_sources = sources_matching(sources, is_question_source)
    if not question_sources:
        return []
    excerpts = _jsonl_excerpts(
        question_sources,
        ("question", "answer", "answers", "selected", "response", "text"),
    )
    text = "Question and answer evidence was recorded"
    if excerpts:
        text += f": {join_limited(excerpts)}"
    else:
        text += f" in {len(question_sources)} source file(s)"
    return [
        _LessonCandidate(
            "question_answer",
            text + ".",
            [s.id for s in question_sources],
        )
    ]


def _implementation_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    work_sources = [
        source
        for source in sources
        if source.kind in {"artifact", "plan", "workflow_step"}
        and not is_housekeeping_source(source)
    ]
    if not work_sources:
        return []
    labels = [source_label(source) for source in work_sources]
    text = f"Work evidence includes {join_limited(labels)}."
    return [_LessonCandidate("implementation", text, [s.id for s in work_sources])]


def _outcome_lessons(sources: list[EpisodeSourceRefWire]) -> list[_LessonCandidate]:
    outcomes = recorded_outcomes(sources)
    if not outcomes:
        return []
    done_ids = [source.id for source in sources_matching(sources, is_done_source)]
    text = "Recorded agent outcomes: " + ", ".join(
        f"`{name}`=`{outcome}`" for name, outcome in outcomes
    )
    return [_LessonCandidate("verification", text + ".", done_ids)]


def _verification_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    commands_by_source: dict[str, list[str]] = {}
    for source in sources_matching(sources, is_verification_text_source):
        text = read_text(source)
        if not text:
            continue
        commands = _extract_verification_commands(text)
        if commands:
            commands_by_source[source.id] = commands
    if not commands_by_source:
        return []
    commands = sorted(
        {command for values in commands_by_source.values() for command in values}
    )
    evidence_ids = sorted(commands_by_source)
    text = f"Verification command(s) were explicitly mentioned: {join_limited([f'`{command}`' for command in commands])}."
    return [_LessonCandidate("verification", text, evidence_ids)]


def _failure_lessons(sources: list[EpisodeSourceRefWire]) -> list[_LessonCandidate]:
    lessons: list[_LessonCandidate] = []
    for source in sources_matching(sources, is_done_source):
        done = read_json_object(source)
        outcome = (str_value(done.get("outcome")) or "").lower()
        error = str_value(done.get("error"))
        traceback = str_value(done.get("traceback"))
        if not outcome or outcome in _SUCCESS_OUTCOMES:
            continue
        name = str_value(done.get("name")) or "agent"
        detail = error or traceback or f"outcome `{outcome}`"
        lessons.append(
            _LessonCandidate(
                "failure",
                f"Agent `{name}` recorded failure evidence: {truncate(detail)}.",
                [source.id],
            )
        )
    return lessons


def _retry_lessons(sources: list[EpisodeSourceRefWire]) -> list[_LessonCandidate]:
    lessons: list[_LessonCandidate] = []
    for source in sources_matching(
        sources, lambda item: is_done_source(item) or is_agent_meta_source(item)
    ):
        data = read_json_object(source)
        retry_fields = [
            str_value(data.get("retry_of_timestamp")),
            str_value(data.get("retried_as_timestamp")),
            str_value(data.get("retry_chain_root_timestamp")),
            str_value(data.get("retry_error_category")),
        ]
        if not any(retry_fields) and not str_list(data.get("retry_started_at")):
            continue
        lessons.append(
            _LessonCandidate(
                "retry",
                "Retry lineage was recorded for this episode.",
                [source.id],
            )
        )
    return lessons


def _artifact_lessons(sources: list[EpisodeSourceRefWire]) -> list[_LessonCandidate]:
    artifacts = [source for source in sources if source.kind in {"image", "pdf"}]
    if not artifacts:
        return []
    text = f"Generated artifact output was collected: {join_limited([source_label(s) for s in artifacts])}."
    return [_LessonCandidate("artifact", text, [source.id for source in artifacts])]


def _memory_context_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    memory_sources = sources_matching(sources, is_memory_source)
    if not memory_sources:
        return []
    labels = [source_label(source) for source in memory_sources]
    text = f"Memory context was captured from {join_limited(labels)}."
    return [
        _LessonCandidate(
            "memory_context",
            text,
            [source.id for source in memory_sources],
        )
    ]


def _open_question_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    pending_sources = [
        source
        for source in sources
        if Path(source.path).name == "pending_question.json"
    ]
    if not pending_sources:
        return []
    return [
        _LessonCandidate(
            "open_question",
            "A pending question marker was collected.",
            [source.id for source in pending_sources],
        )
    ]


def _extract_verification_commands(text: str) -> list[str]:
    commands: set[str] = set()
    for pattern in _VERIFICATION_PATTERNS:
        for match in pattern.finditer(text):
            commands.add(collapse(match.group(0)))
    return sorted(commands)


def _jsonl_excerpts(
    sources: list[EpisodeSourceRefWire],
    keys: tuple[str, ...],
) -> list[str]:
    excerpts: list[str] = []
    for source in sources:
        text = read_text(source)
        if not text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            value = _jsonl_value_excerpt(line, keys)
            if value:
                excerpts.append(value)
                break
    return excerpts


def _jsonl_value_excerpt(line: str, keys: tuple[str, ...]) -> str | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return truncate(line)
    if not isinstance(payload, dict):
        return truncate(str(payload))
    for key in keys:
        value = payload.get(key)
        flattened = _flatten_value(value)
        if flattened:
            return truncate(flattened)
    return truncate(json.dumps(payload, sort_keys=True))


def _flatten_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        list_parts = [_flatten_value(item) for item in value]
        return ", ".join(part for part in list_parts if part is not None and part)
    if isinstance(value, dict):
        dict_parts: list[str] = []
        for key, item in sorted(value.items()):
            flattened = _flatten_value(item)
            if flattened:
                dict_parts.append(f"{key}: {flattened}")
        return "; ".join(dict_parts)
    return str(value)
