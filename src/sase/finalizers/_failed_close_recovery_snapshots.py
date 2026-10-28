"""Verified checkout snapshots attached to failed-close evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.finalizers._failed_close_recovery_assess import RecoveryAssessment
from sase.procs.text_bounding import bound_and_redact_text
from sase.workspace_provider.snapshot import (
    SNAPSHOT_KIND,
    PreservationError,
    snapshot_git_repo,
    snapshot_source_fingerprint,
)

_MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class _SnapshotEvidence:
    """Snapshot records and diagnostics retained with a failed-close retry."""

    records: tuple[dict[str, Any], ...]
    locations: tuple[str, ...]
    errors: tuple[dict[str, str], ...]
    previous_evidence_locations: tuple[str, ...]


def capture_failed_close_snapshots(
    artifacts_dir: str,
    assessment: RecoveryAssessment,
    *,
    run_id: str,
) -> _SnapshotEvidence:
    """Capture only host-assessed, unlanded repositories before cleanup can run."""
    previous_records, previous_errors, previous_locations = _read_prior_evidence(
        Path(artifacts_dir)
    )
    records = list(previous_records)
    errors = list(previous_errors)
    locations: list[str] = []

    for settlement in assessment.repositories:
        if settlement.landed or settlement.deferred:
            continue
        repo = settlement.repo
        repo_root = Path(repo.path).resolve(strict=False)
        try:
            fingerprint = snapshot_source_fingerprint(repo_root)
            reused = next(
                (
                    item
                    for item in records
                    if _record_matches(item, repo_root, fingerprint)
                ),
                None,
            )
            if reused is not None:
                reused["reused"] = True
                locations.append(str(reused["manifest_path"]))
                continue

            workspace_dir, workspace_num = _workspace_identity(repo_root)
            snapshot = snapshot_git_repo(
                repo_root,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                label=repo.name,
                reason=f"failed finalization for host run {run_id}",
            )
            if snapshot is None:
                continue
            entry = _record_snapshot(repo.name, repo_root, snapshot.manifest_path)
            if entry is None:
                raise PreservationError(
                    "snapshot returned without a complete verified manifest"
                )
            records.append(entry)
            locations.append(str(entry["manifest_path"]))
        except Exception as exc:  # noqa: BLE001 - recovery must continue on snapshot errors.
            errors.append(
                {
                    "repo": repo.name,
                    "repo_path": str(repo_root),
                    "error": _redact(str(exc) or type(exc).__name__),
                }
            )

    # Previous records remain evidence even when a later retry captures a new
    # fingerprint. Keep every previously verified locator in the request.
    complete_locations = [
        str(item["manifest_path"])
        for item in records
        if _manifest_is_complete(Path(str(item.get("manifest_path", ""))))
    ]
    return _SnapshotEvidence(
        records=tuple(_dedupe_records(records)),
        locations=tuple(_unique(complete_locations + locations)),
        errors=tuple(_dedupe_errors(errors)),
        previous_evidence_locations=tuple(previous_locations),
    )


def _read_prior_evidence(
    artifacts_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    from sase.finalizers._failed_close_recovery_apply import (
        RECOVERY_OUTCOME_FILENAME,
        RECOVERY_REQUEST_FILENAME,
    )

    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    locations: list[str] = []
    for filename in (RECOVERY_REQUEST_FILENAME, RECOVERY_OUTCOME_FILENAME):
        try:
            payload = json.loads((artifacts_dir / filename).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        for candidate in (payload, payload.get("request")):
            if not isinstance(candidate, Mapping):
                continue
            raw_records = candidate.get("snapshots")
            if isinstance(raw_records, list):
                records.extend(
                    dict(row) for row in raw_records if isinstance(row, Mapping)
                )
            raw_errors = candidate.get("snapshot_errors")
            if isinstance(raw_errors, list):
                errors.extend(
                    {str(key): str(value) for key, value in row.items()}
                    for row in raw_errors
                    if isinstance(row, Mapping)
                )
            raw_locations = candidate.get("evidence_locations")
            if isinstance(raw_locations, list):
                locations.extend(
                    str(value) for value in raw_locations if isinstance(value, str)
                )
    return _dedupe_records(records), _dedupe_errors(errors), _unique(locations)


def _record_matches(
    record: Mapping[str, Any], repo_root: Path, fingerprint: Mapping[str, str]
) -> bool:
    if str(record.get("repo_path", "")) != str(repo_root):
        return False
    if record.get("source_fingerprint") != dict(fingerprint):
        return False
    manifest_path = Path(str(record.get("manifest_path", "")))
    if not manifest_path.is_absolute() or not _manifest_is_complete(manifest_path):
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(manifest, Mapping)
        and manifest.get("kind") == SNAPSHOT_KIND
        and manifest.get("repo_root") == str(repo_root)
        and manifest.get("snapshot_id") == record.get("snapshot_id")
        and manifest.get("source_fingerprint") == dict(fingerprint)
    )


def _record_snapshot(
    repo_name: str, repo_root: Path, manifest_path: Path
) -> dict[str, Any] | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, Mapping):
        return None
    fingerprint = manifest.get("source_fingerprint")
    if (
        manifest.get("kind") != SNAPSHOT_KIND
        or manifest.get("repo_root") != str(repo_root)
        or not isinstance(manifest.get("snapshot_id"), str)
        or not isinstance(fingerprint, Mapping)
        or not _manifest_is_complete(manifest_path)
    ):
        return None
    return {
        "repo": repo_name,
        "repo_path": str(repo_root),
        "snapshot_id": str(manifest["snapshot_id"]),
        "manifest_path": str(manifest_path.resolve(strict=False)),
        "source_fingerprint": dict(fingerprint),
        "reused": False,
    }


def _manifest_is_complete(manifest_path: Path) -> bool:
    if not manifest_path.is_absolute() or manifest_path.name != _MANIFEST_NAME:
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, Mapping) or manifest.get("kind") != SNAPSHOT_KIND:
        return False
    payloads = manifest.get("payloads")
    if not isinstance(payloads, Mapping):
        return False
    for key in ("pack", "index_stage"):
        name = payloads.get(key)
        if not isinstance(name, str) or Path(name).name != name:
            return False
        if not (manifest_path.parent / name).is_file():
            return False
    return True


def _workspace_identity(repo_root: Path) -> tuple[Path, int]:
    from sase.workspace_provider.marker import find_marker_from_cwd
    from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

    found = find_marker_from_cwd(str(repo_root))
    if found is None:
        return repo_root, PRIMARY_WORKSPACE_NUM
    checkout_root, marker = found
    workspace_dir = Path(marker.primary_workspace_dir or checkout_root)
    return workspace_dir, marker.workspace_num


def _dedupe_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        path = str(row.get("manifest_path", ""))
        snapshot_id = str(row.get("snapshot_id", ""))
        if path and snapshot_id:
            unique[(path, snapshot_id)] = dict(row)
    return list(unique.values())


def _dedupe_errors(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for row in errors:
        normalized = {str(key): str(value) for key, value in row.items()}
        key = json.dumps(normalized, sort_keys=True)
        unique[key] = normalized
    return list(unique.values())


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _redact(value: str) -> str:
    return bound_and_redact_text(value, 4000) or "snapshot failed"


__all__ = ["capture_failed_close_snapshots"]
