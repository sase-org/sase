"""Text extraction, tokenization, and scoring helpers for episode recall."""

from __future__ import annotations

import re

from sase.core.episode_wire import EpisodeWire
from sase.memory.episodes._recall_types import EpisodeRecallMatch

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")
_EXCERPT_MAX_CHARS = 180
_SUCCESS_OUTCOMES = {"completed", "noop", "success", "succeeded"}

_TAG_METADATA_KEYS = {
    "keyword",
    "keywords",
    "label",
    "labels",
    "tag",
    "tags",
    "topic",
    "topics",
}
_LOOKUP_METADATA_KEYS = {
    "bead_id",
    "bead_ids",
    "changespec_name",
    "changespec_names",
    "component_key",
    "component_root_kind",
    "component_seed_reason",
    "existing_episode_ids",
    "importance_band",
    "selector_kind",
    "selector_value",
    "weak_agent_families",
    "weak_bead_ids",
    "weak_changespec_names",
    "weak_touched_paths",
}


def recall_excerpt(
    episode: EpisodeWire,
    lesson_text: str,
    query_terms: set[str],
) -> str:
    for lesson in sorted(episode.lessons, key=lambda item: item.id):
        if query_terms & token_set(lesson.text):
            return truncate_excerpt(lesson.text)
    if query_terms & token_set(episode.summary):
        return truncate_excerpt(episode.summary)
    for event in sorted(
        episode.events,
        key=lambda item: (item.timestamp is None, item.timestamp or "", item.id),
    ):
        event_text = " ".join([event.title, event.description or ""])
        if query_terms & token_set(event_text):
            return truncate_excerpt(event_text)
    for factor in sorted(episode.importance_factors, key=lambda item: item.kind):
        factor_text = " ".join(
            [factor.kind, factor.label, " ".join(factor.metadata.values())]
        )
        if query_terms & token_set(factor_text):
            return truncate_excerpt(factor.label)
    for source in sorted(episode.sources, key=lambda item: (item.kind, item.path)):
        source_text = " ".join([source.kind, source.label or "", source.path])
        if query_terms & token_set(source_text):
            return truncate_excerpt(source_text)
    for line in lesson_text.splitlines():
        if query_terms & token_set(line):
            return truncate_excerpt(line)
    return ""


def metadata_recall_terms(metadata: dict[str, str]) -> str:
    parts: list[str] = []
    for key, value in sorted(metadata.items()):
        normalized = key.lower()
        if (
            normalized in _TAG_METADATA_KEYS
            or normalized in _LOOKUP_METADATA_KEYS
            or normalized.endswith("_tags")
            or normalized.endswith("_keywords")
        ):
            parts.append(value)
    return "\n".join(parts)


def weak_refs_recall_terms(episode: EpisodeWire) -> str:
    weak = episode.weak_refs
    parts = [
        *weak.changespec_names,
        *weak.bead_ids,
        *weak.agent_families,
        *weak.touched_paths,
    ]
    for values in weak.metadata.values():
        parts.extend(values)
    return "\n".join(parts)


def importance_recall_terms(episode: EpisodeWire) -> str:
    parts = [episode.importance_band]
    for factor in episode.importance_factors:
        parts.extend([factor.kind, factor.label, *factor.evidence_ids])
        parts.extend(factor.metadata.values())
    return "\n".join(parts)


def safety_recall_terms(episode: EpisodeWire) -> str:
    safety = episode.safety
    return "\n".join(
        [
            "untrusted_transcript_text" if safety.untrusted_transcript_text else "",
            *safety.prompt_injection_phrase_hits,
            *safety.redaction_hits,
            *safety.private_or_missing_source_flags,
            *safety.warnings,
        ]
    )


def weak_refs_summary(episode: EpisodeWire) -> str:
    weak = episode.weak_refs
    parts: list[str] = []
    if weak.changespec_names:
        parts.append("changespecs=" + ",".join(sorted(set(weak.changespec_names))))
    if weak.bead_ids:
        parts.append("beads=" + ",".join(sorted(set(weak.bead_ids))))
    if weak.agent_families:
        parts.append("families=" + ",".join(sorted(set(weak.agent_families))))
    if weak.touched_paths:
        parts.append("paths=" + ",".join(sorted(set(weak.touched_paths))[:5]))
    for key, values in sorted(weak.metadata.items()):
        clean = sorted({value for value in values if value})
        if clean:
            parts.append(f"{key}=" + ",".join(clean[:5]))
    return "; ".join(parts)


def safety_flags(episode: EpisodeWire) -> list[str]:
    safety = episode.safety
    flags = [
        *safety.prompt_injection_phrase_hits,
        *safety.redaction_hits,
        *safety.private_or_missing_source_flags,
        *safety.warnings,
    ]
    if safety.untrusted_transcript_text:
        flags.append("untrusted_transcript_text")
    return sorted({flag for flag in flags if flag})


def recall_sort_key(match: EpisodeRecallMatch) -> tuple[int, int, int, str]:
    return (
        -match.score,
        -_timestamp_sort_value(match.last_event_at),
        -_outcome_rank(match.outcome),
        match.episode_id,
    )


def _outcome_rank(outcome: str | None) -> int:
    if outcome is None:
        return 0
    values = {item.strip().lower() for item in outcome.split(",")}
    return 1 if values & _SUCCESS_OUTCOMES else 0


def _timestamp_sort_value(value: str | None) -> int:
    if not value:
        return 0
    digits = re.sub(r"\D", "", value)
    return int(digits[:14]) if digits else 0


def token_set(text: str) -> set[str]:
    return set(token_list(text))


def token_list(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip("`'\".,;()[]{}<>")
        if token:
            tokens.append(token)
            for part in re.split(r"[._:/-]+", token):
                if part and part != token:
                    tokens.append(part)
    return tokens


def truncate_excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _EXCERPT_MAX_CHARS:
        return collapsed
    return collapsed[: _EXCERPT_MAX_CHARS - 3].rstrip() + "..."
