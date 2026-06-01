"""Helpers for deriving bead display metadata from agent names."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.model import BeadTier, IssueType

if TYPE_CHECKING:
    from sase.bead.model import Issue

_DISMISSED_AGENT_PREFIX_RE = re.compile(r"^\d{6}\.")
_TOP_LEVEL_BEAD_AGENT_NAME_RE = re.compile(r"^[^\s.]+-[0-9a-z]+$")
_BEAD_AGENT_NAME_RE = re.compile(r"^[^\s.]+-[0-9a-z]+(?:\.\d+)*$")


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


def _is_bead_agent_name(normalized_agent_name: str | None) -> bool:
    if not normalized_agent_name:
        return False
    return bool(_BEAD_AGENT_NAME_RE.match(normalized_agent_name))


def derive_agent_bead_id_from_name(agent_name: str | None) -> str | None:
    """Infer a bead id from an agent name written by ``sase bead work``."""
    normalized = _normalized_agent_name(agent_name)
    if not normalized:
        return None

    if _is_land_agent_name(normalized):
        epic_id = normalized.removesuffix(".land")
        return epic_id if _is_bead_agent_name(epic_id) else None

    if _is_bead_agent_name(normalized):
        return normalized

    return None


def _lookup_bead_issue(
    bead_id: str,
    *,
    project_name: str | None = None,
    workspace_dir: str | None = None,
) -> Issue | None:
    """Return the persisted issue for *bead_id*, if available."""
    if workspace_dir:
        try:
            issue = _lookup_bead_issue_from_workspace(bead_id, workspace_dir)
            if issue is not None:
                return issue
        except Exception:
            pass

    if project_name:
        try:
            from sase.bead.workspace import get_project_beads_dirs_for_project

            beads_dirs = get_project_beads_dirs_for_project(project_name)
            issue = _lookup_bead_issue_in_dirs(bead_id, beads_dirs or [])
            if issue is not None:
                return issue
        except Exception:
            pass

    try:
        from sase.bead.cli_common import get_read_view

        with get_read_view() as view:
            return view.show(bead_id)
    except Exception:
        pass

    try:
        from sase.bead.workspace import get_project_beads_dirs

        beads_dirs = get_project_beads_dirs()
        issue = _lookup_bead_issue_in_dirs(bead_id, beads_dirs or [])
        if issue is not None:
            return issue
    except Exception:
        pass

    try:
        from sase.bead.workspace import get_all_project_beads_dirs

        beads_dirs = get_all_project_beads_dirs()
        issue = _lookup_bead_issue_in_dirs(bead_id, beads_dirs)
        if issue is not None:
            return issue
    except Exception:
        pass

    return None


def _lookup_bead_issue_from_workspace(bead_id: str, workspace_dir: str) -> Issue | None:
    local_dirs, primary_dirs = _workspace_beads_dir_candidates(workspace_dir)

    issue = _lookup_bead_issue_in_dirs(bead_id, local_dirs)
    if issue is not None:
        return issue

    return _lookup_bead_issue_in_dirs(bead_id, primary_dirs)


def _workspace_beads_dir_candidates(
    workspace_dir: str,
) -> tuple[list[Path], list[Path]]:
    """Return local and marker-primary bead stores for an agent workspace."""
    workspace = Path(workspace_dir).expanduser().resolve(strict=False)
    local_dirs = _beads_dirs_for_workspace_tree(workspace)
    primary_dirs: list[Path] = []

    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(workspace))
    except Exception:
        found = None
    if found is not None:
        _, marker = found
        primary_str = marker.primary_workspace_dir.strip()
        if primary_str:
            primary = Path(primary_str).expanduser().resolve(strict=False)
            if primary.is_dir():
                primary_dirs = _beads_dirs_for_workspace_tree(primary)

    return local_dirs, _dedupe_paths(primary_dirs)


def _beads_dirs_for_workspace_tree(workspace: Path) -> list[Path]:
    from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC

    candidates: list[Path] = []
    for parent in [workspace, *workspace.parents]:
        vc_beads = parent / BEADS_DIRNAME
        if vc_beads.is_dir():
            candidates.append(vc_beads)
        non_vc_beads = parent / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
        if non_vc_beads.is_dir():
            candidates.append(non_vc_beads)
    return _dedupe_paths(candidates)


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _lookup_bead_issue_in_dirs(
    bead_id: str, beads_dirs: Iterable[Path]
) -> Issue | None:
    """Return the first matching issue from single-store bead paths."""
    from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC, BeadProject

    for beads_dir in beads_dirs:
        parts = beads_dir.parts
        if len(parts) >= 2 and parts[-2:] == ("sdd", "beads"):
            root = beads_dir.parents[1]
            beads_dirname = BEADS_DIRNAME
        elif len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"):
            root = beads_dir.parent
            beads_dirname = BEADS_DIRNAME_NON_VC
        else:
            root = beads_dir.parent
            beads_dirname = beads_dir.name
        try:
            with BeadProject(root, beads_dirname=beads_dirname) as project:
                return project.show(bead_id)
        except KeyError:
            continue
        except Exception:
            continue
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
    workspace_dir: str | None = None,
) -> str | None:
    """Format the bead metadata value for an agent name."""
    bead_id = derive_agent_bead_id_from_name(agent_name)
    if not bead_id:
        return None

    if include_description:
        issue = _lookup_bead_issue(
            bead_id,
            project_name=project_name,
            workspace_dir=workspace_dir,
        )
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
