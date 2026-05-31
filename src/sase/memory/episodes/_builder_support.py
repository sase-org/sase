"""Shared helpers for deterministic episode building."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sase.core.episode_wire import EpisodeEventWire, EpisodeSourceRefWire

_HOUSEKEEPING_LABELS = {
    "agent_meta.json",
    "done.json",
    "memory_reads.jsonl",
    "plan_feedback.jsonl",
    "qa_log.jsonl",
    "raw_xprompt.md",
    "submitted_xprompt.md",
}


def recorded_outcomes(
    sources: list[EpisodeSourceRefWire],
) -> list[tuple[str, str]]:
    outcomes: list[tuple[str, str]] = []
    for source in sources_matching(sources, is_done_source):
        data = read_json_object(source)
        outcome = str_value(data.get("outcome"))
        if not outcome:
            continue
        name = str_value(data.get("name")) or Path(source.path).parent.name
        outcomes.append((name, outcome))
    return sorted(outcomes)


def event(
    kind: str,
    key: str,
    title: str,
    *,
    timestamp: str | None = None,
    description: str | None = None,
    evidence_ids: Iterable[str] = (),
) -> EpisodeEventWire:
    return EpisodeEventWire(
        id=stable_id("event", kind, key),
        kind=kind,
        title=title,
        timestamp=timestamp,
        description=description,
        evidence_ids=sorted({item for item in evidence_ids if item}),
    )


def sources_matching(
    sources: list[EpisodeSourceRefWire],
    predicate: Callable[[EpisodeSourceRefWire], bool],
) -> list[EpisodeSourceRefWire]:
    return [
        source
        for source in sorted(sources, key=lambda item: (item.path, item.id))
        if predicate(source)
    ]


def is_agent_meta_source(source: EpisodeSourceRefWire) -> bool:
    return Path(source.path).name == "agent_meta.json"


def is_done_source(source: EpisodeSourceRefWire) -> bool:
    return Path(source.path).name == "done.json"


def is_feedback_source(source: EpisodeSourceRefWire) -> bool:
    return source.kind == "feedback" or Path(source.path).name == "plan_feedback.jsonl"


def is_question_source(source: EpisodeSourceRefWire) -> bool:
    return source.kind == "question" or Path(source.path).name == "qa_log.jsonl"


def is_memory_source(source: EpisodeSourceRefWire) -> bool:
    return (
        source.kind == "memory_read" or Path(source.path).name == "memory_reads.jsonl"
    )


def is_verification_text_source(source: EpisodeSourceRefWire) -> bool:
    if not source.exists:
        return False
    return source.kind in {"artifact", "chat"} or Path(source.path).name in {
        "done.json",
        "output.txt",
        "response.md",
    }


def is_housekeeping_source(source: EpisodeSourceRefWire) -> bool:
    return Path(source.path).name in _HOUSEKEEPING_LABELS


def source_label(source: EpisodeSourceRefWire) -> str:
    return source.label or Path(source.path).name or source.path


def read_json_object(source: EpisodeSourceRefWire) -> dict[str, Any]:
    text = read_text(source)
    if text is None:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_text(source: EpisodeSourceRefWire) -> str | None:
    if not source.exists:
        return None
    path = Path(source.path)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")[:131072]
    except (OSError, UnicodeDecodeError):
        return None


def str_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def join_limited(values: Iterable[str], *, limit: int = 6) -> str:
    cleaned = [collapse(value).strip("`") for value in values if collapse(value)]
    head = cleaned[:limit]
    rendered = ", ".join(f"`{value}`" for value in head)
    if len(cleaned) > limit:
        rendered += f", and {len(cleaned) - limit} more"
    return rendered


def truncate(text: str, limit: int = 180) -> str:
    collapsed = collapse(text)
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def stable_id(prefix: str, *parts: str) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"
