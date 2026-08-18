"""Detect RUNNING-field / occupant-record occupancy conflicts.

The detect phase of the workspace-exclusivity epic (sase-q0) reports — and
never auto-repairs — three conflict shapes:

- the same workspace number claimed by more than one RUNNING row
- a live claim whose checkout occupant names a different live pid
- an occupant record with no corresponding RUNNING claim

Each conflict is annotated with the last matching workspace-claim ledger
record so a doctor report can name when the row was last mutated and by
which caller tag.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import Any

from sase._linked_repo_config import resolution_config
from sase.core.agent_launch_claims import list_workspace_claims_from_content
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.logs.workspace_claim_ledger import ledger_path, read_ledger_records
from sase.running_field._model import WorkspaceClaim
from sase.workspace_provider.occupant import OccupantRecord, read_occupant_record
from sase.workspace_provider.registry import WorkspaceRegistryError, load_registry
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM, WorkspaceStore

ProcessRunningProbe = Callable[[int], bool]

CODE_DUPLICATE_CLAIM = "duplicate_running_claim"
CODE_OCCUPANT_PID_MISMATCH = "occupant_pid_mismatch"
CODE_ORPHAN_OCCUPANT = "orphan_occupant"


@dataclass(frozen=True)
class OccupancyConflict:
    """One reported occupancy conflict for a single project workspace."""

    code: str
    project: str
    project_file: str
    workspace_num: int
    message: str
    last_mutated_at: str | None = None
    last_caller_tag: str | None = None
    claim_pids: tuple[int, ...] = ()
    occupant_pid: int | None = None
    checkout_dir: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "project": self.project,
            "project_file": self.project_file,
            "workspace_num": self.workspace_num,
            "message": self.message,
            "last_mutated_at": self.last_mutated_at,
            "last_caller_tag": self.last_caller_tag,
            "claim_pids": list(self.claim_pids),
            "occupant_pid": self.occupant_pid,
            "checkout_dir": self.checkout_dir,
        }


def detect_occupancy_conflicts(
    projects_root: Path | str | None = None,
    *,
    process_running: ProcessRunningProbe | None = None,
    ledger_file: str | None = None,
) -> tuple[OccupancyConflict, ...]:
    """Scan every project for occupancy conflicts.

    Reads the RUNNING field and each registered checkout's occupant marker.
    Report-only: this function never mutates claims, occupant files, or the
    ledger. *ledger_file* overrides the canonical ledger path for tests.
    """

    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    alive = process_running or _pid_is_alive
    discovered = list_project_records(
        root,
        "all",
        include_home=False,
        projects_only=False,
    )
    projects = [record for record in discovered if record.is_project]
    canonical_ledger = ledger_path()
    records = read_ledger_records(
        ledger_file=ledger_file if ledger_file is not None else str(canonical_ledger)
    )
    conflicts: list[OccupancyConflict] = []
    for project_record in projects:
        conflicts.extend(_conflicts_for_project(project_record, process_running=alive))
    annotated = tuple(
        _annotate_with_ledger(conflict, records) for conflict in conflicts
    )
    return annotated


def _conflicts_for_project(
    project_record: ProjectRecordWire,
    *,
    process_running: ProcessRunningProbe,
) -> list[OccupancyConflict]:
    project = effective_project_name(project_record)
    project_file = project_record.project_file
    claims = _read_claims(project_file)
    numbered = [
        claim for claim in claims if claim.workspace_num != PRIMARY_WORKSPACE_NUM
    ]
    by_num: dict[int, list[WorkspaceClaim]] = defaultdict(list)
    for claim in numbered:
        by_num[claim.workspace_num].append(claim)

    conflicts: list[OccupancyConflict] = []
    for workspace_num, rows in sorted(by_num.items()):
        if len(rows) < 2:
            continue
        pids = tuple(claim.pid for claim in rows)
        occupants = ", ".join(f"PID {claim.pid} ({claim.workflow})" for claim in rows)
        conflicts.append(
            OccupancyConflict(
                code=CODE_DUPLICATE_CLAIM,
                project=project,
                project_file=project_file,
                workspace_num=workspace_num,
                message=(
                    f"Workspace #{workspace_num} is claimed by more than one "
                    f"RUNNING row: {occupants}"
                ),
                claim_pids=pids,
            )
        )

    checkouts = _project_checkouts(project_record, claimed_nums=set(by_num))
    for workspace_num, checkout_dir in sorted(checkouts.items()):
        occupant: OccupantRecord | None = read_occupant_record(checkout_dir)
        if occupant is None:
            continue
        rows = by_num.get(workspace_num, [])
        if not rows:
            conflicts.append(
                OccupancyConflict(
                    code=CODE_ORPHAN_OCCUPANT,
                    project=project,
                    project_file=project_file,
                    workspace_num=workspace_num,
                    message=(
                        f"Workspace #{workspace_num} has an occupant record "
                        f"(PID {occupant.pid}, {occupant.workflow}) but no "
                        f"corresponding RUNNING claim"
                    ),
                    occupant_pid=occupant.pid,
                    checkout_dir=checkout_dir,
                )
            )
            continue
        if not process_running(occupant.pid):
            continue
        live_claims = [claim for claim in rows if process_running(claim.pid)]
        foreign_live = tuple(
            claim.pid for claim in live_claims if claim.pid != occupant.pid
        )
        if not foreign_live:
            continue
        claim_list = ", ".join(f"PID {pid}" for pid in foreign_live)
        conflicts.append(
            OccupancyConflict(
                code=CODE_OCCUPANT_PID_MISMATCH,
                project=project,
                project_file=project_file,
                workspace_num=workspace_num,
                message=(
                    f"Workspace #{workspace_num} has a live RUNNING claim "
                    f"({claim_list}) but the checkout occupant is a different "
                    f"live PID {occupant.pid} ({occupant.workflow})"
                ),
                claim_pids=foreign_live,
                occupant_pid=occupant.pid,
                checkout_dir=checkout_dir,
            )
        )
    return conflicts


def _read_claims(project_file: str) -> list[WorkspaceClaim]:
    try:
        content = Path(project_file).read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        return list_workspace_claims_from_content(content)
    except (RuntimeError, TypeError, ValueError):
        return []


def _project_checkouts(
    project_record: ProjectRecordWire,
    *,
    claimed_nums: set[int],
) -> dict[int, str]:
    raw_primary = (project_record.workspace_dir or "").strip()
    if not raw_primary:
        return {}
    primary = str(Path(raw_primary).expanduser().resolve(strict=False))
    try:
        store = WorkspaceStore(primary, config=resolution_config(primary, None))
    except Exception:
        return {}

    checkouts: dict[int, str] = {}
    try:
        registry = load_registry(store, strict=True)
    except WorkspaceRegistryError:
        registry = None
    if registry is not None:
        for raw_num, entry in registry.workspaces.items():
            try:
                workspace_num = int(raw_num)
            except (TypeError, ValueError):
                continue
            if workspace_num == PRIMARY_WORKSPACE_NUM:
                continue
            checkout_dir = entry.checkout_dir.rstrip("/") or entry.checkout_dir
            checkouts[workspace_num] = checkout_dir

    for workspace_num in sorted(claimed_nums - set(checkouts)):
        try:
            resolved = store.resolve(workspace_num)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        checkout_dir = resolved.checkout_dir.rstrip("/") or resolved.checkout_dir
        if Path(checkout_dir).is_dir():
            checkouts[workspace_num] = checkout_dir
    return checkouts


def _annotate_with_ledger(
    conflict: OccupancyConflict,
    records: Sequence[dict[str, Any]],
) -> OccupancyConflict:
    last = _last_ledger_record(
        records,
        project_file=conflict.project_file,
        workspace_num=conflict.workspace_num,
    )
    if last is None:
        return conflict
    timestamp = last.get("timestamp")
    caller_tag = last.get("caller_tag")
    ts = str(timestamp) if timestamp else None
    tag = str(caller_tag) if caller_tag else None
    extra = ""
    if ts and tag:
        extra = f" Last mutated at {ts} by {tag}."
    elif ts:
        extra = f" Last mutated at {ts}."
    elif tag:
        extra = f" Last mutated by {tag}."
    if not extra:
        return replace(conflict, last_mutated_at=ts, last_caller_tag=tag)
    return replace(
        conflict,
        message=conflict.message + extra,
        last_mutated_at=ts,
        last_caller_tag=tag,
    )


def _last_ledger_record(
    records: Sequence[dict[str, Any]],
    *,
    project_file: str,
    workspace_num: int,
) -> dict[str, Any] | None:
    matches = [
        record
        for record in records
        if record.get("workspace_num") == workspace_num
        and _same_project_file(record.get("project_file"), project_file)
    ]
    return matches[-1] if matches else None


def _same_project_file(left: object, right: str) -> bool:
    if not isinstance(left, str) or not left:
        return False
    if left == right:
        return True
    try:
        return Path(left).expanduser().resolve(strict=False) == Path(
            right
        ).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return False


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


__all__ = [
    "CODE_DUPLICATE_CLAIM",
    "CODE_OCCUPANT_PID_MISMATCH",
    "CODE_ORPHAN_OCCUPANT",
    "OccupancyConflict",
    "detect_occupancy_conflicts",
]
