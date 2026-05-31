"""Opt-in episodic-memory prompt augmentation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.memory.episodes.recall import EpisodeRecallMatch


@dataclass
class _EpisodeRecallPromptResult:
    """Result of opt-in episodic-memory prompt recall."""

    project: str
    query: str
    limit: int
    matches: list[EpisodeRecallMatch] = field(default_factory=list)


EPISODE_RECALL_ENABLED_ENV = "SASE_MEMORY_EPISODES_RECALL"
EPISODE_RECALL_LIMIT_ENV = "SASE_MEMORY_EPISODES_RECALL_LIMIT"
EPISODE_RECALL_DEFAULT_LIMIT = 3


def episode_recall_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether opt-in episodic-memory recall should augment prompts."""

    source = os.environ if env is None else env
    value = source.get(EPISODE_RECALL_ENABLED_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def episode_recall_limit(env: Mapping[str, str] | None = None) -> int:
    """Return the configured prompt recall limit with a deterministic default."""

    source = os.environ if env is None else env
    raw = source.get(EPISODE_RECALL_LIMIT_ENV, "")
    try:
        limit = int(raw)
    except ValueError:
        return EPISODE_RECALL_DEFAULT_LIMIT
    if limit < 1:
        return EPISODE_RECALL_DEFAULT_LIMIT
    return limit


def generate_episode_recall_prompt(
    prompt: str,
    project: str,
    *,
    limit: int = EPISODE_RECALL_DEFAULT_LIMIT,
    projects_root: Path | str | None = None,
) -> _EpisodeRecallPromptResult:
    """Recall stored episode evidence for prompt augmentation."""

    from sase.memory.episodes.index import read_episode_index
    from sase.memory.episodes.recall import recall_episode_rows

    try:
        matches = recall_episode_rows(
            read_episode_index(project, projects_root=projects_root),
            prompt,
            projects_root=projects_root,
            limit=limit,
        )
    except ValueError:
        matches = []
    return _EpisodeRecallPromptResult(
        project=project,
        query=prompt,
        limit=limit,
        matches=matches,
    )


def format_episode_recall_section(result: _EpisodeRecallPromptResult) -> str:
    """Format recalled episode cards for prompt injection."""

    lines = ["### EPISODIC MEMORY"]
    for match in result.matches:
        lines.append(f"- Episode `{match.episode_id}` ({match.title})")
        if not match.lessons and match.evidence_cards:
            for card in match.evidence_cards:
                evidence = ", ".join(
                    f"`{item.source_id}` {item.path}".rstrip() for item in card.evidence
                )
                suffix = f" [evidence: {evidence}]" if evidence else ""
                lines.append(f"  - {card.title}: {card.text}{suffix}")
            continue
        if not match.lessons and match.excerpt:
            lines.append(f"  - {match.excerpt}")
            continue
        for lesson in match.lessons:
            evidence = ", ".join(
                f"`{item.source_id}` {item.path}".rstrip() for item in lesson.evidence
            )
            suffix = f" [evidence: {evidence}]" if evidence else ""
            lines.append(f"  - {lesson.text}{suffix}")
    return "\n".join(lines)
