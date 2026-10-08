"""DECISIONS section for bead detail views (sase-1hi.4 handoff).

Epic and phase beads show the design plan's Plan Decisions, read from the
design plan file in Launch mode: pending sheets render asks and defaults,
accepted sheets render answers. Anything unresolvable (no design plan, no
``decisions:`` map, invalid file) yields no section, never an error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.model import BeadTier, IssueType
from sase.sdd.plan_decision_handoff import StampedDecisions, load_stamped_decisions

_EPIC_PHASE_AUDIENCE = "epic_phase"
_EPIC_LAND_AUDIENCE = "epic_land"


def _decisions_audience(issue: Any) -> str | None:
    """Return the decision audience lens for a bead, else ``None``.

    Phase beads read through the ``epic_phase`` lens; the epic bead itself
    reads through ``epic_land``. Every other bead kind carries no lens.
    """
    if getattr(issue, "issue_type", None) == IssueType.PHASE:
        return _EPIC_PHASE_AUDIENCE
    if (
        getattr(issue, "issue_type", None) == IssueType.PLAN
        and getattr(issue, "tier", None) == BeadTier.EPIC
    ):
        return _EPIC_LAND_AUDIENCE
    return None


def _resolve_design_file(
    plan_path: str,
    *,
    plan_roots: tuple[Path, ...] = (),
    design_cwd: Path | None = None,
) -> Path | None:
    """Resolve a bead design-plan reference to an existing file, else ``None``."""
    candidate = Path(plan_path).expanduser()
    if candidate.is_file():
        return candidate
    roots: list[Path] = []
    if design_cwd is not None:
        roots.append(Path(design_cwd))
    roots.extend(plan_roots)
    for root in roots:
        resolved = (root / candidate).expanduser()
        if resolved.is_file():
            return resolved
    return None


def _stamped_wire(stamped: StampedDecisions, *, audience: str) -> dict[str, Any]:
    """Project one loaded plan's decisions into the bead detail wire."""
    return {
        "title": stamped.title,
        "tier": stamped.tier,
        "decided_by": stamped.decided_by,
        "decided_via": stamped.decided_via,
        "sheet": stamped.sheet,
        "audience": audience,
    }


def decisions_wire_for_detail(
    detail: Any,
    *,
    plan_roots: tuple[Path, ...] = (),
    design_cwd: Path | None = None,
) -> dict[str, Any] | None:
    """Return the DECISIONS wire for a resolved bead detail, else ``None``."""
    issue = getattr(detail, "issue", None)
    plan = getattr(detail, "plan", None)
    if issue is None or plan is None:
        return None
    audience = _decisions_audience(issue)
    if audience is None:
        return None
    plan_file = _resolve_design_file(
        str(getattr(plan, "path", "")),
        plan_roots=plan_roots,
        design_cwd=design_cwd,
    )
    if plan_file is None:
        return None
    tier = "epic" if audience == _EPIC_LAND_AUDIENCE else "tale"
    try:
        stamped = load_stamped_decisions(plan_file, tier)
    except Exception:
        return None
    if stamped is None:
        return None
    return _stamped_wire(stamped, audience=audience)


def render_decisions_content_lines(wire: dict[str, Any]) -> list[str]:
    """Render the DECISIONS body lines (without the section header)."""
    try:
        from sase.sdd._plan_display_decisions import (
            accepted_decisions_text,
            decision_text_lines,
            pending_decisions_text,
        )
    except Exception:
        return []
    sheet = wire.get("sheet")
    if not isinstance(sheet, dict):
        return []
    via = wire.get("decided_via")
    if wire.get("decided_by") is not None:
        text = accepted_decisions_text(
            sheet,
            str(wire.get("decided_by") or ""),
            via if isinstance(via, str) else None,
        )
    else:
        text = pending_decisions_text(sheet)
    return [f"  {line}" for line in decision_text_lines(text)]


__all__ = [
    "decisions_wire_for_detail",
    "render_decisions_content_lines",
]
