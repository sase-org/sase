"""Authoritative record of the epic beads a run launched.

When ``sase bead work`` materializes an epic-tier plan bead, the creating
run appends a ``created_epics`` entry to its own ``agent_meta.json`` under a
lock. Readers prefer that list and only fall back to the legacy
``epic_bead_id`` back-fill for non-worker rows; bead-store attribution
covers runs whose record write was lost.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

#: Marker field holding the authoritative run → epic record.
CREATED_EPICS_FIELD = "created_epics"

#: ``via`` value for an explicit ``--artifacts-dir`` launch.
HOST_LAUNCH_VIA = "host_launch"

#: ``via`` value for a run's own ``sase bead work`` call.
AGENT_COMMAND_VIA = "agent_command"

_CREATED_EPIC_VIAS = frozenset({HOST_LAUNCH_VIA, AGENT_COMMAND_VIA})

_ARTIFACTS_DIR_ENV = "SASE_ARTIFACTS_DIR"
_META_FILE_NAME = "agent_meta.json"
_MAX_CREATED_EPICS = 64


@dataclass(frozen=True)
class CreatedEpic:
    """One epic-tier plan bead materialized on a run's behalf."""

    bead_id: str
    project: str | None = None
    plan_ref: str | None = None
    created_at: str = ""
    via: str = HOST_LAUNCH_VIA


def _nonempty_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def coerce_created_epics(value: object) -> list[CreatedEpic]:
    """Coerce a raw ``created_epics`` value leniently; never raises."""
    if not isinstance(value, list):
        return []
    entries: list[CreatedEpic] = []
    for item in value:
        if isinstance(item, str):
            bead_id = _nonempty_str(item)
            if bead_id is not None:
                entries.append(CreatedEpic(bead_id=bead_id))
            continue
        if isinstance(item, CreatedEpic):
            if _nonempty_str(item.bead_id) is not None:
                entries.append(item)
            continue
        if not isinstance(item, dict):
            continue
        bead_id = _nonempty_str(item.get("bead_id"))
        if bead_id is None:
            continue
        raw_via = item.get("via")
        via = (
            raw_via
            if isinstance(raw_via, str) and raw_via in _CREATED_EPIC_VIAS
            else HOST_LAUNCH_VIA
        )
        entries.append(
            CreatedEpic(
                bead_id=bead_id,
                project=_nonempty_str(item.get("project")),
                plan_ref=_nonempty_str(item.get("plan_ref")),
                created_at=_nonempty_str(item.get("created_at")) or "",
                via=via,
            )
        )
        if len(entries) >= _MAX_CREATED_EPICS:
            break
    return entries


def _field(source: object, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def created_epic_ids_from_meta(source: object) -> list[str]:
    """Return the epics *source* launched, oldest first.

    Prefers the authoritative ``created_epics`` list. Only when it is
    empty, and only for non-worker rows (no ``phase_bead_id`` or
    ``epic_plan_ref``), it falls back to the legacy ``epic_bead_id``
    back-fill. Worker rows never inherit the fallback: their
    ``epic_bead_id`` names the epic they belong to, not one they launched.
    """
    ids = [
        entry.bead_id
        for entry in coerce_created_epics(_field(source, CREATED_EPICS_FIELD))
    ]
    if ids:
        return ids
    if _nonempty_str(_field(source, "phase_bead_id")) is not None:
        return []
    if _nonempty_str(_field(source, "epic_plan_ref")) is not None:
        return []
    legacy = _nonempty_str(_field(source, "epic_bead_id"))
    return [legacy] if legacy is not None else []


def launched_epic_bead_id(source: object) -> str | None:
    """Return the first epic *source* launched, if any."""
    ids = created_epic_ids_from_meta(source)
    return ids[0] if ids else None


def resolve_creator_artifacts_dir(
    explicit_dir: str | Path | None,
) -> tuple[Path | None, str | None]:
    """Return the run directory to record a created epic on, plus its ``via``.

    An explicit ``--artifacts-dir`` wins (``host_launch``). Otherwise
    ``$SASE_ARTIFACTS_DIR`` is used only when it names a directory holding
    an ``agent_meta.json`` (``agent_command``). Anything else gives
    ``(None, None)``: recording is skipped, never forced.
    """
    if explicit_dir is not None:
        candidate = Path(explicit_dir).expanduser()
        if candidate.is_dir():
            return candidate, HOST_LAUNCH_VIA
        return None, None
    env = os.environ.get(_ARTIFACTS_DIR_ENV, "").strip()
    if env:
        candidate = Path(env).expanduser()
        if candidate.is_dir() and (candidate / _META_FILE_NAME).is_file():
            return candidate, AGENT_COMMAND_VIA
    return None, None


def record_created_epic(
    creator_dir: str | Path | None,
    *,
    bead_id: str,
    project: str | None = None,
    plan_ref: str | None = None,
    via: str = HOST_LAUNCH_VIA,
) -> CreatedEpic | None:
    """Append one ``created_epics`` entry to the creating run's marker.

    Deduplicates by ``bead_id`` so repeat launches and resumes are
    idempotent. A failed write is logged and returns ``None``; it never
    fails the launch.
    """
    if creator_dir is None:
        return None
    clean_bead_id = _nonempty_str(bead_id)
    if clean_bead_id is None:
        return None
    entry = CreatedEpic(
        bead_id=clean_bead_id,
        project=_nonempty_str(project),
        plan_ref=_nonempty_str(plan_ref),
        created_at=datetime.now(UTC).isoformat(),
        via=via if via in _CREATED_EPIC_VIAS else HOST_LAUNCH_VIA,
    )

    def _append(meta: dict[str, Any]) -> bool:
        entries = coerce_created_epics(meta.get(CREATED_EPICS_FIELD))
        if any(existing.bead_id == entry.bead_id for existing in entries):
            return True
        entries.append(entry)
        meta[CREATED_EPICS_FIELD] = [asdict(existing) for existing in entries]
        return True

    try:
        from sase.core.agent_meta_update import update_agent_meta_locked

        update_agent_meta_locked(creator_dir, _append)
    except Exception as exc:
        _logger.warning(
            "could not record created epic %s on %s: %s",
            entry.bead_id,
            creator_dir,
            exc,
        )
        return None
    return entry


def attributed_epic_ids(
    project: str,
    *,
    creator_global_name: str,
    plan_ref: str | None = None,
    plan_basename: str | None = None,
) -> list[str]:
    """Return epic-tier plan beads attributed to *creator_global_name*.

    Matches beads whose ``created_by`` equals the creator and whose
    ``design`` names the run's plan (exact ``plan_ref`` or basename match).
    Reads through the same canonical project store locator bead waits use.
    Meant for rare fallback use; failures give an empty list.
    """
    creator = _nonempty_str(creator_global_name)
    if not _nonempty_str(project) or creator is None:
        return []
    try:
        issues = _epic_plan_issues(str(project).strip())
    except Exception as exc:
        _logger.warning(
            "could not attribute epics for %s in %s: %s",
            creator,
            project,
            exc,
        )
        return []
    return _attributed_from_issues(
        issues,
        creator=creator,
        plan_ref=plan_ref,
        plan_basename=plan_basename,
    )


def _epic_plan_issues(project: str) -> list[Any]:
    from sase.bead.model import BeadTier, IssueType
    from sase.bead.store_locator import (
        canonical_beads_dir_for_project,
        open_bead_project_for_beads_dir,
    )

    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        return []
    with open_bead_project_for_beads_dir(beads_dir) as bead_project:
        return bead_project.list_issues(
            issue_types=[IssueType.PLAN],
            tiers=[BeadTier.EPIC],
        )


def _attributed_from_issues(
    issues: list[Any],
    *,
    creator: str,
    plan_ref: str | None = None,
    plan_basename: str | None = None,
) -> list[str]:
    wanted_ref = _nonempty_str(plan_ref)
    wanted_base = _nonempty_str(plan_basename)
    if wanted_base is None and wanted_ref is not None:
        wanted_base = Path(wanted_ref).name or None
    if wanted_ref is None and wanted_base is None:
        return []
    matched: list[str] = []
    for issue in issues:
        if getattr(issue, "created_by", "") != creator:
            continue
        design = getattr(issue, "design", "")
        if not isinstance(design, str) or not design.strip():
            continue
        design = design.strip()
        if wanted_ref is not None and design == wanted_ref:
            matched.append(issue.id)
        elif wanted_base is not None and Path(design).name == wanted_base:
            matched.append(issue.id)
    return list(dict.fromkeys(matched))


__all__ = [
    "AGENT_COMMAND_VIA",
    "CREATED_EPICS_FIELD",
    "HOST_LAUNCH_VIA",
    "CreatedEpic",
    "attributed_epic_ids",
    "coerce_created_epics",
    "created_epic_ids_from_meta",
    "launched_epic_bead_id",
    "record_created_epic",
    "resolve_creator_artifacts_dir",
]
