"""Non-lesson derivation for deterministic episode building."""

from __future__ import annotations

import re

from sase.core.episode_wire import (
    EpisodeEventWire,
    EpisodeLessonWire,
    EpisodeSafetyWire,
    EpisodeSourceRefWire,
    EpisodeWeakRefsWire,
)
from sase.memory.episodes._builder_support import (
    event,
    is_agent_meta_source,
    read_json_object,
    read_text,
    recorded_outcomes,
    sources_matching,
    str_list,
    str_value,
)
from sase.memory.episodes.collector import EpisodeDraft
from sase.memory.episodes.title import EpisodeGoal

_PROMPT_INJECTION_PHRASES = (
    "ignore previous instructions",
    "disregard previous instructions",
    "forget all previous instructions",
    "reveal the system prompt",
    "print the system prompt",
    "developer message",
    "system message",
    "you are now",
)
_REDACTION_PATTERNS = {
    "api-key-assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|token|secret|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}"
    ),
    "bearer-token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_./+=-]{16,}"),
    "private-key-block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def is_v2_component_draft(draft: EpisodeDraft) -> bool:
    return bool(draft.metadata.get("component_key"))


def derive_events(draft: EpisodeDraft) -> list[EpisodeEventWire]:
    events_by_id = {event.id: event for event in draft.events}
    for source in sources_matching(draft.sources, is_agent_meta_source):
        meta = read_json_object(source)
        action = str_value(meta.get("plan_action")) or str_value(
            meta.get("auto_approve_plan_action")
        )
        approved = bool(meta.get("plan_approved"))
        submitted_at = str_list(meta.get("plan_submitted_at"))
        for index, timestamp in enumerate(submitted_at, 1):
            current_event = event(
                "decision",
                f"{source.id}:plan-submitted:{index}",
                "Plan submitted",
                timestamp=timestamp,
                evidence_ids=[source.id],
            )
            events_by_id[current_event.id] = current_event
        if action or approved:
            title = "Plan decision recorded"
            if action:
                title = f"Plan action recorded: {action}"
            current_event = event(
                "decision",
                f"{source.id}:plan-action:{action or approved}",
                title,
                timestamp=submitted_at[-1] if submitted_at else None,
                description=f"approved={str(approved).lower()}",
                evidence_ids=[source.id],
            )
            events_by_id[current_event.id] = current_event

    return sorted(
        events_by_id.values(),
        key=lambda current_event: (
            current_event.timestamp is None,
            current_event.timestamp or "",
            current_event.id,
        ),
    )


def derive_summary(
    draft: EpisodeDraft,
    goal: EpisodeGoal,
    lessons: list[EpisodeLessonWire],
) -> str:
    agent_count = sum(1 for node in draft.nodes if node.kind == "agent_run")
    chat_count = sum(1 for node in draft.nodes if node.kind == "chat")
    outcomes = recorded_outcomes(draft.sources)
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


def derive_v2_summary(
    draft: EpisodeDraft,
    goal: EpisodeGoal,
    events: list[EpisodeEventWire],
    weak_refs: EpisodeWeakRefsWire,
    safety: EpisodeSafetyWire,
) -> str:
    agent_count = sum(1 for node in draft.nodes if node.kind == "agent_run")
    chat_count = sum(1 for node in draft.nodes if node.kind == "chat")
    outcomes = recorded_outcomes(draft.sources)
    timestamps = sorted({event.timestamp for event in events if event.timestamp})
    parts: list[str] = []
    if goal.text:
        parts.append(goal.text.rstrip(".") + ".")
    else:
        parts.append("Collected factual connected-component evidence.")
    parts.append(
        f"The component contains {agent_count} agent run(s), {chat_count} chat(s), "
        f"{len(draft.sources)} source(s), and {len(events)} timeline event(s)."
    )
    if timestamps:
        parts.append(f"Time span: {timestamps[0]} to {timestamps[-1]}.")
    if outcomes:
        joined = ", ".join(f"{name}={outcome}" for name, outcome in outcomes)
        parts.append(f"Recorded outcome(s): {joined}.")
    weak_parts: list[str] = []
    if weak_refs.changespec_names:
        weak_parts.append("ChangeSpecs " + ", ".join(weak_refs.changespec_names))
    if weak_refs.bead_ids:
        weak_parts.append("beads " + ", ".join(weak_refs.bead_ids))
    if weak_refs.agent_families:
        weak_parts.append("families " + ", ".join(weak_refs.agent_families))
    if weak_parts:
        parts.append("Weak refs: " + "; ".join(weak_parts) + ".")
    if safety.warnings:
        parts.append(f"Warnings: {len(safety.warnings)} safety flag(s).")
    return " ".join(parts)


def derive_metadata(
    draft: EpisodeDraft,
    events: list[EpisodeEventWire],
    lessons: list[EpisodeLessonWire],
    *,
    weak_refs: EpisodeWeakRefsWire,
    safety: EpisodeSafetyWire,
    importance_score: int,
    importance_band: str,
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
    agent_count = sum(1 for node in draft.nodes if node.kind == "agent_run")
    chat_count = sum(1 for node in draft.nodes if node.kind == "chat")
    timestamps = [event.timestamp for event in events if event.timestamp]
    metadata = {
        **draft.metadata,
        "selector_kind": draft.selector_kind,
        "selector_value": draft.selector_value or "",
        "agent_count": str(agent_count),
        "chat_count": str(chat_count),
        "source_count": str(len(draft.sources)),
        "lesson_count": str(len(lessons)),
        "importance_score": str(importance_score),
        "importance_band": importance_band,
        "warning_count": str(len(safety.warnings)),
    }
    if agent_names:
        metadata["agent_names"] = ",".join(agent_names)
    if changespec_names or weak_refs.changespec_names:
        metadata["changespec_names"] = ",".join(
            sorted({*changespec_names, *weak_refs.changespec_names})
        )
    if bead_ids or weak_refs.bead_ids:
        metadata["bead_ids"] = ",".join(sorted({*bead_ids, *weak_refs.bead_ids}))
    outcomes = recorded_outcomes(draft.sources)
    if outcomes:
        metadata["outcome"] = ",".join(sorted({outcome for _name, outcome in outcomes}))
    if timestamps:
        metadata["first_event_at"] = min(timestamps)
        metadata["last_event_at"] = max(timestamps)
    return dict(sorted(metadata.items()))


def derive_weak_refs(draft: EpisodeDraft) -> EpisodeWeakRefsWire:
    changespec_names = {
        *(_metadata_csv(draft.metadata.get("weak_changespec_names"))),
        *(
            node.metadata["name"]
            for node in draft.nodes
            if node.kind == "changespec" and "name" in node.metadata
        ),
    }
    bead_ids = {
        *(_metadata_csv(draft.metadata.get("weak_bead_ids"))),
        *(
            node.metadata["id"]
            for node in draft.nodes
            if node.kind == "bead" and "id" in node.metadata
        ),
    }
    agent_families = {
        *(_metadata_csv(draft.metadata.get("weak_agent_families"))),
        *(
            node.metadata["family"]
            for node in draft.nodes
            if node.kind == "agent_run" and node.metadata.get("family")
        ),
    }
    touched_paths = _metadata_csv(draft.metadata.get("weak_touched_paths"))
    metadata = {
        key: [value]
        for key, value in {
            "component_seed_reason": draft.metadata.get("component_seed_reason"),
            "component_strong_edge_count": draft.metadata.get(
                "component_strong_edge_count"
            ),
            "existing_episode_ids": draft.metadata.get("existing_episode_ids"),
        }.items()
        if value
    }
    return EpisodeWeakRefsWire(
        changespec_names=sorted(changespec_names),
        bead_ids=sorted(bead_ids),
        agent_families=sorted(agent_families),
        touched_paths=sorted(touched_paths),
        metadata=metadata,
    )


def derive_safety(draft: EpisodeDraft) -> EpisodeSafetyWire:
    source_texts = {
        source.id: text for source in draft.sources if (text := read_text(source))
    }
    phrase_hits = sorted(
        {
            phrase
            for text in source_texts.values()
            for phrase in _PROMPT_INJECTION_PHRASES
            if phrase in text.lower()
        }
    )
    redaction_hits = sorted(
        {
            name
            for text in source_texts.values()
            for name, pattern in _REDACTION_PATTERNS.items()
            if pattern.search(text)
        }
    )
    private_or_missing_flags = sorted(
        {
            *_missing_source_flags(draft.sources),
            *_private_source_flags(draft.sources),
        }
    )
    warnings = sorted(
        {
            *draft.warnings,
            *(f"prompt-injection:{phrase}" for phrase in phrase_hits),
            *(f"redaction:{hit}" for hit in redaction_hits),
            *private_or_missing_flags,
        }
    )
    return EpisodeSafetyWire(
        untrusted_transcript_text=any(
            source.kind == "chat" for source in draft.sources
        ),
        prompt_injection_phrase_hits=phrase_hits,
        redaction_hits=redaction_hits,
        private_or_missing_source_flags=private_or_missing_flags,
        warnings=warnings,
    )


def _metadata_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({item.strip() for item in value.split(",") if item.strip()})


def _missing_source_flags(
    sources: list[EpisodeSourceRefWire],
) -> list[str]:
    return [
        f"missing-source:{source.id}"
        for source in sorted(sources, key=lambda item: item.id)
        if not source.exists
    ]


def _private_source_flags(
    sources: list[EpisodeSourceRefWire],
) -> list[str]:
    flags: list[str] = []
    for source in sorted(sources, key=lambda item: item.id):
        data = read_json_object(source)
        if data.get("private") is True:
            flags.append(f"private-source:{source.id}")
        if data.get("hidden") is True:
            flags.append(f"hidden-source:{source.id}")
    return flags
