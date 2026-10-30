"""Durable protection ledger reads and writes for agents publication."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import time

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync._publication_protection_models import (
    AGENT_PUBLICATION_PROTECTION_FILENAME,
    PublicationBytesVerdict,
)
from sase.agents_sync._publication_protection_scan import ScannedPublicationCandidate
from sase.agents_sync.io import atomic_write_json
from sase.core.agent_publication_protection import (
    AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION,
    publication_protection_ledger_empty,
    publication_protection_ledger_validate,
    publication_protection_lookup,
    publication_protection_record_from_rejection,
    publication_protection_record_from_scan,
    publication_protection_retry_allowed,
    publication_protection_resolve_verified_clean,
    publication_protection_upsert,
)
from sase.core.paths import (
    sase_projects_dir,
    validate_sase_project_name,
)


def _read_publication_protection_ledger(
    project_key: str,
    *,
    projects_root: Path | None = None,
) -> dict[str, object]:
    """Read one validated project ledger under its matching lock."""
    path = _ledger_path(project_key, projects_root=projects_root)
    with _ledger_lock(path):
        return _read_ledger(path)


def read_publication_protection_ledger_from_path(
    path: Path | str,
    project_key: str,
) -> dict[str, object] | None:
    """Read and validate an immutable ledger snapshot for doctor."""
    validate_sase_project_name(project_key)
    ledger_path = Path(path)
    if ledger_path.is_symlink():
        raise RuntimeError("agent publication protection ledger cannot be a symlink")
    if not ledger_path.exists():
        return None
    return _read_ledger(ledger_path)


def record_publication_scan(
    project_key: str,
    *,
    repository_identity: str,
    relative_destination: str,
    candidate: ScannedPublicationCandidate,
    affected_requests: Iterable[str] = (),
    timestamp: float | None = None,
) -> dict[str, object] | None:
    """Persist blocked or unverified scan evidence without storing file bytes."""
    if candidate.sha256 is None or candidate.disposition is None:
        return None
    return _record_scan_disposition(
        project_key,
        repository_identity=repository_identity,
        relative_destination=relative_destination,
        sha256=candidate.sha256,
        disposition=candidate.disposition,
        affected_requests=affected_requests,
        timestamp=timestamp,
    )


def record_publication_bytes_scan(
    project_key: str,
    *,
    repository_identity: str,
    relative_destination: str,
    verdict: PublicationBytesVerdict,
    affected_requests: Iterable[str] = (),
    timestamp: float | None = None,
) -> dict[str, object] | None:
    """Persist blocked or unverified bytes evidence without storing file bytes."""
    if verdict.sha256 is None or verdict.disposition is None:
        return None
    return _record_scan_disposition(
        project_key,
        repository_identity=repository_identity,
        relative_destination=relative_destination,
        sha256=verdict.sha256,
        disposition=verdict.disposition,
        affected_requests=affected_requests,
        timestamp=timestamp,
    )


def lookup_publication_content_record(
    project_key: str,
    *,
    repository_identity: str,
    relative_destination: str,
    sha256: str,
) -> dict[str, object] | None:
    """Return the durable protection row for one published identity, if any.

    Missing or unreadable ledgers mean no decision, never a clean verdict;
    callers keep the existing history-preserving behavior in that case. A
    missing ledger file is checked without creating directories so clean
    drains never touch the filesystem for protection state.
    """
    try:
        path = _ledger_path(project_key)
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - an invalid key means no decision.
        return None
    if path.is_symlink() or not path.exists():
        return None
    try:
        ledger = _read_publication_protection_ledger(project_key)
    except RuntimeError:
        return None
    try:
        return publication_protection_lookup(
            ledger,
            _identity(repository_identity, relative_destination, sha256),
        )
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - a failed lookup never authorizes publish.
        return None


def _record_scan_disposition(
    project_key: str,
    *,
    repository_identity: str,
    relative_destination: str,
    sha256: str,
    disposition: dict[str, object],
    affected_requests: Iterable[str] = (),
    timestamp: float | None = None,
) -> dict[str, object] | None:
    record = publication_protection_record_from_scan(
        {
            "schema_version": AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION,
            "identity": {
                "repository_identity": repository_identity,
                "relative_destination": relative_destination,
                "sha256": sha256,
            },
            "affected_requests": list(affected_requests),
            "disposition": disposition,
            "timestamp": time.time() if timestamp is None else timestamp,
        }
    )
    if record is None:
        return _resolve_verified_clean(
            project_key,
            _identity(
                repository_identity,
                relative_destination,
                sha256,
            ),
        )
    return _upsert_record(project_key, record)


def record_publication_push_rejection(
    project_key: str,
    *,
    repository_identity: str,
    relative_destination: str,
    sha256: str,
    classification: str,
    affected_requests: Iterable[str] = (),
    timestamp: float | None = None,
) -> dict[str, object] | None:
    """Persist a Rust-classified secret rejection without inventing a rule."""
    record = publication_protection_record_from_rejection(
        {
            "schema_version": AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION,
            "identity": {
                "repository_identity": repository_identity,
                "relative_destination": relative_destination,
                "sha256": sha256,
            },
            "affected_requests": list(affected_requests),
            "classification": classification,
            "timestamp": time.time() if timestamp is None else timestamp,
        }
    )
    if record is None:
        return None
    return _upsert_record(project_key, record)


def publication_content_retry_allowed(
    project_key: str,
    *,
    repository_identity: str,
    relative_destination: str,
    sha256: str,
) -> bool:
    """Keep an exact blocked digest out of explicit and generic retry paths."""
    ledger = _read_publication_protection_ledger(project_key)
    return publication_protection_retry_allowed(
        ledger,
        _identity(repository_identity, relative_destination, sha256),
    )


def _upsert_record(
    project_key: str,
    record: dict[str, object],
) -> dict[str, object]:
    path = _ledger_path(project_key)
    with _ledger_lock(path):
        ledger = _read_ledger(path)
        updated = publication_protection_upsert(ledger, record)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, updated)
        return updated


def _resolve_verified_clean(
    project_key: str,
    identity: dict[str, object],
) -> dict[str, object]:
    path = _ledger_path(project_key)
    if not path.exists() and not path.is_symlink():
        # No persisted state: resolving a clean scan never creates ledger
        # directories, so clean drains leave protection state alone.
        return publication_protection_ledger_empty()
    with _ledger_lock(path):
        ledger = _read_ledger(path)
        updated = publication_protection_resolve_verified_clean(ledger, identity)
        if updated != ledger:
            if updated.get("records"):
                atomic_write_json(path, updated)
            else:
                path.unlink(missing_ok=True)
        return updated


def _read_ledger(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise RuntimeError("agent publication protection ledger cannot be a symlink")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return publication_protection_ledger_empty()
    except PublicationDrainTimedOut:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("agent publication protection ledger is unreadable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("agent publication protection ledger must be an object")
    try:
        return publication_protection_ledger_validate(payload)
    except PublicationDrainTimedOut:
        raise
    except Exception as exc:  # noqa: BLE001 - do not echo untrusted persisted values.
        raise RuntimeError("agent publication protection ledger is invalid") from exc


def _ledger_path(
    project_key: str,
    *,
    projects_root: Path | None = None,
) -> Path:
    validate_sase_project_name(project_key)
    root = sase_projects_dir() if projects_root is None else projects_root
    return root / project_key / AGENT_PUBLICATION_PROTECTION_FILENAME


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _identity(
    repository_identity: str,
    relative_destination: str,
    sha256: str,
) -> dict[str, object]:
    return {
        "repository_identity": repository_identity,
        "relative_destination": relative_destination,
        "sha256": sha256,
    }
