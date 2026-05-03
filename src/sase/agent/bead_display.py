"""Helpers for deriving bead display metadata from agent names."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sase.bead.model import BeadTier, IssueType

if TYPE_CHECKING:
    from sase.bead.model import Issue

_DISMISSED_AGENT_PREFIX_RE = re.compile(r"^\d{6}\.")
_PHASE_BEAD_AGENT_NAME_RE = re.compile(r"^.+\.\d+$")
_TOP_LEVEL_BEAD_AGENT_NAME_RE = re.compile(r"^[^\s.]+-[0-9a-z]+$")


def _normalized_agent_name(agent_name: str | None) -> str | None:
    if not agent_name:
        return None

    normalized = _DISMISSED_AGENT_PREFIX_RE.sub("", agent_name, count=1)
    if not normalized:
        return None
    return normalized


def _is_land_agent_name(normalized_agent_name: str | None) -> bool:
    if not normalized_agent_name:
        return False
    return normalized_agent_name.endswith(".land") and bool(
        normalized_agent_name.removesuffix(".land")
    )


def _is_top_level_bead_agent_name(normalized_agent_name: str | None) -> bool:
    if not normalized_agent_name:
        return False
    return bool(_TOP_LEVEL_BEAD_AGENT_NAME_RE.match(normalized_agent_name))


def derive_agent_bead_id_from_name(agent_name: str | None) -> str | None:
    """Infer a bead id from an agent name written by ``sase bead work``."""
    normalized = _normalized_agent_name(agent_name)
    if not normalized:
        return None

    if _is_land_agent_name(normalized):
        epic_id = normalized.removesuffix(".land")
        return epic_id or None

    if _PHASE_BEAD_AGENT_NAME_RE.match(normalized):
        return normalized

    if _is_top_level_bead_agent_name(normalized):
        return normalized

    return None


def _lookup_bead_issue(
    bead_id: str, *, project_name: str | None = None
) -> Issue | None:
    """Return the persisted issue for *bead_id*, if available."""
    if project_name:
        try:
            from sase.bead.workspace import (
                MergedBeadView,
                get_project_beads_dirs_for_project,
            )

            beads_dirs = get_project_beads_dirs_for_project(project_name)
            if beads_dirs:
                with MergedBeadView(beads_dirs) as view:
                    return view.show(bead_id)
        except Exception:
            pass

    try:
        from sase.bead.cli_common import get_read_view

        with get_read_view() as view:
            return view.show(bead_id)
    except Exception:
        pass

    try:
        from sase.bead.workspace import MergedBeadView, get_all_project_beads_dirs

        beads_dirs = get_all_project_beads_dirs()
        if beads_dirs:
            with MergedBeadView(beads_dirs) as view:
                return view.show(bead_id)
    except Exception:
        pass

    return None


def _normalize_bead_text(text: str | None) -> str | None:
    """Collapse bead text for display on a single metadata line."""
    if not text:
        return None
    normalized = " ".join(text.split())
    return normalized or None


def format_agent_bead_display_for_name(
    agent_name: str | None,
    *,
    include_description: bool = True,
    project_name: str | None = None,
) -> str | None:
    """Format the bead metadata value for an agent name."""
    bead_id = derive_agent_bead_id_from_name(agent_name)
    if not bead_id:
        return None

    if include_description:
        issue = _lookup_bead_issue(bead_id, project_name=project_name)
        description = _normalize_bead_text(getattr(issue, "description", None))
        if description:
            return f"{bead_id} - {description}"
        if issue is not None and _is_epic_land_issue(agent_name, issue):
            title = _normalize_bead_text(getattr(issue, "title", None))
            if title:
                return f"{bead_id} - Land epic: {title}"
        title = _normalize_bead_text(getattr(issue, "title", None))
        if title:
            return f"{bead_id} - {title}"

    return bead_id


def _is_epic_land_issue(agent_name: str | None, issue: Issue) -> bool:
    normalized = _normalized_agent_name(agent_name)
    if _is_land_agent_name(normalized):
        return True

    return (
        _is_top_level_bead_agent_name(normalized)
        and getattr(issue, "issue_type", None) == IssueType.PLAN
        and getattr(issue, "tier", None) == BeadTier.EPIC
    )
