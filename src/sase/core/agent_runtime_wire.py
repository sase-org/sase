"""Wire records for Rust-backed clan/family runtime aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClanRuntimeMemberWire:
    """Runtime-relevant projection of one agent artifact record."""

    run_started_at: str | None = None
    stopped_at: str | None = None
    finished_at: float | None = None
    has_done_marker: bool = False
    terminal_is_synthesized: bool = False
    plan_submitted_at: list[str] = field(default_factory=list)
    feedback_submitted_at: list[str] = field(default_factory=list)
    plan_approved: bool = False
    questions_submitted_at: list[str] = field(default_factory=list)
    question_response_path: str | None = None
    pending_question_submitted_at: str | None = None


@dataclass(frozen=True)
class ClanRuntimeWire:
    """Wall-clock runtime for a clan or sequential family."""

    wall_clock_seconds: float = 0.0
    active: bool = False


__all__ = ["ClanRuntimeMemberWire", "ClanRuntimeWire"]
