"""Quarantine-record and local-admission IO for artifact-link collisions.

Read-only snapshots and doctor do not write these files. Publication and local
durable admission persist them under the existing publication lock with
atomic no-replace plus fsync.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_history import ArtifactLinkCollisionEvidence
from sase.sdd._artifact_link_event_canonical import ArtifactLinkEventCorruptionError
from sase.sdd._artifact_link_event_install import install_artifact_link_bytes

_QUARANTINE_NAMESPACE = Path("link-events") / "quarantine" / "v1"
_QUARANTINE_STAGING = _QUARANTINE_NAMESPACE / ".staging"
_ADMISSION_DIR = Path("link-events") / "admission" / "v1"
_ADMISSION_STAGING = _ADMISSION_DIR / ".staging"
_ADMISSION_SCHEMA_VERSION = 1
_UNSAFE_SYMLINK = "quarantine path is a symlink"
_UNSAFE_NOT_DIRECTORY = "quarantine path is not a directory"
_UNSAFE_NOT_FILE = "quarantine path is not a regular file"
_UNSAFE_ESCAPE = "quarantine path escapes the store root"
_UNSAFE_BROKEN = "quarantine path is a broken symlink"


def _reusable_quarantine_record(
    root: str | Path,
    relative: str,
    finding: ArtifactLinkQuarantineFinding,
    *,
    rejected_canonical_json: str,
) -> str | None:
    """Return *relative* without writing when a matching immutable record exists.

    A match requires the stored record to validate and to agree on project,
    operation, accepted/rejected digests, and the full rejected payload
    (event plus canonical JSON). Basis, detail, ambiguity, and locator may
    differ across the durability transition and do not block reuse. Any other
    difference, malformed bytes, or symlink returns None so the normal
    no-replace install reports corruption.
    """

    resolved = Path(root).expanduser().resolve(strict=False)
    if _unsafe_quarantine_file_reason(resolved, relative, leaf_must_exist=True):
        return None
    existing_path = resolved / relative
    try:
        if existing_path.is_symlink() or not existing_path.is_file():
            return None
        payload = json.loads(existing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        validated = dict(
            require_rust_binding("artifact_link_quarantine_record_validate")(payload)
        )
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return None
    if str(validated.get("project_key") or "") != finding.project_key:
        return None
    if str(validated.get("operation_id") or "") != finding.operation_id:
        return None
    if str(validated.get("accepted_digest") or "") != finding.accepted_digest:
        return None
    if str(validated.get("rejected_digest") or "") != finding.rejected_digest:
        return None
    stored_event = validated.get("rejected_event")
    if not isinstance(stored_event, Mapping):
        return None
    if dict(stored_event) != dict(finding.rejected_event):
        return None
    if str(validated.get("rejected_canonical_json") or "") != rejected_canonical_json:
        return None
    return relative


@dataclass(frozen=True, slots=True)
class ArtifactLinkQuarantineFinding:
    """One rejected payload plus the accepted digest and selection basis."""

    project_key: str
    operation_id: str
    accepted_digest: str
    rejected_digest: str
    rejected_event: dict[str, Any]
    basis: str
    detail: str
    source_locator: str | None = None
    ambiguity: tuple[str, ...] = ()
    rejected_path: str | None = None
    record_path: str | None = None

    def render(self) -> str:
        parts = [
            (
                f"operation {self.operation_id} collision: accepted "
                f"{self.accepted_digest} ({self.basis})"
            ),
            f"rejected {self.rejected_digest}",
        ]
        if self.source_locator:
            parts.append(f"source {self.source_locator}")
        if self.rejected_path:
            parts.append(f"rejected bytes remain at {self.rejected_path}")
        if self.record_path:
            parts.append(f"quarantine record {self.record_path}")
        if self.ambiguity:
            parts.append("ambiguity: " + "; ".join(self.ambiguity))
        return "; ".join(parts)


def persist_artifact_link_quarantine_record(
    root: str | Path,
    finding: ArtifactLinkQuarantineFinding,
    *,
    rejected_canonical_json: str,
) -> str:
    """Persist one quarantine record. Repeat replays with the same bytes are no-ops.

    Once the winner is durable the partition reports a stronger basis
    (``durable_beats_pending``/``durable_beats_incoming``) with different
    detail/ambiguity/locator for the same accepted/rejected decision. Reuse a
    validated existing immutable record when its identity and full rejected
    payload match, preserving its original bytes and provenance. Different
    payloads, malformed evidence, or incompatible decisions remain corruption.
    """

    try:
        relative = str(
            require_rust_binding("artifact_link_quarantine_record_path")(
                finding.operation_id,
                finding.rejected_digest,
            )
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ArtifactLinkEventCorruptionError(
            f"artifact-link quarantine record path is invalid for "
            f"{finding.operation_id}:{finding.rejected_digest}: {exc}"
        ) from exc
    resolved_root = Path(root).expanduser().resolve(strict=False)
    unsafe = _unsafe_quarantine_file_reason(
        resolved_root, relative, leaf_must_exist=False
    )
    if unsafe is not None:
        raise ArtifactLinkEventCorruptionError(f"{relative}: {unsafe}")
    staging_unsafe = _walk_quarantine_components(
        resolved_root,
        _QUARANTINE_STAGING.as_posix(),
        leaf_kind="directory",
        leaf_must_exist=False,
    )
    if staging_unsafe is not None:
        raise ArtifactLinkEventCorruptionError(
            f"{_QUARANTINE_STAGING.as_posix()}: {staging_unsafe}"
        )
    existing_relative = _reusable_quarantine_record(
        root,
        relative,
        finding,
        rejected_canonical_json=rejected_canonical_json,
    )
    if existing_relative is not None:
        return existing_relative
    record = {
        "schema_version": int(
            require_rust_binding("artifact_link_quarantine_wire_schema_version")()
        ),
        "project_key": finding.project_key,
        "operation_id": finding.operation_id,
        "accepted_digest": finding.accepted_digest,
        "rejected_digest": finding.rejected_digest,
        "rejected_event": finding.rejected_event,
        "rejected_canonical_json": rejected_canonical_json,
        "selection_basis": finding.basis,
        "ambiguity": list(finding.ambiguity),
        "detail": finding.detail,
    }
    if finding.source_locator is not None:
        record["source_locator"] = finding.source_locator
    try:
        canonical = str(
            require_rust_binding("artifact_link_quarantine_record_canonical_json")(
                record
            )
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ArtifactLinkEventCorruptionError(
            f"artifact-link quarantine record is invalid for "
            f"{finding.operation_id}:{finding.rejected_digest}: {exc}"
        ) from exc
    install_artifact_link_bytes(
        root,
        relative,
        canonical.encode("utf-8"),
        staging_dir=_QUARANTINE_STAGING,
    )
    return relative


def load_artifact_link_quarantine_records(
    roots: Iterable[str | Path],
    expected_project_key: str | None = None,
) -> tuple[tuple[ArtifactLinkQuarantineFinding, ...], tuple[str, ...]]:
    """Load persisted quarantine records from *roots*. Invalid files are blocking.

    Each record's operation/digest path and, when *expected_project_key* is
    given, its store project are enforced alongside the existing
    symlink/corruption rules. Valid quarantine stays a nonblocking diagnostic;
    malformed or misfiled records remain blocking. Read-only callers stay
    side-effect free.
    """

    findings: list[ArtifactLinkQuarantineFinding] = []
    errors: list[str] = []
    seen_roots: set[Path] = set()
    validate = require_rust_binding("artifact_link_quarantine_record_validate")
    record_path_binding = require_rust_binding("artifact_link_quarantine_record_path")
    for raw_root in roots:
        root = Path(raw_root).expanduser().resolve(strict=False)
        if root in seen_roots:
            continue
        seen_roots.add(root)
        record_root = root / _QUARANTINE_NAMESPACE
        namespace_error = _unsafe_quarantine_dir_reason(
            root, _QUARANTINE_NAMESPACE.as_posix()
        )
        if namespace_error == "missing":
            continue
        if namespace_error is not None:
            errors.append(f"{_QUARANTINE_NAMESPACE.as_posix()}: {namespace_error}")
            continue
        scanned_files, scan_errors = _scan_quarantine_tree(root, record_root)
        errors.extend(scan_errors)
        for path in scanned_files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{_display_path(root, path)}: {exc}")
                continue
            if not isinstance(payload, dict):
                errors.append(
                    f"{_display_path(root, path)}: quarantine record is not an object"
                )
                continue
            try:
                validated = dict(validate(payload))
            except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
                errors.append(f"{_display_path(root, path)}: {exc}")
                continue
            try:
                expected_relative = str(
                    record_path_binding(
                        str(validated.get("operation_id") or ""),
                        str(validated.get("rejected_digest") or ""),
                    )
                )
            except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
                errors.append(f"{_display_path(root, path)}: {exc}")
                continue
            actual_relative = _display_path(root, path)
            if actual_relative != expected_relative:
                errors.append(
                    f"{actual_relative}: quarantine path does not match "
                    f"operation {validated.get('operation_id')} digest "
                    f"{validated.get('rejected_digest')}"
                )
                continue
            if (
                expected_project_key is not None
                and str(validated.get("project_key") or "") != expected_project_key
            ):
                errors.append(
                    f"{actual_relative}: quarantine project "
                    f"{validated.get('project_key')!r} != {expected_project_key!r}"
                )
                continue
            file_error = _unsafe_quarantine_file_reason(
                root, actual_relative, leaf_must_exist=True
            )
            if file_error is not None:
                errors.append(f"{actual_relative}: {file_error}")
                continue
            findings.append(_finding_from_record(validated, relative=actual_relative))
    return tuple(findings), tuple(errors)


def record_artifact_link_admission(
    root: str | Path,
    *,
    digest: str,
    operation_id: str,
) -> int:
    """Record durable admission evidence for one local-only object.

    Existing records are left in place (first admission wins). The assigned
    sequence is the next integer after any records already stored under *root*.
    """

    root = Path(root).expanduser().resolve(strict=False)
    existing = _admission_record(root, digest)
    if existing is not None:
        return existing
    sequence = _next_admission_sequence(root)
    relative = _ADMISSION_DIR / f"{digest}.json"
    payload = json.dumps(
        {
            "schema_version": _ADMISSION_SCHEMA_VERSION,
            "digest": digest,
            "operation_id": operation_id,
            "sequence": sequence,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    from sase.sdd._artifact_link_event_canonical import (
        ArtifactLinkEventCorruptionError,
    )

    try:
        install_artifact_link_bytes(
            root,
            relative,
            f"{payload}\n".encode(),
            staging_dir=_ADMISSION_STAGING,
        )
    except ArtifactLinkEventCorruptionError:
        recorded = _admission_record(root, digest)
        if recorded is not None:
            return recorded
        raise
    return _admission_record(root, digest) or sequence


def _admission_sequence_for(root: str | Path, digest: str) -> int | None:
    """Return the persisted admission sequence for *digest*, if any."""

    return _admission_record(Path(root).expanduser().resolve(strict=False), digest)


def attach_admission_evidence(candidates: Sequence[Any]) -> tuple[Any, ...]:
    """Fill admission_sequence on candidates that have a local admission record."""

    from dataclasses import replace

    updated: list[Any] = []
    for candidate in candidates:
        root = getattr(candidate, "root", None)
        digest = str(getattr(candidate, "digest", "") or "")
        if not root or not digest:
            updated.append(candidate)
            continue
        sequence = _admission_sequence_for(root, digest)
        if sequence is None:
            updated.append(candidate)
            continue
        current = getattr(candidate, "evidence", ArtifactLinkCollisionEvidence())
        if not isinstance(current, ArtifactLinkCollisionEvidence):
            current = ArtifactLinkCollisionEvidence()
        if current.admission_sequence == sequence:
            updated.append(candidate)
            continue
        updated.append(
            replace(
                candidate,
                evidence=ArtifactLinkCollisionEvidence(
                    history_complete=current.history_complete,
                    first_commit_id=current.first_commit_id,
                    first_commit_at=current.first_commit_at,
                    ancestor_commit_ids=current.ancestor_commit_ids,
                    admission_sequence=sequence,
                ),
            )
        )
    return tuple(updated)


def merge_quarantine_findings(
    logical: Iterable[ArtifactLinkQuarantineFinding],
    persisted: Iterable[ArtifactLinkQuarantineFinding],
) -> tuple[ArtifactLinkQuarantineFinding, ...]:
    """Union logical partition findings with persisted incoming-rejection records."""

    merged: dict[tuple[str, str], ArtifactLinkQuarantineFinding] = {}
    for finding in logical:
        merged[(finding.operation_id, finding.rejected_digest)] = finding
    for finding in persisted:
        key = (finding.operation_id, finding.rejected_digest)
        existing = merged.get(key)
        if existing is None:
            merged[key] = finding
            continue
        merged[key] = ArtifactLinkQuarantineFinding(
            project_key=existing.project_key,
            operation_id=existing.operation_id,
            accepted_digest=existing.accepted_digest,
            rejected_digest=existing.rejected_digest,
            rejected_event=existing.rejected_event,
            basis=existing.basis,
            detail=existing.detail,
            source_locator=existing.source_locator or finding.source_locator,
            ambiguity=existing.ambiguity or finding.ambiguity,
            rejected_path=existing.rejected_path or finding.rejected_path,
            record_path=finding.record_path or existing.record_path,
        )
    return tuple(merged[key] for key in sorted(merged))


def _finding_from_record(
    record: Mapping[str, Any],
    *,
    relative: str,
) -> ArtifactLinkQuarantineFinding:
    event = record.get("rejected_event")
    return ArtifactLinkQuarantineFinding(
        project_key=str(record.get("project_key") or ""),
        operation_id=str(record.get("operation_id") or ""),
        accepted_digest=str(record.get("accepted_digest") or ""),
        rejected_digest=str(record.get("rejected_digest") or ""),
        rejected_event=dict(event) if isinstance(event, Mapping) else {},
        basis=str(record.get("selection_basis") or ""),
        detail=str(record.get("detail") or ""),
        source_locator=(
            str(record["source_locator"])
            if record.get("source_locator") is not None
            else None
        ),
        ambiguity=tuple(
            str(item) for item in record.get("ambiguity") or () if str(item)
        ),
        record_path=relative,
    )


def _admission_record(root: Path, digest: str) -> int | None:
    path = root / _ADMISSION_DIR / f"{digest}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("sequence")
    if raw is None:
        return None
    try:
        sequence = int(raw)
    except (TypeError, ValueError):
        return None
    if sequence < 1:
        return None
    return sequence


def _next_admission_sequence(root: Path) -> int:
    record_root = root / _ADMISSION_DIR
    if not record_root.is_dir():
        return 1
    highest = 0
    for path in record_root.glob("*.json"):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        raw = payload.get("sequence")
        if raw is None:
            continue
        try:
            sequence = int(raw)
        except (TypeError, ValueError):
            continue
        highest = max(highest, sequence)
    return highest + 1


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _unsafe_quarantine_dir_reason(root: Path, relative: str) -> str | None:
    """Return why *relative* is an unsafe directory tree, or ``missing``."""

    return _walk_quarantine_components(
        root, relative, leaf_kind="directory", leaf_must_exist=True
    )


def _unsafe_quarantine_file_reason(
    root: Path,
    relative: str,
    *,
    leaf_must_exist: bool,
) -> str | None:
    """Return why *relative* is an unsafe record path under *root*."""

    return _walk_quarantine_components(
        root, relative, leaf_kind="file", leaf_must_exist=leaf_must_exist
    )


def _walk_quarantine_components(
    root: Path,
    relative: str,
    *,
    leaf_kind: str,
    leaf_must_exist: bool,
) -> str | None:
    rel = Path(relative)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        return _UNSAFE_ESCAPE
    cursor = root
    for index, part in enumerate(rel.parts):
        cursor = cursor / part
        last = index == len(rel.parts) - 1
        if cursor.is_symlink():
            try:
                exists = cursor.exists()
            except OSError:
                exists = False
            return _UNSAFE_SYMLINK if exists else _UNSAFE_BROKEN
        if not cursor.exists():
            if last and not leaf_must_exist:
                break
            if not last and not leaf_must_exist:
                break
            return "missing"
        if last:
            if leaf_kind == "directory" and not cursor.is_dir():
                return _UNSAFE_NOT_DIRECTORY
            if leaf_kind == "file" and not cursor.is_file():
                return _UNSAFE_NOT_FILE
        elif not cursor.is_dir():
            return _UNSAFE_NOT_DIRECTORY
    try:
        parent = (root / rel).parent.resolve(strict=False)
        located = parent / rel.name
        located.relative_to(root)
        if located.exists() and not located.is_symlink():
            located.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return _UNSAFE_ESCAPE
    return None


def _scan_quarantine_tree(
    root: Path, record_root: Path
) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    errors: list[str] = []
    for dirpath, dirnames, filenames in os.walk(record_root, followlinks=False):
        is_top = Path(dirpath) == record_root
        kept: list[str] = []
        for name in dirnames:
            child = Path(dirpath) / name
            display = _display_path(root, child)
            if child.is_symlink():
                try:
                    exists = child.exists()
                except OSError:
                    exists = False
                detail = _UNSAFE_SYMLINK if exists else _UNSAFE_BROKEN
                errors.append(f"{display}: {detail}")
                continue
            if not child.is_dir():
                errors.append(f"{display}: {_UNSAFE_NOT_DIRECTORY}")
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            if not name.endswith(".json"):
                # Top-level entries must be operation directories or the
                # staging directory. A plain file or broken symlink at the
                # operation path would otherwise be silently ignored.
                if is_top:
                    path = Path(dirpath) / name
                    display = _display_path(root, path)
                    if path.is_symlink():
                        try:
                            exists = path.exists()
                        except OSError:
                            exists = False
                        detail = _UNSAFE_SYMLINK if exists else _UNSAFE_BROKEN
                        errors.append(f"{display}: {detail}")
                    else:
                        errors.append(f"{display}: {_UNSAFE_NOT_DIRECTORY}")
                continue
            path = Path(dirpath) / name
            display = _display_path(root, path)
            if path.is_symlink():
                try:
                    exists = path.exists()
                except OSError:
                    exists = False
                detail = _UNSAFE_SYMLINK if exists else _UNSAFE_BROKEN
                errors.append(f"{display}: {detail}")
                continue
            if not path.is_file():
                errors.append(f"{display}: {_UNSAFE_NOT_FILE}")
                continue
            files.append(path)
    files.sort()
    return files, errors


__all__ = [
    "ArtifactLinkQuarantineFinding",
    "attach_admission_evidence",
    "load_artifact_link_quarantine_records",
    "merge_quarantine_findings",
    "persist_artifact_link_quarantine_record",
    "record_artifact_link_admission",
]
