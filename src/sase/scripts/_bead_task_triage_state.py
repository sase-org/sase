"""Persisted state and gateable-bead reads for the bead-task-triage chop."""

from __future__ import annotations

from datetime import date
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from sase.bead.flag_due import flag_removal_due
from sase.bead.model import Issue, IssueType, Status
from sase.core import bead_read_facade as rust_beads

STATE_SCHEMA_VERSION = 3

_GATEABLE_STORE_STATUSES = (Status.OPEN, Status.READY, Status.SNOOZED)
_GATEABLE_TASK_STATUSES = (Status.READY, Status.SNOOZED)


@dataclass
class ProjectState:
    gates: dict[str, str] = field(default_factory=dict)
    generations: dict[str, int] = field(default_factory=dict)
    fingerprints: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)


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
                and flag_removal_due(
                    issue.flag.remove_by_date,
                    issue.flag.remove_by_release,
                    today=today,
                    release=release,
                )
                == "due"
            ):
                gateable.append(issue)
    return gateable
