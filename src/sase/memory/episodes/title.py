"""Deterministic episode title and goal derivation."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.core.episode_wire import EpisodeSourceRefWire
from sase.memory.episodes.collector import EpisodeDraft

TITLE_MAX_CHARS = 88
GOAL_MAX_CHARS = 240

_PROMPT_LABELS = {"raw_xprompt.md", "submitted_xprompt.md"}
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


@dataclass(frozen=True)
class EpisodeGoal:
    """A source-grounded goal candidate for an episode."""

    text: str
    evidence_ids: list[str]


def derive_episode_title(draft: EpisodeDraft) -> str:
    """Return a stable, human-readable title for a collected episode draft."""

    goal = derive_episode_goal(draft)
    if goal.evidence_ids:
        return _title_from_text(goal.text)

    for node in sorted(draft.nodes, key=lambda item: (item.kind, item.id)):
        if node.kind == "changespec" and node.label:
            return _truncate_title(f"ChangeSpec {node.label}")
        if node.kind == "bead" and node.label:
            return _truncate_title(f"Bead {node.label}")
        if node.kind == "agent_run" and node.label:
            return _truncate_title(f"Agent {node.label}")

    root = next(
        (source for source in draft.sources if source.id == draft.root_source_id),
        None,
    )
    if root is not None:
        label = root.label or Path(root.path).name
        return _truncate_title(f"Episode from {label}")
    return "Deterministic Episode"


def derive_episode_goal(draft: EpisodeDraft) -> EpisodeGoal:
    """Return the earliest explicit prompt or plan goal in the draft."""

    prompt = _first_source_text(draft.sources, _is_prompt_source)
    if prompt is not None:
        source, text = prompt
        goal = _goal_from_text(text)
        if goal:
            return EpisodeGoal(goal, [source.id])

    plan = _first_source_text(draft.sources, lambda source: source.kind == "plan")
    if plan is not None:
        source, text = plan
        goal = _goal_from_text(text)
        if goal:
            return EpisodeGoal(goal, [source.id])

    for turn in sorted(draft.chat_turns, key=lambda item: item.id):
        if turn.prompt_excerpt:
            return EpisodeGoal(
                _truncate_goal(turn.prompt_excerpt), [turn.chat_source_id]
            )

    return EpisodeGoal("", [])


def _first_source_text(
    sources: list[EpisodeSourceRefWire],
    predicate: Callable[[EpisodeSourceRefWire], bool],
) -> tuple[EpisodeSourceRefWire, str] | None:
    for source in sorted(sources, key=lambda item: (item.path, item.id)):
        if not predicate(source):
            continue
        text = _read_bounded_text(source)
        if text:
            return source, text
    return None


def _is_prompt_source(source: EpisodeSourceRefWire) -> bool:
    label = source.label or Path(source.path).name
    return label in _PROMPT_LABELS or Path(source.path).name in _PROMPT_LABELS


def _read_bounded_text(source: EpisodeSourceRefWire) -> str | None:
    if not source.exists:
        return None
    path = Path(source.path)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")[:8192]
    except (OSError, UnicodeDecodeError):
        return None


def _goal_from_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            heading = _clean_line(match.group(1))
            if _useful_line(heading):
                return _truncate_goal(heading)

    paragraph: list[str] = []
    for line in lines:
        cleaned = _clean_line(line)
        if not cleaned:
            if paragraph:
                break
            continue
        if cleaned.lower() in {"prompt", "response", "summary", "goal"}:
            continue
        paragraph.append(cleaned)
        if len(" ".join(paragraph)) >= GOAL_MAX_CHARS:
            break
    return _truncate_goal(" ".join(paragraph)) if paragraph else ""


def _title_from_text(text: str) -> str:
    first_sentence = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    first_sentence = first_sentence.rstrip(".!?")
    return _truncate_title(first_sentence)


def _clean_line(line: str) -> str:
    cleaned = line.strip().strip("`")
    cleaned = _LIST_MARKER_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _useful_line(line: str) -> bool:
    if not line:
        return False
    return line.lower() not in {
        "chat history",
        "linked chats",
        "prompt",
        "response",
    }


def _truncate_goal(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= GOAL_MAX_CHARS:
        return collapsed
    return collapsed[: GOAL_MAX_CHARS - 3].rstrip() + "..."


def _truncate_title(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip() or "Deterministic Episode"
    if len(collapsed) <= TITLE_MAX_CHARS:
        return collapsed
    return collapsed[: TITLE_MAX_CHARS - 3].rstrip() + "..."


__all__ = [
    "EpisodeGoal",
    "derive_episode_goal",
    "derive_episode_title",
]
