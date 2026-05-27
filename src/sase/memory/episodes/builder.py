"""Deterministic episode builder for collected source graphs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sase.core.episode_facade import generate_episode_id
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEventWire,
    EpisodeLessonWire,
    EpisodeSourceRefWire,
    EpisodeWire,
)
from sase.memory.episodes.collector import EpisodeDraft
from sase.memory.episodes.source_refs import sort_source_refs
from sase.memory.episodes.title import (
    EpisodeGoal,
    derive_episode_goal,
    derive_episode_title,
)

_HOUSEKEEPING_LABELS = {
    "agent_meta.json",
    "done.json",
    "dynamic_memory.json",
    "memory_reads.jsonl",
    "plan_feedback.jsonl",
    "qa_log.jsonl",
    "raw_xprompt.md",
    "submitted_xprompt.md",
}
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


def build_episode(draft: EpisodeDraft) -> EpisodeWire:
    """Convert a collected draft graph into a canonical episode wire record."""

    sources = sort_source_refs(draft.sources)
    goal = derive_episode_goal(draft)
    title = derive_episode_title(draft)
    events = _derive_events(draft)
    lessons = _derive_lessons(draft, goal)
    summary = _derive_summary(draft, goal, lessons)
    metadata = _derive_metadata(draft, events, lessons)
    episode_id = generate_episode_id(draft.project, draft.root_source_id, sources)
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode_id,
        project=draft.project,
        title=title,
        summary=summary,
        root_source_id=draft.root_source_id,
        sources=sources,
        nodes=sorted(draft.nodes, key=lambda node: node.id),
        edges=sorted(draft.edges, key=lambda edge: edge.id),
        events=events,
        lessons=lessons,
        metadata=metadata,
    )


def _derive_lessons(
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
                id=_stable_id("lesson", candidate.kind, candidate.text, *evidence_ids),
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
        self.text = _collapse(text)
        self.evidence_ids = list(evidence_ids)


def _derive_events(draft: EpisodeDraft) -> list[EpisodeEventWire]:
    events_by_id = {event.id: event for event in draft.events}
    for source in _sources_matching(draft.sources, _is_agent_meta_source):
        meta = _read_json_object(source)
        action = _str_value(meta.get("plan_action")) or _str_value(
            meta.get("auto_approve_plan_action")
        )
        approved = bool(meta.get("plan_approved"))
        submitted_at = _str_list(meta.get("plan_submitted_at"))
        for index, timestamp in enumerate(submitted_at, 1):
            event = _event(
                "decision",
                f"{source.id}:plan-submitted:{index}",
                "Plan submitted",
                timestamp=timestamp,
                evidence_ids=[source.id],
            )
            events_by_id[event.id] = event
        if action or approved:
            title = "Plan decision recorded"
            if action:
                title = f"Plan action recorded: {action}"
            event = _event(
                "decision",
                f"{source.id}:plan-action:{action or approved}",
                title,
                timestamp=submitted_at[-1] if submitted_at else None,
                description=f"approved={str(approved).lower()}",
                evidence_ids=[source.id],
            )
            events_by_id[event.id] = event

    return sorted(
        events_by_id.values(),
        key=lambda event: (event.timestamp is None, event.timestamp or "", event.id),
    )


def _derive_summary(
    draft: EpisodeDraft,
    goal: EpisodeGoal,
    lessons: list[EpisodeLessonWire],
) -> str:
    agent_count = sum(1 for node in draft.nodes if node.kind == "agent_run")
    chat_count = sum(1 for node in draft.nodes if node.kind == "chat")
    outcomes = _recorded_outcomes(draft.sources)
    parts: list[str] = []
    if goal.text:
        parts.append(goal.text.rstrip(".") + ".")
    else:
        parts.append("Collected a deterministic source graph.")
    parts.append(
        f"The episode links {agent_count} agent run(s), {chat_count} chat(s), "
        f"{len(draft.sources)} source(s), and {len(lessons)} lesson record(s)."
    )
    if outcomes:
        joined = ", ".join(f"{name}={outcome}" for name, outcome in outcomes)
        parts.append(f"Recorded outcome(s): {joined}.")
    return " ".join(parts)


def _derive_metadata(
    draft: EpisodeDraft,
    events: list[EpisodeEventWire],
    lessons: list[EpisodeLessonWire],
) -> dict[str, str]:
    agent_names = sorted(
        {node.label for node in draft.nodes if node.kind == "agent_run" and node.label}
    )
    changespec_names = sorted(
        {
            node.metadata["name"]
            for node in draft.nodes
            if node.kind == "changespec" and "name" in node.metadata
        }
    )
    bead_ids = sorted(
        {
            node.metadata["id"]
            for node in draft.nodes
            if node.kind == "bead" and "id" in node.metadata
        }
    )
    timestamps = [event.timestamp for event in events if event.timestamp]
    metadata = {
        **draft.metadata,
        "selector_kind": draft.selector_kind,
        "selector_value": draft.selector_value or "",
        "source_count": str(len(draft.sources)),
        "lesson_count": str(len(lessons)),
    }
    if agent_names:
        metadata["agent_names"] = ",".join(agent_names)
    if changespec_names:
        metadata["changespec_names"] = ",".join(changespec_names)
    if bead_ids:
        metadata["bead_ids"] = ",".join(bead_ids)
    if timestamps:
        metadata["first_event_at"] = min(timestamps)
        metadata["last_event_at"] = max(timestamps)
    return dict(sorted(metadata.items()))


def _plan_decision_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    lessons: list[_LessonCandidate] = []
    for source in _sources_matching(sources, _is_agent_meta_source):
        meta = _read_json_object(source)
        action = _str_value(meta.get("plan_action")) or _str_value(
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
    feedback_sources = _sources_matching(sources, _is_feedback_source)
    if not feedback_sources:
        return []
    excerpts = _jsonl_excerpts(feedback_sources, ("feedback", "message", "text"))
    text = "Feedback was recorded"
    if excerpts:
        text += f": {_join_limited(excerpts)}"
    else:
        text += f" in {len(feedback_sources)} source file(s)"
    return [_LessonCandidate("feedback", text + ".", [s.id for s in feedback_sources])]


def _question_answer_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    question_sources = _sources_matching(sources, _is_question_source)
    if not question_sources:
        return []
    excerpts = _jsonl_excerpts(
        question_sources,
        ("question", "answer", "answers", "selected", "response", "text"),
    )
    text = "Question and answer evidence was recorded"
    if excerpts:
        text += f": {_join_limited(excerpts)}"
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
        and not _is_housekeeping_source(source)
    ]
    if not work_sources:
        return []
    labels = [_source_label(source) for source in work_sources]
    text = f"Work evidence includes {_join_limited(labels)}."
    return [_LessonCandidate("implementation", text, [s.id for s in work_sources])]


def _outcome_lessons(sources: list[EpisodeSourceRefWire]) -> list[_LessonCandidate]:
    outcomes = _recorded_outcomes(sources)
    if not outcomes:
        return []
    done_ids = [source.id for source in _sources_matching(sources, _is_done_source)]
    text = "Recorded agent outcomes: " + ", ".join(
        f"`{name}`=`{outcome}`" for name, outcome in outcomes
    )
    return [_LessonCandidate("verification", text + ".", done_ids)]


def _verification_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    commands_by_source: dict[str, list[str]] = {}
    for source in _sources_matching(sources, _is_verification_text_source):
        text = _read_text(source)
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
    text = f"Verification command(s) were explicitly mentioned: {_join_limited([f'`{command}`' for command in commands])}."
    return [_LessonCandidate("verification", text, evidence_ids)]


def _failure_lessons(sources: list[EpisodeSourceRefWire]) -> list[_LessonCandidate]:
    lessons: list[_LessonCandidate] = []
    for source in _sources_matching(sources, _is_done_source):
        done = _read_json_object(source)
        outcome = (_str_value(done.get("outcome")) or "").lower()
        error = _str_value(done.get("error"))
        traceback = _str_value(done.get("traceback"))
        if not outcome or outcome in _SUCCESS_OUTCOMES:
            continue
        name = _str_value(done.get("name")) or "agent"
        detail = error or traceback or f"outcome `{outcome}`"
        lessons.append(
            _LessonCandidate(
                "failure",
                f"Agent `{name}` recorded failure evidence: {_truncate(detail)}.",
                [source.id],
            )
        )
    return lessons


def _retry_lessons(sources: list[EpisodeSourceRefWire]) -> list[_LessonCandidate]:
    lessons: list[_LessonCandidate] = []
    for source in _sources_matching(
        sources, lambda item: _is_done_source(item) or _is_agent_meta_source(item)
    ):
        data = _read_json_object(source)
        retry_fields = [
            _str_value(data.get("retry_of_timestamp")),
            _str_value(data.get("retried_as_timestamp")),
            _str_value(data.get("retry_chain_root_timestamp")),
            _str_value(data.get("retry_error_category")),
        ]
        if not any(retry_fields) and not _str_list(data.get("retry_started_at")):
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
    text = f"Generated artifact output was collected: {_join_limited([_source_label(s) for s in artifacts])}."
    return [_LessonCandidate("artifact", text, [source.id for source in artifacts])]


def _memory_context_lessons(
    sources: list[EpisodeSourceRefWire],
) -> list[_LessonCandidate]:
    memory_sources = _sources_matching(sources, _is_memory_source)
    if not memory_sources:
        return []
    labels = [_source_label(source) for source in memory_sources]
    text = f"Memory context was captured from {_join_limited(labels)}."
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


def _recorded_outcomes(
    sources: list[EpisodeSourceRefWire],
) -> list[tuple[str, str]]:
    outcomes: list[tuple[str, str]] = []
    for source in _sources_matching(sources, _is_done_source):
        data = _read_json_object(source)
        outcome = _str_value(data.get("outcome"))
        if not outcome:
            continue
        name = _str_value(data.get("name")) or Path(source.path).parent.name
        outcomes.append((name, outcome))
    return sorted(outcomes)


def _extract_verification_commands(text: str) -> list[str]:
    commands: set[str] = set()
    for pattern in _VERIFICATION_PATTERNS:
        for match in pattern.finditer(text):
            commands.add(_collapse(match.group(0)))
    return sorted(commands)


def _jsonl_excerpts(
    sources: list[EpisodeSourceRefWire],
    keys: tuple[str, ...],
) -> list[str]:
    excerpts: list[str] = []
    for source in sources:
        text = _read_text(source)
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
        return _truncate(line)
    if not isinstance(payload, dict):
        return _truncate(str(payload))
    for key in keys:
        value = payload.get(key)
        flattened = _flatten_value(value)
        if flattened:
            return _truncate(flattened)
    return _truncate(json.dumps(payload, sort_keys=True))


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


def _event(
    kind: str,
    key: str,
    title: str,
    *,
    timestamp: str | None = None,
    description: str | None = None,
    evidence_ids: Iterable[str] = (),
) -> EpisodeEventWire:
    return EpisodeEventWire(
        id=_stable_id("event", kind, key),
        kind=kind,
        title=title,
        timestamp=timestamp,
        description=description,
        evidence_ids=sorted({item for item in evidence_ids if item}),
    )


def _sources_matching(
    sources: list[EpisodeSourceRefWire],
    predicate: Callable[[EpisodeSourceRefWire], bool],
) -> list[EpisodeSourceRefWire]:
    return [
        source
        for source in sorted(sources, key=lambda item: (item.path, item.id))
        if predicate(source)
    ]


def _is_agent_meta_source(source: EpisodeSourceRefWire) -> bool:
    return Path(source.path).name == "agent_meta.json"


def _is_done_source(source: EpisodeSourceRefWire) -> bool:
    return Path(source.path).name == "done.json"


def _is_feedback_source(source: EpisodeSourceRefWire) -> bool:
    return source.kind == "feedback" or Path(source.path).name == "plan_feedback.jsonl"


def _is_question_source(source: EpisodeSourceRefWire) -> bool:
    return source.kind == "question" or Path(source.path).name == "qa_log.jsonl"


def _is_memory_source(source: EpisodeSourceRefWire) -> bool:
    return source.kind in {"dynamic_memory", "memory_read"} or Path(
        source.path
    ).name in {
        "dynamic_memory.json",
        "memory_reads.jsonl",
    }


def _is_verification_text_source(source: EpisodeSourceRefWire) -> bool:
    if not source.exists:
        return False
    return source.kind in {"artifact", "chat"} or Path(source.path).name in {
        "done.json",
        "output.txt",
        "response.md",
    }


def _is_housekeeping_source(source: EpisodeSourceRefWire) -> bool:
    return Path(source.path).name in _HOUSEKEEPING_LABELS


def _source_label(source: EpisodeSourceRefWire) -> str:
    return source.label or Path(source.path).name or source.path


def _read_json_object(source: EpisodeSourceRefWire) -> dict[str, Any]:
    text = _read_text(source)
    if text is None:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(source: EpisodeSourceRefWire) -> str | None:
    if not source.exists:
        return None
    path = Path(source.path)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")[:131072]
    except (OSError, UnicodeDecodeError):
        return None


def _str_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _join_limited(values: Iterable[str], *, limit: int = 6) -> str:
    cleaned = [_collapse(value).strip("`") for value in values if _collapse(value)]
    head = cleaned[:limit]
    rendered = ", ".join(f"`{value}`" for value in head)
    if len(cleaned) > limit:
        rendered += f", and {len(cleaned) - limit} more"
    return rendered


def _truncate(text: str, limit: int = 180) -> str:
    collapsed = _collapse(text)
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


__all__ = [
    "build_episode",
]
