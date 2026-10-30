"""Private state and fail-closed scanner adapter for agents publication."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
from typing import Any

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.v2_validation import MAX_TEXT_BYTES
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
    publication_scan_disposition,
)
from sase.core.paths import (
    sase_home,
    sase_projects_dir,
    validate_sase_project_name,
)

AGENT_PUBLICATION_PROTECTION_FILENAME = "agents-publication-protection.json"
PRIVATE_SCAN_STAGING_DIRECTORY = "agents-publication-scans"

# Bound for one in-memory publication candidate. Matches the v2 text limit so
# oversized text is withheld as unverified instead of raising scanner limits.
MAX_PUBLICATION_SCAN_BYTES = MAX_TEXT_BYTES


@dataclass(frozen=True, slots=True)
class PublicationBytesVerdict:
    """One in-memory candidate's digest and scan decision.

    Callers must only publish the exact bytes this verdict was computed from
    after checking :attr:`is_publishable`.
    """

    sha256: str | None
    byte_count: int | None
    disposition: dict[str, object] | None

    @property
    def is_publishable(self) -> bool:
        return (
            self.sha256 is not None
            and self.disposition is not None
            and self.disposition.get("status") == "clean"
        )


@dataclass(frozen=True, slots=True)
class PublicationProtectionScope:
    """Project-scoped identity for protection ledger reads and writes."""

    project_key: str
    repository_identity: str
    max_bytes: int = MAX_PUBLICATION_SCAN_BYTES


@dataclass(frozen=True, slots=True)
class ScannedPublicationCandidate:
    """One private candidate copy and its scan decision.

    Keep this object inside ``_scan_publication_candidate``'s context. A
    publisher may only copy the private staged bytes after a clean scan.
    """

    staged_path: Path | None
    sha256: str | None
    byte_count: int | None
    disposition: dict[str, object] | None

    @property
    def is_publishable(self) -> bool:
        return (
            self.staged_path is not None
            and self.sha256 is not None
            and self.disposition is not None
            and self.disposition.get("status") == "clean"
        )

    def copy_verified_to(self, destination: Path | str) -> Path:
        """Write the exact scanned bytes and verify the copied digest."""
        if not self.is_publishable or self.staged_path is None or self.sha256 is None:
            raise RuntimeError(
                "publication candidate did not pass a complete text scan"
            )
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".scan.tmp", dir=target.parent
        )
        temp_path = Path(name)
        try:
            with os.fdopen(fd, "wb") as output, self.staged_path.open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            copied_digest = _sha256_file(temp_path)
            if copied_digest != self.sha256:
                raise RuntimeError(
                    "staged publication candidate changed after scanning"
                )
            os.replace(temp_path, target)
            return target
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


@contextmanager
def scan_publication_candidate(
    source: Path | str,
    *,
    max_bytes: int,
    env: dict[str, str] | None = None,
) -> Iterator[ScannedPublicationCandidate]:
    """Copy and scan text privately; only the yielded copy can be published.

    Callers use this only for text. Binary media needs its existing explicit
    media handling because the attachment scanner intentionally skips binary
    bytes. Oversized input is hashed with bounded memory and withheld as
    unverified; the scanner limit is never increased.
    """
    path = Path(source)
    try:
        staging_root = _private_scan_root()
    except PublicationDrainTimedOut:
        raise
    except OSError:
        yield _unverified_candidate(None, None, None, "scan_error")
        return
    with tempfile.TemporaryDirectory(prefix="candidate-", dir=staging_root) as temp_dir:
        staged_path = Path(temp_dir) / "candidate"
        try:
            source_fd = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
        except PublicationDrainTimedOut:
            raise
        except OSError:
            yield _unverified_candidate(None, None, None, "scan_error")
            return
        try:
            source_stat = os.fstat(source_fd)
        except PublicationDrainTimedOut:
            raise
        except OSError:
            os.close(source_fd)
            yield _unverified_candidate(None, None, None, "scan_error")
            return
        if not stat.S_ISREG(source_stat.st_mode):
            os.close(source_fd)
            yield _unverified_candidate(None, None, None, "scan_error")
            return

        if source_stat.st_size > max_bytes:
            try:
                oversize_digest = _hash_open_file(source_fd)
            except PublicationDrainTimedOut:
                raise
            except OSError:
                os.close(source_fd)
                yield _unverified_candidate(None, None, None, "scan_error")
                return
            finally:
                try:
                    os.close(source_fd)
                except PublicationDrainTimedOut:
                    raise
                except OSError:
                    pass
            scan_result, scan_failure = _scan_file(
                path,
                max_bytes=max_bytes,
                env=env,
            )
            if scan_result is not None and scan_result.get("outcome") == "skipped":
                disposition = _disposition(scan=scan_result)
            else:
                disposition = _disposition(failure=scan_failure or "scan_error")
            yield ScannedPublicationCandidate(
                None, oversize_digest, source_stat.st_size, disposition
            )
            return

        digest = hashlib.sha256()
        byte_count = 0
        try:
            with (
                os.fdopen(source_fd, "rb") as source_file,
                staged_path.open("xb") as target,
            ):
                os.chmod(staged_path, 0o600)
                while chunk := source_file.read(1024 * 1024):
                    target.write(chunk)
                    digest.update(chunk)
                    byte_count += len(chunk)
                target.flush()
                os.fsync(target.fileno())
        except PublicationDrainTimedOut:
            raise
        except OSError:
            yield _unverified_candidate(None, None, None, "scan_error")
            return

        digest_hex = digest.hexdigest()
        scan_result, scan_failure = _scan_file(
            staged_path,
            max_bytes=max_bytes,
            env=env,
        )
        try:
            unchanged = _sha256_file(staged_path) == digest_hex
        except PublicationDrainTimedOut:
            raise
        except OSError:
            unchanged = False
        if not unchanged:
            disposition = _disposition(failure="scan_error")
        elif scan_result is None:
            disposition = _disposition(failure=scan_failure or "scan_error")
        elif scan_result.get("outcome") == "clean":
            if scan_result.get("bytes_scanned") == byte_count:
                disposition = _disposition(scan=scan_result)
            else:
                disposition = _disposition(failure="scan_error")
        else:
            disposition = _disposition(scan=scan_result)
        yield ScannedPublicationCandidate(
            staged_path,
            digest_hex,
            byte_count,
            disposition,
        )


def scan_publication_bytes(
    data: bytes,
    *,
    max_bytes: int,
    env: dict[str, str] | None = None,
) -> PublicationBytesVerdict:
    """Scan in-memory publication bytes through a private staged copy.

    Oversized input is hashed with bounded memory and withheld as unverified;
    the scanner limit is never raised to publish oversized text. A missing
    binding, scan error, or skipped result is unverified, never clean.
    """

    digest_hex = hashlib.sha256(data).hexdigest()
    if len(data) > max_bytes:
        return PublicationBytesVerdict(
            digest_hex, len(data), _disposition(failure="scan_error")
        )
    try:
        staging_root = _private_scan_root()
    except PublicationDrainTimedOut:
        raise
    except OSError:
        return PublicationBytesVerdict(
            digest_hex, len(data), _disposition(failure="scan_error")
        )
    with tempfile.TemporaryDirectory(prefix="bytes-", dir=staging_root) as temp_dir:
        staged_path = Path(temp_dir) / "candidate"
        try:
            with staged_path.open("xb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(staged_path, 0o600)
        except PublicationDrainTimedOut:
            raise
        except OSError:
            return PublicationBytesVerdict(
                digest_hex, len(data), _disposition(failure="scan_error")
            )
        scan_result, scan_failure = _scan_file(
            staged_path,
            max_bytes=max_bytes,
            env=env,
        )
        try:
            unchanged = _sha256_file(staged_path) == digest_hex
        except PublicationDrainTimedOut:
            raise
        except OSError:
            unchanged = False
        if not unchanged:
            disposition = _disposition(failure="scan_error")
        elif scan_result is None:
            disposition = _disposition(failure=scan_failure or "scan_error")
        elif scan_result.get("outcome") == "clean":
            if scan_result.get("bytes_scanned") == len(data):
                disposition = _disposition(scan=scan_result)
            else:
                disposition = _disposition(failure="scan_error")
        else:
            disposition = _disposition(scan=scan_result)
        return PublicationBytesVerdict(digest_hex, len(data), disposition)


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


def _private_scan_root() -> Path:
    private = sase_home() / "private"
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    if private.is_symlink():
        raise OSError("private scan parent must not be a symlink")
    os.chmod(private, 0o700)
    root = private / PRIVATE_SCAN_STAGING_DIRECTORY
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise OSError("private scan directory must not be a symlink")
    os.chmod(root, 0o700)
    return root


def _scan_file(
    path: Path,
    *,
    max_bytes: int,
    env: dict[str, str] | None,
) -> tuple[dict[str, object] | None, str | None]:
    try:
        from sase.core.rust import require_rust_binding

        binding = require_rust_binding("attachment_scan_file")
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - a missing binding never authorizes publish.
        return None, "scanner_unavailable"
    try:
        home = str(Path.home())
        try:
            from sase.core.paths import sase_home as current_sase_home

            sase_home_path = str(current_sase_home())
        except PublicationDrainTimedOut:
            raise
        except Exception:  # noqa: BLE001 - an unavailable home is no scan context.
            sase_home_path = str(Path.home() / ".sase")
        capture = dict(os.environ) if env is None else dict(env)
        result = binding(str(path), max_bytes, capture, home, sase_home_path)
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - scanner failure must withhold content.
        return None, "scan_error"
    if not isinstance(result, dict):
        return None, "scan_error"
    return dict(result), None


def _disposition(
    *,
    scan: dict[str, object] | None = None,
    failure: str | None = None,
) -> dict[str, object] | None:
    try:
        return publication_scan_disposition(scan=scan, failure=failure)
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - missing policy binding also withholds.
        return None


def _unverified_candidate(
    staged_path: Path | None,
    sha256: str | None,
    byte_count: int | None,
    failure: str,
) -> ScannedPublicationCandidate:
    return ScannedPublicationCandidate(
        staged_path,
        sha256,
        byte_count,
        _disposition(failure=failure),
    )


def _hash_open_file(handle: int) -> str:
    os.lseek(handle, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(handle, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


__all__ = [
    "AGENT_PUBLICATION_PROTECTION_FILENAME",
    "MAX_PUBLICATION_SCAN_BYTES",
    "PRIVATE_SCAN_STAGING_DIRECTORY",
    "PublicationBytesVerdict",
    "PublicationProtectionScope",
    "ScannedPublicationCandidate",
    "lookup_publication_content_record",
    "publication_content_retry_allowed",
    "read_publication_protection_ledger_from_path",
    "record_publication_bytes_scan",
    "record_publication_push_rejection",
    "record_publication_scan",
    "scan_publication_bytes",
    "scan_publication_candidate",
]
