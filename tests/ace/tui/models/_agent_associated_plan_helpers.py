"""Shared helpers for the ``test_agent_associated_plan*`` modules."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_associated_plan import (
    AssociatedPlanSummary,
    resolve_agent_plan_enrichment,
)
from sase.agent.bead_display import BeadIssueLookupSession


def write_plan(
    path: Path,
    goal: str,
    *,
    title: str | None = "Associated plan metadata",
    tier: str | None = "tale",
    size: str | None = "small",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tier_line = f"tier: {tier}\n" if tier is not None else ""
    title_line = f"title: {title!r}\n" if title is not None else ""
    size_line = f"size: {size}\n" if tier == "tale" and size is not None else ""
    path.write_text(
        f"---\n{tier_line}{title_line}goal: {goal!r}\n{size_line}---\n# Plan\n",
        encoding="utf-8",
    )
    return path


def write_epic(path: Path, goal: str = "Deliver every authored phase") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "tier: epic\n"
        "title: Epic phase metadata\n"
        f"goal: {goal!r}\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Canonical phase summaries\n"
        "    depends_on: []\n"
        "    description: Normalize the authoritative validator payload.\n"
        "    size: small\n"
        "  - id: docs\n"
        "    title: Independent documentation\n"
        "    depends_on: []\n"
        "    size: small\n"
        "  - id: render\n"
        "    title: Responsive roadmap\n"
        "    depends_on: [core, docs]\n"
        "    size: medium\n"
        "    model: codex/gpt-5.6-sol\n"
        "  - id: verify\n"
        "    title: End-to-end verification\n"
        "    depends_on: [render]\n"
        "    size: large\n"
        "---\n"
        "# Plan\n\n"
        "Implement it.\n",
        encoding="utf-8",
    )
    return path


def resolve_agent_associated_plan(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> AssociatedPlanSummary | None:
    """Return the associated-plan portion of role-aware enrichment."""
    return resolve_agent_plan_enrichment(
        agent,
        lookup_session=lookup_session,
    ).associated_plan
