"""Replay recovery report, progress files, and shared path constants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from json import loads
from pathlib import Path
from typing import Any

from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.models import ProjectTarget, SyncOutcome
from sase.core.agent_publication_recovery import (
    REPLAY_APPLY_ACTION_REFUSE,
    ReplayPathClassification,
)

PROGRESS_NAME = "progress.json"
CHECKSUMS_NAME = "checksums.json"
REVISIONS_NAME = "revisions.json"
BUNDLE_NAME = "unpublished.bundle"
PRESERVED_DIR = "preserved"
OBJECTS_DIR = "objects"
MUTATION_STAGES = frozenset({"reset", "replaying"})
COMPLETE_STAGE = "complete"
VERIFIED_STAGE = "verified"


@dataclass(frozen=True, slots=True)
class ReplayRecoveryReport:
    """Preservation inventory and optional transaction outcome."""

    project_key: str
    observed_head: str
    expected_head: str
    upstream: str
    ahead: int
    behind: int
    stage: str
    action: str
    already_complete: bool
    apply: bool
    error: str | None
    browsing_paths: tuple[str, ...]
    owner_content_paths: tuple[str, ...]
    archive_object_paths: tuple[str, ...]
    unknown_paths: tuple[str, ...]
    preserved_hoods: tuple[str, ...]
    refused_divergences: tuple[str, ...]
    backup_dir: str
    outcome: SyncOutcome | None = None


def write_progress(backup_root: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(backup_root / PROGRESS_NAME, payload)


def read_progress(backup_root: Path) -> dict[str, Any] | None:
    path = backup_root / PROGRESS_NAME
    if not path.is_file():
        return None
    value = read_json(path)
    return value if isinstance(value, dict) else None


def read_json(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"))


def report_from_state(
    target: ProjectTarget,
    expected_head: str,
    backup_root: Path,
    apply: bool,
    observed: dict[str, Any],
    progress: dict[str, Any] | None,
    classified: ReplayPathClassification | None,
    hoods: tuple[str, ...],
    refused: tuple[str, ...],
    action: str,
    outcome: SyncOutcome | None,
) -> ReplayRecoveryReport:
    browsing = (
        tuple(classified.browsing)
        if classified is not None
        else tuple(progress.get("browsing", ()) if progress else ())
    )
    owner_content = (
        tuple(classified.owner_content)
        if classified is not None
        else tuple(progress.get("owner_content", ()) if progress else ())
    )
    archive_object = (
        tuple(classified.archive_object)
        if classified is not None
        else tuple(progress.get("archive_object", ()) if progress else ())
    )
    unknown = (
        tuple(classified.unknown)
        if classified is not None
        else tuple(progress.get("unknown", ()) if progress else ())
    )
    return ReplayRecoveryReport(
        project_key=target.project_key,
        observed_head=str(observed["head"]),
        expected_head=expected_head,
        upstream=str(observed["upstream"]),
        ahead=int(observed["ahead"]),
        behind=int(observed["behind"]),
        stage=str((progress or {}).get("stage") or "inventory"),
        action=action,
        already_complete=str((progress or {}).get("stage")) == COMPLETE_STAGE,
        apply=apply,
        error=None,
        browsing_paths=tuple(str(item) for item in browsing),
        owner_content_paths=tuple(str(item) for item in owner_content),
        archive_object_paths=tuple(str(item) for item in archive_object),
        unknown_paths=tuple(str(item) for item in unknown),
        preserved_hoods=hoods or tuple(progress.get("hoods", ()) if progress else ()),
        refused_divergences=refused,
        backup_dir=str(backup_root),
        outcome=outcome,
    )


def error_report(
    target: ProjectTarget,
    expected_head: str,
    backup_root: Path,
    apply: bool,
    error: str,
    *,
    observed: dict[str, Any] | None = None,
    classified: ReplayPathClassification | None = None,
    hoods: tuple[str, ...] = (),
    refused: tuple[str, ...] = (),
    outcome: SyncOutcome | None = None,
) -> ReplayRecoveryReport:
    observed = observed or {
        "head": "",
        "upstream": "",
        "ahead": 0,
        "behind": 0,
        "unpublished": (),
    }
    return replace(
        report_from_state(
            target,
            expected_head,
            backup_root,
            apply,
            observed,
            read_progress(backup_root),
            classified,
            hoods,
            refused,
            REPLAY_APPLY_ACTION_REFUSE,
            outcome,
        ),
        error=error,
    )
