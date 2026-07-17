"""Helpers for deriving bead display metadata from agent names."""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.model import BeadTier, IssueType

if TYPE_CHECKING:
    from sase.bead.model import Issue
    from sase.bead.project import BeadProject

_DISMISSED_AGENT_PREFIX_RE = re.compile(r"^\d{6}\.")
_TOP_LEVEL_BEAD_AGENT_NAME_RE = re.compile(r"^[^\s.]+-[0-9a-z]+$")
_BEAD_AGENT_NAME_RE = re.compile(r"^[^\s.]+-[0-9a-z]+(?:\.\d+)*$")


class BeadIssueLookupSession:
    """Reuse locally opened bead stores across a batch of issue lookups."""

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._projects: dict[Path, BeadProject | None] = {}

    def __enter__(self) -> BeadIssueLookupSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
        self._stack.close()

    def lookup(self, bead_id: str, beads_dirs: Iterable[Path]) -> Issue | None:
        """Return the first matching issue, opening each store at most once."""
        from sase.bead.project import BeadProject

        for beads_dir in beads_dirs:
            key = beads_dir.expanduser().resolve()
            if key not in self._projects:
                root, beads_dirname = _bead_project_location(beads_dir)
                try:
                    project = self._stack.enter_context(
                        BeadProject(root, beads_dirname=beads_dirname)
                    )
                except Exception:
                    project = None
                self._projects[key] = project

            project = self._projects[key]
            if project is None:
                continue
            try:
                return project.show(bead_id)
            except KeyError:
                continue
            except Exception:
                continue
        return None


def _normalized_agent_name(agent_name: str | None) -> str | None:
    if not agent_name:
        return None

    normalized = _DISMISSED_AGENT_PREFIX_RE.sub("", agent_name, count=1)
    if not normalized:
        return None
    family_base, separator, family_suffix = normalized.rpartition("--")
    if separator and family_base and family_suffix:
        return family_base
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


def lookup_bead_issue(
    bead_id: str,
    *,
    project_name: str | None = None,
    workspace_dir: str | None = None,
    local_only: bool = False,
    lookup_session: BeadIssueLookupSession | None = None,
) -> Issue | None:
    """Return the persisted issue for *bead_id*, if available."""
    if workspace_dir:
        try:
            issue = _lookup_bead_issue_from_workspace(
                bead_id,
                workspace_dir,
                lookup_session=lookup_session,
            )
            if issue is not None:
                return issue
        except Exception:
            pass

    if project_name:
        try:
            from sase.bead.workspace import get_project_beads_dirs_for_project

            beads_dirs = get_project_beads_dirs_for_project(project_name)
            issue = _lookup_bead_issue_in_dirs(
                bead_id,
                beads_dirs or [],
                lookup_session=lookup_session,
            )
            if issue is not None:
                return issue
        except Exception:
            pass

    if local_only:
        try:
            from sase.bead.cli_common import (
                resolve_beads_location,
                resolved_beads_location_is_usable,
            )

            location = resolve_beads_location(require_existing=True)
            if location is not None and resolved_beads_location_is_usable(location):
                issue = _lookup_bead_issue_in_dirs(
                    bead_id,
                    [location.beads_dir],
                    lookup_session=lookup_session,
                )
                if issue is not None:
                    return issue
        except Exception:
            pass
    else:
        try:
            from sase.bead.cli_common import get_read_view

            with get_read_view() as view:
                return view.show(bead_id)
        except Exception:
            pass

    try:
        from sase.bead.workspace import get_project_beads_dirs

        beads_dirs = get_project_beads_dirs()
        issue = _lookup_bead_issue_in_dirs(
            bead_id,
            beads_dirs or [],
            lookup_session=lookup_session,
        )
        if issue is not None:
            return issue
    except Exception:
        pass

    try:
        from sase.bead.workspace import get_all_project_beads_dirs

        beads_dirs = get_all_project_beads_dirs()
        issue = _lookup_bead_issue_in_dirs(
            bead_id,
            beads_dirs,
            lookup_session=lookup_session,
        )
        if issue is not None:
            return issue
    except Exception:
        pass

    return None


def _lookup_bead_issue_from_workspace(
    bead_id: str,
    workspace_dir: str,
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> Issue | None:
    local_dirs, primary_dirs = _workspace_beads_dir_candidates(workspace_dir)

    issue = _lookup_bead_issue_in_dirs(
        bead_id,
        local_dirs,
        lookup_session=lookup_session,
    )
    if issue is not None:
        return issue

    return _lookup_bead_issue_in_dirs(
        bead_id,
        primary_dirs,
        lookup_session=lookup_session,
    )


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
    bead_id: str,
    beads_dirs: Iterable[Path],
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> Issue | None:
    """Return the first matching issue from single-store bead paths."""
    from sase.bead.project import BeadProject

    if lookup_session is not None:
        return lookup_session.lookup(bead_id, beads_dirs)

    for beads_dir in beads_dirs:
        root, beads_dirname = _bead_project_location(beads_dir)
        try:
            with BeadProject(root, beads_dirname=beads_dirname) as project:
                return project.show(bead_id)
        except KeyError:
            continue
        except Exception:
            continue
    return None


def _bead_project_location(beads_dir: Path) -> tuple[Path, str]:
    """Return the ``BeadProject`` root and dirname for a bead-store path."""
    from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC

    parts = beads_dir.parts
    if len(parts) >= 2 and parts[-2:] == ("sdd", "beads"):
        return beads_dir.parents[1], BEADS_DIRNAME
    if len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"):
        return beads_dir.parent, BEADS_DIRNAME_NON_VC
    return beads_dir.parent, beads_dir.name


def normalize_bead_text(text: str | None) -> str | None:
    """Collapse bead text for display on a single metadata line."""
    if not text:
        return None
    normalized = " ".join(text.split())
    return normalized or None


def format_agent_bead_display_for_name(
    agent_name: str | None,
    *,
    include_description: bool = True,
    require_existing: bool = False,
    project_name: str | None = None,
    workspace_dir: str | None = None,
    local_only: bool = False,
    lookup_session: BeadIssueLookupSession | None = None,
) -> str | None:
    """Format the bead metadata value for an agent name.

    When *require_existing* is ``True``, the candidate bead id is looked up in
    the agent-context bead stores and ``None`` is returned unless a concrete
    issue is found. This is the strict "confirmed bead" path used by the TUI,
    which must not render bead metadata for names that merely look like bead
    ids. The default (``require_existing=False``) preserves the legacy
    fallback-to-id behavior that non-TUI callers (e.g. completion
    notifications) depend on. ``local_only=True`` prevents the fallback lookup
    from materializing or syncing an SDD store and is intended for passive TUI
    metadata reads.
    """
    bead_id = derive_agent_bead_id_from_name(agent_name)
    if not bead_id:
        return None

    issue: Issue | None = None
    if include_description or require_existing:
        issue = lookup_bead_issue(
            bead_id,
            project_name=project_name,
            workspace_dir=workspace_dir,
            local_only=local_only,
            lookup_session=lookup_session,
        )

    if require_existing and issue is None:
        return None

    if include_description and issue is not None:
        description = normalize_bead_text(getattr(issue, "description", None))
        if description:
            return f"{bead_id} - {description}"
        if _is_epic_land_issue(agent_name, issue):
            title = normalize_bead_text(getattr(issue, "title", None))
            if title:
                return f"{bead_id} - Land epic: {title}"
        title = normalize_bead_text(getattr(issue, "title", None))
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
