"""Deterministic importance scoring for episode v2 records."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from sase.core.episode_wire import (
    EpisodeEventWire,
    EpisodeImportanceFactorWire,
    EpisodeSourceRefWire,
    EpisodeWeakRefsWire,
)
from sase.memory.episodes._models import EpisodeDraft

_SUCCESS_OUTCOMES = {"completed", "noop", "success", "succeeded"}
_DESIGN_PROMPT_RE = re.compile(
    r"\b(research|memory|lesson|postmortem|design decision|architecture decision)\b",
    re.IGNORECASE,
)
_VERIFICATION_PATTERNS = (
    re.compile(r"\bjust\s+(?:check|test-cov|test-visual|test|lint|fmt|install)\b"),
    re.compile(r"\bpytest\b(?:\s+[-\w./:=]+){0,6}"),
    re.compile(r"\bruff\s+check\b"),
    re.compile(r"\bmypy\b"),
    re.compile(r"\bcargo\s+(?:test|clippy|fmt)\b"),
    re.compile(r"\buv\s+run\s+pytest\b(?:\s+[-\w./:=]+){0,6}"),
)
_HOUSEKEEPING_NAMES = {
    "agent_meta.json",
    "done.json",
    "dynamic_memory.json",
    "memory_reads.jsonl",
    "plan_feedback.jsonl",
    "qa_log.jsonl",
    "raw_xprompt.md",
    "submitted_xprompt.md",
    "workflow_state.json",
}


@dataclass(frozen=True)
class EpisodeImportanceScore:
    """Deterministic score, band, and factor explanation."""

    score: int
    band: str
    factors: list[EpisodeImportanceFactorWire]


def score_episode_importance(
    draft: EpisodeDraft,
    *,
    events: Sequence[EpisodeEventWire],
    weak_refs: EpisodeWeakRefsWire,
) -> EpisodeImportanceScore:
    """Return deterministic importance metadata for a component episode."""

    sources = sorted(draft.sources, key=lambda source: (source.path, source.id))
    source_texts = _source_texts(sources)
    factors = [
        factor
        for factor in (
            _retry_recovered_factor(sources),
            _design_prompt_factor(sources, source_texts),
            _durable_docs_factor(sources, weak_refs),
            _shared_core_factor(sources, weak_refs),
            _interaction_factor(sources, events),
            _artifact_factor(sources, weak_refs),
            _verification_factor(sources, source_texts),
            _connected_work_factor(draft, sources),
            _noop_factor(sources),
            _hidden_chop_factor(sources),
            _tiny_transcript_factor(sources, source_texts, weak_refs),
            _dream_generated_factor(sources, source_texts),
        )
        if factor is not None
    ]
    score = max(0, min(100, sum(factor.score for factor in factors)))
    return EpisodeImportanceScore(
        score=score,
        band=_importance_band(score),
        factors=sorted(
            factors,
            key=lambda factor: (factor.score < 0, -abs(factor.score), factor.kind),
        ),
    )


def _retry_recovered_factor(
    sources: Sequence[EpisodeSourceRefWire],
) -> EpisodeImportanceFactorWire | None:
    retry_evidence: list[str] = []
    success = False
    for source in sources:
        data = _read_json_object(source)
        if not data:
            continue
        if _has_any_key(
            data,
            (
                "retry_of_timestamp",
                "retried_as_timestamp",
                "retry_chain_root_timestamp",
                "retry_error_category",
            ),
        ) or _str_list(data.get("retry_started_at")):
            retry_evidence.append(source.id)
        outcome = _str_value(data.get("outcome"))
        if outcome is not None and outcome.lower() in _SUCCESS_OUTCOMES:
            success = True
    if not retry_evidence or not success:
        return None
    return _factor(
        "retry_recovered",
        "Retry or failed attempt later succeeded",
        18,
        retry_evidence,
    )


def _design_prompt_factor(
    sources: Sequence[EpisodeSourceRefWire],
    source_texts: dict[str, str],
) -> EpisodeImportanceFactorWire | None:
    evidence = [
        source.id
        for source in sources
        if source.kind in {"chat", "plan", "artifact"}
        and _DESIGN_PROMPT_RE.search(source_texts.get(source.id, ""))
    ]
    if not evidence:
        return None
    return _factor(
        "design_or_memory_requested",
        "Research, memory, lesson, postmortem, or design-decision work requested",
        16,
        evidence,
    )


def _durable_docs_factor(
    sources: Sequence[EpisodeSourceRefWire],
    weak_refs: EpisodeWeakRefsWire,
) -> EpisodeImportanceFactorWire | None:
    paths = _all_paths(sources, weak_refs)
    evidence = _evidence_for_paths(
        sources,
        paths,
        (
            "sdd/research/",
            "sdd/events/",
            "memory/",
            "AGENTS.md",
            "architecture",
        ),
    )
    if not evidence:
        return None
    return _factor(
        "durable_knowledge_docs",
        "Durable research, memory, event, agent-instruction, or architecture docs touched",
        14,
        evidence,
    )


def _shared_core_factor(
    sources: Sequence[EpisodeSourceRefWire],
    weak_refs: EpisodeWeakRefsWire,
) -> EpisodeImportanceFactorWire | None:
    paths = _all_paths(sources, weak_refs)
    evidence = _evidence_for_paths(
        sources,
        paths,
        (
            "sase-core",
            "src/sase/core/",
            "src/sase/default_config.yml",
            "default_config.yml",
            "hook",
            "launch",
            "finaliz",
            "schema",
        ),
    )
    if not evidence:
        return None
    return _factor(
        "shared_core_or_runtime",
        "Shared/core code, schema, config, launch, finalization, or hook surface touched",
        12,
        evidence,
    )


def _interaction_factor(
    sources: Sequence[EpisodeSourceRefWire],
    events: Sequence[EpisodeEventWire],
) -> EpisodeImportanceFactorWire | None:
    evidence: set[str] = set()
    for source in sources:
        if Path(source.path).name in {"plan_feedback.jsonl", "qa_log.jsonl"}:
            evidence.add(source.id)
        data = _read_json_object(source)
        if data.get("plan_approved") or _str_value(data.get("plan_action")):
            evidence.add(source.id)
    for event in events:
        if event.kind in {"feedback", "question_answer", "decision"}:
            evidence.update(event.evidence_ids)
    if not evidence:
        return None
    return _factor(
        "plan_feedback_or_qa",
        "Plan approval, user feedback, or question/answer loop present",
        10,
        evidence,
    )


def _artifact_factor(
    sources: Sequence[EpisodeSourceRefWire],
    weak_refs: EpisodeWeakRefsWire,
) -> EpisodeImportanceFactorWire | None:
    evidence = {
        source.id
        for source in sources
        if source.kind in {"image", "pdf", "workflow_step"}
        or (
            source.kind == "artifact"
            and not _is_housekeeping_source(source)
            and (
                "diff" in (source.label or "").lower()
                or Path(source.path).suffix in {".diff", ".patch"}
            )
        )
    }
    if weak_refs.changespec_names:
        evidence.update(source.id for source in sources if Path(source.path).suffix)
    if not evidence:
        return None
    return _factor(
        "artifact_or_changespec_evidence",
        "Diff, generated artifact, workflow-step, commit, PR, or ChangeSpec evidence present",
        8,
        evidence,
    )


def _verification_factor(
    sources: Sequence[EpisodeSourceRefWire],
    source_texts: dict[str, str],
) -> EpisodeImportanceFactorWire | None:
    commands_by_source: dict[str, list[str]] = {}
    for source in sources:
        text = source_texts.get(source.id, "")
        if not text:
            continue
        commands = sorted(
            {
                _collapse(match.group(0))
                for pattern in _VERIFICATION_PATTERNS
                for match in pattern.finditer(text)
            }
        )
        if commands:
            commands_by_source[source.id] = commands
    if not commands_by_source:
        return None
    return _factor(
        "verification_present",
        "Verification command detected",
        6,
        commands_by_source,
        metadata={
            "commands": ",".join(
                sorted(
                    {
                        cmd
                        for commands in commands_by_source.values()
                        for cmd in commands
                    }
                )
            )
        },
    )


def _connected_work_factor(
    draft: EpisodeDraft,
    sources: Sequence[EpisodeSourceRefWire],
) -> EpisodeImportanceFactorWire | None:
    chat_count = _int_metadata(draft.metadata.get("chat_count"))
    workflow_steps = [source.id for source in sources if source.kind == "workflow_step"]
    if chat_count <= 1 and not workflow_steps:
        return None
    evidence = [source.id for source in sources if source.kind == "chat"]
    evidence.extend(workflow_steps)
    return _factor(
        "connected_chats_or_steps",
        "Multiple connected chats or workflow steps present",
        5,
        evidence,
        metadata={
            "chat_count": str(chat_count),
            "workflow_step_count": str(len(workflow_steps)),
        },
    )


def _noop_factor(
    sources: Sequence[EpisodeSourceRefWire],
) -> EpisodeImportanceFactorWire | None:
    outcomes = [_record_outcome(source) for source in sources]
    outcomes = [outcome for outcome in outcomes if outcome is not None]
    if not outcomes or not all(
        outcome in {"completed", "noop"} for outcome in outcomes
    ):
        return None
    has_work_artifact = any(
        source.kind in {"image", "pdf", "workflow_step", "plan"}
        or (
            source.kind == "artifact"
            and not _is_housekeeping_source(source)
            and Path(source.path).name not in {"output.txt"}
        )
        for source in sources
    )
    if has_work_artifact:
        return None
    return _factor(
        "completed_no_artifact_noop",
        "Completed/noop episode has no durable artifact evidence",
        -12,
        [source.id for source in sources if _record_outcome(source) is not None],
    )


def _hidden_chop_factor(
    sources: Sequence[EpisodeSourceRefWire],
) -> EpisodeImportanceFactorWire | None:
    hidden_evidence: list[str] = []
    for source in sources:
        data = _read_json_object(source)
        if data.get("hidden") is True:
            hidden_evidence.append(source.id)
    if not hidden_evidence:
        return None
    has_failure = any(
        (_record_outcome(source) or "") not in {"", *list(_SUCCESS_OUTCOMES)}
        for source in sources
        if _record_outcome(source) is not None
    )
    has_diff = any(
        "diff" in (source.label or "").lower()
        or Path(source.path).suffix in {".diff", ".patch"}
        for source in sources
    )
    path_text = "\n".join(source.path.lower() for source in sources)
    looks_like_chop = "chop" in path_text or "lumberjack" in path_text
    if not looks_like_chop or has_failure or has_diff:
        return None
    return _factor(
        "hidden_recurring_chop_noop",
        "Hidden recurring chop with no failure or diff",
        -14,
        hidden_evidence,
    )


def _tiny_transcript_factor(
    sources: Sequence[EpisodeSourceRefWire],
    source_texts: dict[str, str],
    weak_refs: EpisodeWeakRefsWire,
) -> EpisodeImportanceFactorWire | None:
    chat_text = "\n".join(
        source_texts.get(source.id, "") for source in sources if source.kind == "chat"
    )
    if not chat_text or len(chat_text) > 800:
        return None
    has_context = any(
        source.kind in {"plan", "feedback", "question", "workflow_step"}
        or Path(source.path).suffix in {".diff", ".patch"}
        for source in sources
    ) or any(path.startswith("sdd/") for path in weak_refs.touched_paths)
    if has_context:
        return None
    return _factor(
        "tiny_transcript_low_signal",
        "Tiny transcript has no plan, diff, feedback, question, or SDD source",
        -10,
        [source.id for source in sources if source.kind == "chat"],
    )


def _dream_generated_factor(
    sources: Sequence[EpisodeSourceRefWire],
    source_texts: dict[str, str],
) -> EpisodeImportanceFactorWire | None:
    evidence = [
        source.id
        for source in sources
        if "dream"
        in f"{source.path} {source.label or ''} {source_texts.get(source.id, '')}".lower()
    ]
    if not evidence:
        return None
    return _factor(
        "dream_generated",
        "Dream-generated episode unless explicitly allowed",
        -20,
        evidence,
    )


def _factor(
    kind: str,
    label: str,
    score: int,
    evidence: Iterable[str] | dict[str, Any],
    *,
    metadata: dict[str, str] | None = None,
) -> EpisodeImportanceFactorWire:
    evidence_ids = evidence.keys() if isinstance(evidence, dict) else evidence
    return EpisodeImportanceFactorWire(
        kind=kind,
        label=label,
        score=score,
        evidence_ids=sorted({item for item in evidence_ids if item}),
        metadata=dict(sorted((metadata or {}).items())),
    )


def _importance_band(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _source_texts(
    sources: Sequence[EpisodeSourceRefWire],
) -> dict[str, str]:
    return {source.id: text for source in sources if (text := _read_text(source))}


def _all_paths(
    sources: Sequence[EpisodeSourceRefWire],
    weak_refs: EpisodeWeakRefsWire,
) -> list[str]:
    return [*(source.path for source in sources), *weak_refs.touched_paths]


def _evidence_for_paths(
    sources: Sequence[EpisodeSourceRefWire],
    paths: Sequence[str],
    needles: Sequence[str],
) -> list[str]:
    lower_paths = [path.lower() for path in paths]
    if not any(
        any(needle.lower() in path for needle in needles) for path in lower_paths
    ):
        return []
    source_evidence = sorted(
        {
            source.id
            for source in sources
            if any(needle.lower() in source.path.lower() for needle in needles)
        }
    )
    if source_evidence:
        return source_evidence
    return [sources[0].id] if sources else []


def _record_outcome(source: EpisodeSourceRefWire) -> str | None:
    outcome = _str_value(_read_json_object(source).get("outcome"))
    return outcome.lower() if outcome is not None else None


def _is_housekeeping_source(source: EpisodeSourceRefWire) -> bool:
    return Path(source.path).name in _HOUSEKEEPING_NAMES


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


def _has_any_key(data: dict[str, Any], keys: Iterable[str]) -> bool:
    return any(_str_value(data.get(key)) for key in keys)


def _str_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _int_metadata(value: str | None) -> int:
    if value is None or not value.isdigit():
        return 0
    return int(value)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


__all__ = [
    "EpisodeImportanceScore",
    "score_episode_importance",
]
