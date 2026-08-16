"""Surface-neutral agent-family plan/bead preview value and formatters.

Both the ACE TUI prompt-input completion menu and the external-editor agent
catalog render the same "preview ladder" for a family completion entry: an
authored plan's tier and title, a bead's type and title, or nothing. This
module holds the shared value type and text formatters so the wording cannot
drift between surfaces; it intentionally has no ACE TUI model imports so the
editor helper (a separate process) can use it too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from sase.bead_type_presentation import BEAD_TYPE_PRESENTATIONS
from sase.phase_size_presentation import PhaseSizeValue
from sase.plan_tier_presentation import (
    GENERIC_PLAN_ACCENT,
    GENERIC_PLAN_LABEL,
    PLAN_TIER_PRESENTATIONS,
)
from sase.sdd.plan_display import PlanDisplay, PlanDisplayTier
from sase.sdd.plan_waves import plan_phase_waves

AgentFamilyPlanPreviewKind = Literal["tale", "epic", "plan", "phase", "task"]

#: Phase details beyond this count are dropped from both the row subtitle and
#: the editor documentation block; ``phase_count``/``wave_count`` still carry
#: the true totals.
_MAX_PREVIEW_PHASES: Final = 6
_GOAL_CLIP_LENGTH: Final = 240


@dataclass(frozen=True, slots=True)
class AgentFamilyPlanPreview:
    """One resolved preview rung for a family's completion row/detail."""

    kind: AgentFamilyPlanPreviewKind | None
    title: str | None
    goal: str | None
    parent_title: str | None
    phase_count: int | None
    wave_count: int | None
    phase_titles: tuple[str, ...]
    phase_ids: tuple[str, ...]
    phase_sizes: tuple[PhaseSizeValue, ...]
    size: PhaseSizeValue | None
    description: str | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether nothing at all resolved (render the prompt rung)."""
        return self.kind is None


#: Singleton for "resolved, nothing to show" — distinct from an unresolved
#: cache miss, which callers must track separately (see
#: ``agent_family_preview_cache``).
EMPTY_AGENT_FAMILY_PLAN_PREVIEW: Final = AgentFamilyPlanPreview(
    kind=None,
    title=None,
    goal=None,
    parent_title=None,
    phase_count=None,
    wave_count=None,
    phase_titles=(),
    phase_ids=(),
    phase_sizes=(),
    size=None,
    description=None,
)

_PLAN_TIER_KINDS: dict[PlanDisplayTier, AgentFamilyPlanPreviewKind] = {
    "tale": "tale",
    "epic": "epic",
    "plan": "plan",
}

_LABELS: dict[AgentFamilyPlanPreviewKind, str] = {
    "tale": PLAN_TIER_PRESENTATIONS["tale"].label,
    "epic": PLAN_TIER_PRESENTATIONS["epic"].label,
    "plan": GENERIC_PLAN_LABEL,
    "phase": BEAD_TYPE_PRESENTATIONS["phase"].label,
    "task": BEAD_TYPE_PRESENTATIONS["task"].label,
}

_ACCENTS: dict[AgentFamilyPlanPreviewKind, str] = {
    "tale": PLAN_TIER_PRESENTATIONS["tale"].accent_color,
    "epic": PLAN_TIER_PRESENTATIONS["epic"].accent_color,
    "plan": GENERIC_PLAN_ACCENT,
    "phase": BEAD_TYPE_PRESENTATIONS["phase"].accent_color,
    "task": BEAD_TYPE_PRESENTATIONS["task"].accent_color,
}


def agent_family_plan_preview_label(kind: AgentFamilyPlanPreviewKind) -> str:
    """Return the cross-surface chip word for *kind* (``"Epic"``, ...)."""
    return _LABELS[kind]


def agent_family_plan_preview_accent(kind: AgentFamilyPlanPreviewKind) -> str:
    """Return the cross-surface accent hex color for *kind*."""
    return _ACCENTS[kind]


def agent_family_plan_preview_from_plan(plan: PlanDisplay) -> AgentFamilyPlanPreview:
    """Project one resolved ``PlanDisplay`` into a family preview.

    Returns :data:`EMPTY_AGENT_FAMILY_PLAN_PREVIEW` when even the tier is
    unknown; a known tier with a missing title still yields a preview so the
    caller can render the chip and fall back to a prompt snippet in its
    place.
    """
    kind = _PLAN_TIER_KINDS.get(plan.effective_tier) if plan.effective_tier else None
    if kind is None:
        return EMPTY_AGENT_FAMILY_PLAN_PREVIEW

    phase_count: int | None = None
    wave_count: int | None = None
    phase_titles: tuple[str, ...] = ()
    phase_ids: tuple[str, ...] = ()
    phase_sizes: tuple[PhaseSizeValue, ...] = ()
    if plan.phase_availability == "available":
        phase_count = len(plan.phases)
        waves = plan_phase_waves(plan.phases)
        wave_count = len(waves) if waves is not None else None
        bounded = plan.phases[:_MAX_PREVIEW_PHASES]
        phase_titles = tuple(phase.title for phase in bounded)
        phase_ids = tuple(phase.id for phase in bounded)
        phase_sizes = tuple(phase.size for phase in bounded)

    return AgentFamilyPlanPreview(
        kind=kind,
        title=plan.title,
        goal=plan.goal,
        parent_title=None,
        phase_count=phase_count,
        wave_count=wave_count,
        phase_titles=phase_titles,
        phase_ids=phase_ids,
        phase_sizes=phase_sizes,
        size=plan.size,
        description=None,
    )


def agent_family_plan_preview_from_bead(
    *,
    bead_type: Literal["phase", "task"],
    title: str | None,
    parent_title: str | None,
    size: PhaseSizeValue | None,
    description: str | None = None,
) -> AgentFamilyPlanPreview:
    """Project one resolved phase/task bead identity into a family preview."""
    if not title:
        return EMPTY_AGENT_FAMILY_PLAN_PREVIEW
    return AgentFamilyPlanPreview(
        kind=bead_type,
        title=title,
        goal=None,
        parent_title=parent_title,
        phase_count=None,
        wave_count=None,
        phase_titles=(),
        phase_ids=(),
        phase_sizes=(),
        size=size,
        description=description,
    )


def agent_family_plan_structure_text(
    preview: AgentFamilyPlanPreview,
    *,
    compact: bool,
) -> str:
    """Return the phase/wave structure fragment, or ``""`` when unknown."""
    if preview.phase_count is None:
        return ""
    if compact:
        return f"{preview.phase_count}ph"
    phase_word = "phase" if preview.phase_count == 1 else "phases"
    if preview.wave_count is None:
        return f"{preview.phase_count} {phase_word}"
    wave_word = "wave" if preview.wave_count == 1 else "waves"
    return f"{preview.phase_count} {phase_word} · {preview.wave_count} {wave_word}"


def agent_family_plan_preview_detail(
    preview: AgentFamilyPlanPreview,
    *,
    fallback_title: str = "",
) -> str:
    """Return the one-line editor completion-item detail for *preview*.

    ``fallback_title`` substitutes for a chip with a known kind but no
    title (a plan file that is missing, unreadable, or untitled). Returns
    ``""`` when nothing usable resolved, leaving the caller's own fallback
    (a raw prompt snippet, or a plain member-count detail) in place.
    """
    if preview.kind is None:
        return ""
    title = preview.title or fallback_title
    if not title:
        return ""
    segments: list[str] = [preview.kind]
    structure = agent_family_plan_structure_text(preview, compact=False)
    if structure:
        segments.append(structure)
    segments.append(title)
    return " · ".join(segments)


def _clip_goal(goal: str) -> str:
    if len(goal) <= _GOAL_CLIP_LENGTH:
        return goal
    return goal[: _GOAL_CLIP_LENGTH - 1].rstrip() + "…"


def agent_family_plan_preview_documentation(
    preview: AgentFamilyPlanPreview,
    *,
    fallback_title: str = "",
) -> str:
    """Return the markdown documentation block for *preview*.

    Bounded to the same ``_MAX_PREVIEW_PHASES`` phases already carried by
    *preview* and a clipped goal, so a caller can pass this straight through
    to an editor's documentation popup. Returns ``""`` under the same
    conditions as :func:`agent_family_plan_preview_detail`.
    """
    if preview.kind is None:
        return ""
    title = preview.title or fallback_title
    if not title:
        return ""

    label = agent_family_plan_preview_label(preview.kind)
    structure = agent_family_plan_structure_text(preview, compact=False)
    header = f"**{label}**" + (f" · {structure}" if structure else "")
    lines = [header, "", f"## {title}"]
    if preview.goal:
        lines.extend(["", _clip_goal(preview.goal)])
    if preview.parent_title:
        lines.extend(["", f"_Part of {preview.parent_title}_"])
    if preview.phase_titles:
        lines.append("")
        lines.extend(
            f"- `{phase_id}` — {phase_title} ({phase_size})"
            for phase_id, phase_title, phase_size in zip(
                preview.phase_ids,
                preview.phase_titles,
                preview.phase_sizes,
                strict=True,
            )
        )
    return "\n".join(lines)


__all__ = [
    "AgentFamilyPlanPreview",
    "AgentFamilyPlanPreviewKind",
    "EMPTY_AGENT_FAMILY_PLAN_PREVIEW",
    "agent_family_plan_preview_accent",
    "agent_family_plan_preview_detail",
    "agent_family_plan_preview_documentation",
    "agent_family_plan_preview_from_bead",
    "agent_family_plan_preview_from_plan",
    "agent_family_plan_preview_label",
    "agent_family_plan_structure_text",
]
