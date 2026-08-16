"""Persisted state and project inventory for the bead-task-triage chop."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from sase.bead.flag_due import flag_removal_due
from sase.bead.model import Issue, IssueType, Status
from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.chops.sdk import ChopLogger
from sase.core import bead_read_facade as rust_beads
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records

STATE_SCHEMA_VERSION = 3

_GATEABLE_STORE_STATUSES = (Status.OPEN, Status.READY, Status.SNOOZED)
_GATEABLE_TASK_STATUSES = (Status.READY, Status.SNOOZED)


@dataclass
class ProjectState:
    gates: dict[str, str] = field(default_factory=dict)
    generations: dict[str, int] = field(default_factory=dict)
    fingerprints: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectInventory:
    stores: tuple[tuple[str, Path], ...]
    skipped_projects: frozenset[str] = frozenset()
    sweep_allowed: bool = True


def read_state(
    path: Path,
    *,
    gate_kinds: tuple[str, ...],
) -> dict[str, ProjectState]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    raw_projects = payload.get("projects")
    if not isinstance(raw_projects, dict):
        return {}

    projects: dict[str, ProjectState] = {}
    for project_name, raw_project in raw_projects.items():
        if not isinstance(project_name, str) or not isinstance(raw_project, dict):
            continue
        raw_gates = raw_project.get("gates")
        raw_generations = raw_project.get("generations")
        raw_fingerprints = raw_project.get("fingerprints")
        raw_kinds = raw_project.get("kinds")
        gates = (
            {
                bead_id: request_id
                for bead_id, request_id in raw_gates.items()
                if isinstance(bead_id, str) and isinstance(request_id, str)
            }
            if isinstance(raw_gates, dict)
            else {}
        )
        generations = (
            {
                bead_id: generation
                for bead_id, generation in raw_generations.items()
                if isinstance(bead_id, str)
                and isinstance(generation, int)
                and not isinstance(generation, bool)
                and generation >= 1
            }
            if isinstance(raw_generations, dict)
            else {}
        )
        fingerprints = (
            {
                bead_id: fingerprint
                for bead_id, fingerprint in raw_fingerprints.items()
                if isinstance(bead_id, str)
                and bead_id in gates
                and isinstance(fingerprint, str)
                and fingerprint
            }
            if isinstance(raw_fingerprints, dict)
            else {}
        )
        # A version-2 state file recorded no kind because triage was the only
        # one; every gate it names is therefore a TaskTriage gate.
        kinds = (
            {
                bead_id: kind
                for bead_id, kind in raw_kinds.items()
                if isinstance(bead_id, str) and bead_id in gates and kind in gate_kinds
            }
            if isinstance(raw_kinds, dict)
            else {}
        )
        if gates or generations or fingerprints:
            projects[project_name] = ProjectState(
                gates=gates,
                generations=generations,
                fingerprints=fingerprints,
                kinds=kinds,
            )
    return projects


def write_state(path: Path, projects: dict[str, ProjectState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "projects": {
            project_name: {
                "gates": dict(sorted(project.gates.items())),
                "generations": dict(sorted(project.generations.items())),
                "fingerprints": dict(sorted(project.fingerprints.items())),
                "kinds": dict(sorted(project.kinds.items())),
            }
            for project_name, project in sorted(projects.items())
            if project.gates or project.generations or project.fingerprints
        },
    }
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def enabled_project_stores(log: ChopLogger) -> ProjectInventory:
    records = list(
        list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    )
    stores: list[tuple[str, Path]] = []
    skipped_projects: set[str] = set()
    for record in records:
        if (
            not record.is_project
            or record.state != "enabled"
            or record.system_managed
            or record.project_name == "home"
        ):
            continue
        try:
            beads_dir = canonical_beads_dir_for_project(record.project_name)
        except Exception as exc:  # noqa: BLE001 - continue with healthy projects.
            skipped_projects.add(record.project_name)
            log.warning(
                f"[bead_task_triage] Failed to locate bead store for "
                f"{project_display_name(record.project_name)}: {exc}"
            )
            continue
        if beads_dir is None:
            skipped_projects.add(record.project_name)
            continue
        stores.append((record.project_name, beads_dir))
    return ProjectInventory(
        stores=tuple(stores),
        skipped_projects=frozenset(skipped_projects),
        sweep_allowed=bool(records),
    )


def coerce_project_inventory(
    value: ProjectInventory | Iterable[tuple[str, Path]],
) -> ProjectInventory:
    """Normalize legacy test doubles that still return the old stores list."""
    if isinstance(value, ProjectInventory):
        return value
    return ProjectInventory(stores=tuple(value))


def project_display_name(project_name: str) -> str:
    try:
        from sase.project_display_names import project_display_name_for

        return project_display_name_for(project_name)
    except Exception:  # noqa: BLE001 - logging must not perturb reconciliation.
        return project_name


def gateable_beads(beads_dir: Path, *, today: date, release: str) -> list[Issue]:
    """Read every task or flag bead that owes the user a gate, in one store pass.

    A task bead is gateable while ``ready`` or ``snoozed``, unchanged from
    before. A flag bead is gateable only while ``open`` and due -- both its
    date and release removal thresholds have passed, per
    :func:`sase.bead.flag_due.flag_removal_due` -- so due-ness is never
    persisted on the bead itself. *today* and *release* are explicit
    arguments so tests never need to freeze the clock globally.
    """
    issues = rust_beads.list_issues(
        beads_dir,
        statuses=list(_GATEABLE_STORE_STATUSES),
        issue_types=[IssueType.TASK, IssueType.FLAG],
    )
    gateable: list[Issue] = []
    for issue in issues:
        if issue.issue_type == IssueType.TASK:
            if issue.status in _GATEABLE_TASK_STATUSES:
                gateable.append(issue)
        elif issue.issue_type == IssueType.FLAG:
            if (
                issue.status == Status.OPEN
                and issue.flag is not None
                and flag_removal_due(issue.flag, today=today, release=release) == "due"
            ):
                gateable.append(issue)
    return gateable
