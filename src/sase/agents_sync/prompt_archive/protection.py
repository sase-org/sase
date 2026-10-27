"""Scan and withhold unsafe prompt-archive text through the shared adapter.

The attachment scanner cannot inspect binary content. Hash-named objects are
classified from their bytes (NUL or non-UTF-8 means nontext), never from a
suffix. Nontext objects keep the existing hash-checked copy path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.archive_objects import (
    canonical_archive_object_digest,
)
from sase.agents_sync.publication_protection import (
    PublicationBytesVerdict,
    PublicationProtectionScope,
    ScannedPublicationCandidate,
    lookup_publication_content_record,
    publication_content_retry_allowed,
    record_publication_bytes_scan,
    record_publication_scan,
    scan_publication_bytes,
    scan_publication_candidate,
)
from sase.core.artifact_file_helpers import hash_file
from sase.core.paths import sase_home, validate_sase_project_name
from sase.core.prompt_artifact_staging import PromptArtifactRecord
from sase.core.rust import require_rust_binding

PROMPT_PROTECTION_BLOCKED = "prompt archive withheld by publication protection"
PROMPT_PROTECTION_UNVERIFIED = "prompt archive could not be verified for publication"
PRIVATE_RECOVERY_DIRECTORY = "agents-publication-recovery"


@dataclass(frozen=True, slots=True)
class _ArchiveProtectionVerdict:
    """One archive candidate's protection decision, without matched bytes."""

    sha256: str | None
    status: str
    publishable: bool

    @property
    def withheld_reason(self) -> str | None:
        if self.publishable:
            return None
        if self.status == "blocked":
            return "blocked"
        return "unverified"


def protection_scope_for_target(
    target: ProjectTarget,
) -> PublicationProtectionScope:
    """Build the ledger identity the transcript publisher uses for this sidecar."""

    return PublicationProtectionScope(
        project_key=target.project_key,
        repository_identity=target.remote_url,
    )


def publication_text_bytes(data: bytes) -> bool:
    """Return whether *data* is UTF-8 text the scanner can inspect."""

    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def preserve_private_publication_object(
    *,
    project_key: str,
    sha256: str,
    source: Path | str,
) -> Path:
    """Copy a sole-copy object into private durable storage.

    A failed copy raises and must stop any cleanup of *source*. Success never
    authorizes publication; it only keeps the bytes recoverable.
    """

    validate_sase_project_name(project_key)
    digest = sha256.lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("private recovery object digest is invalid")
    origin = Path(source)
    if origin.is_symlink() or not origin.is_file():
        raise OSError("private recovery source must be a regular file")
    actual = hash_file(origin)
    if actual != digest:
        raise OSError("private recovery source digest does not match")
    private = sase_home() / "private"
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    if private.is_symlink():
        raise OSError("private recovery parent must not be a symlink")
    os.chmod(private, 0o700)
    root = private / PRIVATE_RECOVERY_DIRECTORY / project_key / digest[:2]
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise OSError("private recovery directory must not be a symlink")
    os.chmod(root, 0o700)
    destination = root / digest
    if destination.is_file() and not destination.is_symlink():
        if hash_file(destination) == digest:
            return destination
        raise OSError("private recovery object collision")
    tmp = destination.with_name(f".{digest}.tmp")
    try:
        with origin.open("rb") as src, tmp.open("xb") as out:
            os.chmod(tmp, 0o600)
            while chunk := src.read(1024 * 1024):
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if hash_file(tmp) != digest:
            raise OSError("private recovery copy changed while writing")
        os.replace(tmp, destination)
        os.chmod(destination, 0o600)
        return destination
    finally:
        tmp.unlink(missing_ok=True)


def scan_archive_text_bytes(
    data: bytes,
    *,
    scope: PublicationProtectionScope,
    relative_destination: str,
    affected_requests: tuple[str, ...] = (),
) -> _ArchiveProtectionVerdict:
    """Scan in-memory prompt or generated text and persist a non-clean decision."""

    digest = hashlib.sha256(data).hexdigest()
    prior = _prior_block(
        scope,
        relative_destination=relative_destination,
        sha256=digest,
    )
    if prior is not None:
        return prior
    verdict = scan_publication_bytes(data, max_bytes=scope.max_bytes)
    _record_bytes(scope, relative_destination, verdict, affected_requests)
    return _from_bytes_verdict(verdict, digest)


def scan_archive_text_file(
    path: Path,
    *,
    scope: PublicationProtectionScope,
    relative_destination: str,
    affected_requests: tuple[str, ...] = (),
) -> _ArchiveProtectionVerdict:
    """Scan one worktree text file through a private staged copy."""

    try:
        digest = hash_file(path)
    except OSError:
        return _ArchiveProtectionVerdict(None, "unverified", False)
    prior = _prior_block(
        scope,
        relative_destination=relative_destination,
        sha256=digest,
    )
    if prior is not None:
        return prior
    with scan_publication_candidate(path, max_bytes=scope.max_bytes) as candidate:
        _record_file(scope, relative_destination, candidate, affected_requests)
        return _from_file_candidate(candidate, digest)


def _copy_publishable_text_object(
    source: Path,
    destination: Path,
    *,
    expected_digest: str,
    scope: PublicationProtectionScope,
    relative_destination: str,
    affected_requests: tuple[str, ...] = (),
) -> _ArchiveProtectionVerdict:
    """Copy a scanned text object only after a complete clean scan."""

    prior = _prior_block(
        scope,
        relative_destination=relative_destination,
        sha256=expected_digest,
    )
    if prior is not None:
        return prior
    with scan_publication_candidate(source, max_bytes=scope.max_bytes) as candidate:
        _record_file(scope, relative_destination, candidate, affected_requests)
        verdict = _from_file_candidate(candidate, expected_digest)
        if not verdict.publishable:
            return verdict
        if candidate.sha256 != expected_digest:
            return _ArchiveProtectionVerdict(candidate.sha256, "unverified", False)
        if destination.exists():
            try:
                if hash_file(destination) == expected_digest:
                    return verdict
            except OSError:
                return _ArchiveProtectionVerdict(expected_digest, "unverified", False)
            raise RuntimeError(f"prompt artifact digest collision at {destination}")
        candidate.copy_verified_to(destination)
        return verdict


def unstage_unpublishable_archive_paths(
    repo: Path,
    git_runner: GitRunner,
    *,
    scope: PublicationProtectionScope,
    archive_paths: tuple[str, ...],
) -> str | None:
    """Leave blocked or unverified archive blobs out of the index.

    Private preservation runs before any unstage of a ``files/objects`` path.
    A preserve failure stops that mutation and keeps the worktree copy.
    """

    candidates = _dirty_archive_paths(repo, git_runner, archive_paths)
    if isinstance(candidates, str):
        return candidates
    blocked: list[str] = []
    for relative in candidates:
        path = repo / relative
        if path.is_symlink():
            return (
                "prompt archive failed protection verification: "
                f"unsupported symlink at {relative!r}"
            )
        if not path.is_file():
            continue
        object_digest = canonical_archive_object_digest(relative)
        try:
            data = path.read_bytes()
        except OSError:
            return (
                "prompt archive failed protection verification: "
                f"could not read {relative!r}"
            )
        if object_digest is not None:
            try:
                actual = hash_file(path)
            except OSError:
                return (
                    "prompt archive failed protection verification: "
                    f"could not hash {relative!r}"
                )
            if actual != object_digest:
                # Hash validity is an independent invariant; invalid pending
                # objects are quarantined elsewhere. A tracked mismatch stays.
                continue
            if not publication_text_bytes(data):
                continue
        elif not publication_text_bytes(data):
            # Generated prompt/index text must be UTF-8; binary here is unverified.
            blocked.append(relative)
            continue
        verdict = scan_archive_text_bytes(
            data,
            scope=scope,
            relative_destination=relative,
        )
        if verdict.publishable:
            continue
        if object_digest is not None:
            try:
                preserve_private_publication_object(
                    project_key=scope.project_key,
                    sha256=object_digest,
                    source=path,
                )
            except (OSError, ValueError):
                return (
                    "prompt archive failed protection verification: "
                    f"could not preserve withheld object {relative!r}"
                )
        blocked.append(relative)
    if not blocked:
        return None
    reset = git_runner(
        repo,
        ["reset", "--quiet", "HEAD", "--", *blocked],
        op="agents_sync.prompt_archive_protection_unstage",
    )
    if reset.returncode != 0:
        detail = (reset.stderr or reset.stdout or "unknown git error").strip()
        return f"could not unstage withheld prompt archive paths: {detail}"
    return None


def filter_publishable_pool_records(
    records: tuple[PromptArtifactRecord, ...],
    *,
    source_for: Callable[[PromptArtifactRecord], Path | None],
    repo: Path,
    scope: PublicationProtectionScope,
    affected_requests: tuple[str, ...] = (),
) -> tuple[tuple[PromptArtifactRecord, ...], tuple[Path, ...]]:
    """Copy clean textual and binary pool objects; drop withheld text objects."""

    accepted: list[PromptArtifactRecord] = []
    copied: list[Path] = []
    for record in records:
        source = source_for(record)
        if source is None:
            accepted.append(record)
            continue
        expected = record.get("sha256")
        if not isinstance(expected, str) or hash_file(source) != expected:
            raise RuntimeError(f"prompt artifact digest mismatch: {source}")
        destination = repo / str(
            require_rust_binding("artifact_object_relpath")(expected)
        )
        relative = destination.relative_to(repo).as_posix()
        data = Path(source).read_bytes()
        if not publication_text_bytes(data):
            _copy_binary_object(Path(source), destination, expected)
            copied.append(destination)
            accepted.append(record)
            continue
        verdict = _copy_publishable_text_object(
            Path(source),
            destination,
            expected_digest=expected,
            scope=scope,
            relative_destination=relative,
            affected_requests=affected_requests,
        )
        if not verdict.publishable:
            continue
        copied.append(destination)
        accepted.append(record)
    return tuple(accepted), tuple(copied)


def _copy_binary_object(source: Path, target: Path, digest: str) -> None:
    """Keep existing nontext media handling, separate from a text scan."""

    if target.exists():
        if hash_file(target) != digest:
            raise RuntimeError(f"prompt artifact digest collision at {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        with source.open("rb") as src, tmp.open("xb") as out:
            while chunk := src.read(1024 * 1024):
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if hash_file(tmp) != digest:
            raise RuntimeError(f"prompt artifact changed while publishing: {source}")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _prior_block(
    scope: PublicationProtectionScope,
    *,
    relative_destination: str,
    sha256: str,
) -> _ArchiveProtectionVerdict | None:
    try:
        record = lookup_publication_content_record(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=relative_destination,
            sha256=sha256,
        )
    except Exception:  # noqa: BLE001 - a failed lookup never authorizes publish.
        return _ArchiveProtectionVerdict(sha256, "unverified", False)
    if record is None:
        return None
    if record.get("status") == "blocked":
        return _ArchiveProtectionVerdict(sha256, "blocked", False)
    try:
        if not publication_content_retry_allowed(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=relative_destination,
            sha256=sha256,
        ):
            return _ArchiveProtectionVerdict(sha256, "blocked", False)
    except Exception:  # noqa: BLE001 - a failed retry decision never publishes.
        return _ArchiveProtectionVerdict(sha256, "unverified", False)
    return None


def _record_bytes(
    scope: PublicationProtectionScope,
    relative_destination: str,
    verdict: PublicationBytesVerdict,
    affected_requests: tuple[str, ...],
) -> None:
    try:
        record_publication_bytes_scan(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=relative_destination,
            verdict=verdict,
            affected_requests=affected_requests,
        )
    except Exception:  # noqa: BLE001 - the scan verdict still withholds.
        return


def _record_file(
    scope: PublicationProtectionScope,
    relative_destination: str,
    candidate: ScannedPublicationCandidate,
    affected_requests: tuple[str, ...],
) -> None:
    try:
        record_publication_scan(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=relative_destination,
            candidate=candidate,
            affected_requests=affected_requests,
        )
    except Exception:  # noqa: BLE001 - the scan verdict still withholds.
        return


def _from_bytes_verdict(
    verdict: PublicationBytesVerdict, digest: str
) -> _ArchiveProtectionVerdict:
    status = (
        str(verdict.disposition.get("status"))
        if verdict.disposition and verdict.disposition.get("status")
        else "unverified"
    )
    return _ArchiveProtectionVerdict(
        verdict.sha256 or digest, status, verdict.is_publishable
    )


def _from_file_candidate(
    candidate: ScannedPublicationCandidate, digest: str
) -> _ArchiveProtectionVerdict:
    status = (
        str(candidate.disposition.get("status"))
        if candidate.disposition and candidate.disposition.get("status")
        else "unverified"
    )
    return _ArchiveProtectionVerdict(
        candidate.sha256 or digest, status, candidate.is_publishable
    )


def _dirty_archive_paths(
    repo: Path,
    git_runner: GitRunner,
    archive_paths: tuple[str, ...],
) -> tuple[str, ...] | str:
    existing = tuple(
        path
        for path in archive_paths
        if (repo / path).exists() or _tracked_path(repo, path, git_runner)
    )
    if not existing:
        return ()
    status = git_runner(
        repo,
        ["status", "--porcelain=v1", "-z", "--", *existing],
        op="agents_sync.prompt_archive_protection_status",
    )
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "unknown git error").strip()
        return f"could not inspect prompt archive worktree for protection: {detail}"
    changed: list[str] = []
    tokens = status.stdout.split("\0") if status.stdout else []
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            return (
                "prompt archive failed protection verification: "
                "could not parse worktree status"
            )
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC" or y in "RC":
            if index < len(tokens) and tokens[index]:
                changed.append(tokens[index])
                index += 1
        if x == "U" or y == "U" or x == "A" and y == "A":
            return (
                "prompt archive failed protection verification: "
                f"could not verify conflicted file at {path!r}"
            )
        if y == "D":
            continue
        if path:
            changed.append(path)
    return tuple(dict.fromkeys(changed))


def _tracked_path(repo: Path, path: str, git_runner: GitRunner) -> bool:
    tracked = git_runner(
        repo,
        ["ls-files", "--", path],
        op="agents_sync.prompt_archive_protection_tracked",
    )
    return tracked.returncode == 0 and bool(tracked.stdout.strip())


def protection_skip_reason(status: str) -> str:
    """Return the durable, value-free skip reason for a withheld prompt."""

    if status == "blocked":
        return PROMPT_PROTECTION_BLOCKED
    return PROMPT_PROTECTION_UNVERIFIED


def should_charge_prompt_protection_failure(error: str) -> bool:
    """Blocked content is parked; unverified and other failures stay retryable."""

    return error != PROMPT_PROTECTION_BLOCKED


__all__ = [
    "PRIVATE_RECOVERY_DIRECTORY",
    "PROMPT_PROTECTION_BLOCKED",
    "PROMPT_PROTECTION_UNVERIFIED",
    "filter_publishable_pool_records",
    "preserve_private_publication_object",
    "protection_scope_for_target",
    "protection_skip_reason",
    "publication_text_bytes",
    "scan_archive_text_bytes",
    "scan_archive_text_file",
    "should_charge_prompt_protection_failure",
    "unstage_unpublishable_archive_paths",
]
