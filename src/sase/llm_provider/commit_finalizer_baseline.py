"""Pre-existing repository baseline capture for commit finalization.

``finalizer_baseline.json`` records repository dirt that predates work this
run owns. A ``run_start`` record is captured before the agent's first turn; an
``opened_repo`` record is captured before the run first contacts a repository
whose checkout was not part of the run-start snapshot. Both scopes are
legitimate "not this run's work" evidence.

All current readers go through :func:`load_finalizer_baseline_records`, which
keeps the record scope intact and canonicalizes duplicate repository paths.
When a run-start and opened-repo record name the same normalized path, the
run-start record wins because it was captured earlier by contract. Same-scope
legacy duplicates have no capture metadata, so they fall back to a stable
repo-id tie-breaker instead of depending on JSON list order.

``commit_finalizer_baseline.json`` is a historical read-only fallback for
archived agents; new code never writes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import json
import logging
import os
from pathlib import Path
import subprocess
from typing import Any

from .commit_finalizer_git import dirty_path_fingerprints, normalize_path
from sase.memory.locks import locked_file

_logger = logging.getLogger(__name__)

BASELINE_FILENAME = "commit_finalizer_baseline.json"
FINALIZER_BASELINE_FILENAME = "finalizer_baseline.json"

DirtyBaseline = dict[str, dict[str, tuple[str, str | None]]]

_BASELINE_SCOPE_RUN_START = "run_start"
_BASELINE_SCOPE_OPENED_REPO = "opened_repo"
_BASELINE_SCOPE_PRECEDENCE = {
    _BASELINE_SCOPE_RUN_START: 0,
    _BASELINE_SCOPE_OPENED_REPO: 1,
}


@dataclass(frozen=True)
class FinalizerBaselineRecord:
    """One canonical ``finalizer_baseline.json`` repository record."""

    repo_id: str
    path: str
    kind: str
    name: str
    scope: str
    fingerprints: dict[str, tuple[str, str | None]]
    captured_at: str | None = None
    head: str | None = None


def capture_dirty_baseline(project_dir: str, artifacts_dir: str) -> None:
    """Snapshot pre-existing repository checkouts before this agent's first turn.

    Best-effort only: any failure leaves no baseline file on disk, which
    makes the finalizer behave exactly as it did before baselines existed.
    """
    try:
        from .commit_finalizer_state import collect_baseline_repositories

        baseline_repos = collect_baseline_repositories(project_dir)
        records = [
            _baseline_record(
                repo_id=_repo_id(repo.kind, repo.name, repo.path),
                repo_path=repo.path,
                kind=repo.kind,
                name=repo.name,
                scope=_BASELINE_SCOPE_RUN_START,
            )
            for repo in baseline_repos
        ]
        _write_dirty_baseline_records(Path(artifacts_dir), records)
    except Exception:
        _logger.warning(
            "Failed to capture commit finalizer dirty-path baseline", exc_info=True
        )


def bind_run_start_baseline_to_workspace(
    project_dir: str,
    artifacts_dir: str,
    *,
    inherited: bool,
) -> None:
    """Rebind run-start baseline records to the checkout this run actually uses.

    Bootstrap may capture ``finalizer_baseline.json`` against a placeholder
    workspace (deferred claim) or inherit a parent's stale ``main`` path.
    After launch preparation claims the real workspace, this helper rebuilds
    ``run_start`` records from :func:`collect_baseline_repositories` for
    that checkout.

    When *inherited* is true, fingerprints are emptied so a parent's
    still-uncommitted work is this run's to commit. When false, fingerprints
    and ``head`` are captured fresh, matching :func:`capture_dirty_baseline`.

    Best-effort only: never raises. No-ops when *project_dir* is not a git
    checkout, or when a ``run_start`` ``main`` record already names that
    checkout.
    """
    try:
        _bind_run_start_baseline_to_workspace(
            project_dir, artifacts_dir, inherited=inherited
        )
    except Exception:
        _logger.warning(
            "Failed to bind commit finalizer run-start baseline to workspace",
            exc_info=True,
        )


def capture_opened_repo_dirty_baseline(
    repo_id: str,
    repo_path: str,
    *,
    kind: str,
    name: str,
    artifacts_dir: str | None = None,
) -> str | None:
    """Atomically add a late-opened repository to this run's baseline.

    Returns ``None`` on success and a diagnostic string on failure. The first
    baseline for a repository ID wins, so repeated opens cannot rebase the
    already-protected dirt.
    """

    root_value = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not root_value:
        return None
    root = Path(root_value).expanduser().resolve(strict=False)
    normalized_repo_path = normalize_path(repo_path)
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / f"{FINALIZER_BASELINE_FILENAME}.lock"
        with locked_file(lock_path, fcntl.LOCK_EX):
            payload = _read_finalizer_baseline_payload(root)
            records = {
                str(item.get("repo_id")): dict(item)
                for item in payload.get("repositories", [])
                if isinstance(item, dict) and isinstance(item.get("repo_id"), str)
            }
            existing = records.get(repo_id)
            if existing is not None:
                existing_path = normalize_path(str(existing.get("path", "")))
                if existing_path != normalized_repo_path:
                    return (
                        f"repository baseline {repo_id!r} already points at "
                        f"{existing_path}; refusing to recapture {normalized_repo_path}"
                    )
                return None
            if any(
                normalize_path(str(existing.get("path", ""))) == normalized_repo_path
                for existing in records.values()
            ):
                return None
            record = _baseline_record(
                repo_id=repo_id,
                repo_path=normalized_repo_path,
                kind=kind,
                name=name,
                scope=_BASELINE_SCOPE_OPENED_REPO,
            )
            records[repo_id] = record
            _write_finalizer_baseline_payload(root, list(records.values()))
    except Exception as exc:
        _logger.warning("Failed to capture opened repo dirty baseline", exc_info=True)
        return f"{type(exc).__name__}: {exc}"
    return None


def load_dirty_baseline(artifact_root: Path | None) -> DirtyBaseline | None:
    """Load the baseline evidence for callers that only need fingerprints.

    New runs write ``finalizer_baseline.json``. ``commit_finalizer_baseline.json``
    is a historical-only reader for archived agents; this function never writes
    that filename.

    Returns ``None`` on a missing, unreadable, or malformed baseline file so
    callers degrade to pre-baseline behavior rather than raising.
    """
    if artifact_root is None:
        return None
    records = load_finalizer_baseline_records(Path(artifact_root))
    if records is not None:
        return {record.path: dict(record.fingerprints) for record in records}
    return _load_legacy_dirty_baseline(Path(artifact_root))


def load_finalizer_baseline_records(
    artifact_root: Path | None,
) -> tuple[FinalizerBaselineRecord, ...] | None:
    """Load canonical ``finalizer_baseline.json`` records, if present.

    The returned records preserve ``scope`` and contain at most one record per
    normalized repository path. Missing, unreadable, or malformed files return
    ``None`` so callers can fall back to legacy behavior or no-baseline
    behavior.
    """
    if artifact_root is None:
        return None
    try:
        payload = json.loads(
            (Path(artifact_root) / FINALIZER_BASELINE_FILENAME).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        return None
    records = payload.get("repositories")
    if not isinstance(records, list):
        return None

    parsed: list[FinalizerBaselineRecord] = []
    for item in records:
        record = _parse_finalizer_baseline_record(item)
        if record is None:
            return None
        parsed.append(record)
    return _canonical_baseline_records(parsed)


def _load_legacy_dirty_baseline(artifact_root: Path) -> DirtyBaseline | None:
    """Read archived ``commit_finalizer_baseline.json`` files; never a writer."""
    try:
        raw = (artifact_root / BASELINE_FILENAME).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    baseline: DirtyBaseline = {}
    for repo_path, entries in data.items():
        if not isinstance(repo_path, str) or not isinstance(entries, dict):
            return None
        repo_entries: dict[str, tuple[str, str | None]] = {}
        for path, fingerprint in entries.items():
            if not _is_valid_fingerprint_entry(path, fingerprint):
                return None
            repo_entries[path] = (fingerprint[0], fingerprint[1])
        baseline[repo_path] = repo_entries
    return baseline


def _parse_finalizer_baseline_record(
    item: object,
) -> FinalizerBaselineRecord | None:
    if not isinstance(item, Mapping):
        return None
    repo_id = item.get("repo_id")
    repo_path = item.get("path")
    kind = item.get("kind")
    name = item.get("name")
    scope = item.get("scope")
    raw_fingerprints = item.get("fingerprints")
    captured_at = item.get("captured_at")
    head = item.get("head")
    if not (
        isinstance(repo_id, str)
        and isinstance(repo_path, str)
        and isinstance(kind, str)
        and isinstance(name, str)
        and isinstance(scope, str)
        and scope in _BASELINE_SCOPE_PRECEDENCE
        and isinstance(raw_fingerprints, Mapping)
        and (captured_at is None or isinstance(captured_at, str))
        and (head is None or isinstance(head, str))
    ):
        return None
    fingerprints = _normalize_fingerprints(raw_fingerprints)
    if fingerprints is None:
        return None
    return FinalizerBaselineRecord(
        repo_id=repo_id,
        path=normalize_path(repo_path),
        kind=kind,
        name=name,
        scope=scope,
        fingerprints=fingerprints,
        captured_at=captured_at,
        head=head,
    )


def _normalize_fingerprints(
    raw: Mapping[object, object],
) -> dict[str, tuple[str, str | None]] | None:
    normalized: dict[str, tuple[str, str | None]] = {}
    for path, fingerprint in raw.items():
        if not (
            isinstance(path, str)
            and isinstance(fingerprint, list)
            and len(fingerprint) == 2
            and isinstance(fingerprint[0], str)
            and (fingerprint[1] is None or isinstance(fingerprint[1], str))
        ):
            return None
        normalized[path] = (fingerprint[0], fingerprint[1])
    return normalized


def _canonical_baseline_records(
    records: list[FinalizerBaselineRecord],
) -> tuple[FinalizerBaselineRecord, ...]:
    selected: dict[str, FinalizerBaselineRecord] = {}
    for record in records:
        existing = selected.get(record.path)
        if existing is None:
            selected[record.path] = record
            continue
        if _baseline_record_sort_key(record) < _baseline_record_sort_key(existing):
            selected[record.path] = record
    return tuple(
        sorted(
            selected.values(),
            key=lambda record: (record.path, _baseline_record_sort_key(record)),
        )
    )


def _baseline_record_sort_key(
    record: FinalizerBaselineRecord,
) -> tuple[int, str, str]:
    return (
        _BASELINE_SCOPE_PRECEDENCE[record.scope],
        record.captured_at or "",
        record.repo_id,
    )


def _is_valid_fingerprint_entry(path: object, fingerprint: object) -> bool:
    return (
        isinstance(path, str)
        and isinstance(fingerprint, list)
        and len(fingerprint) == 2
        and isinstance(fingerprint[0], str)
        and (fingerprint[1] is None or isinstance(fingerprint[1], str))
    )


def _repo_id(kind: str, name: str, repo_path: str) -> str:
    if name:
        return f"{kind}:{name}"
    return f"{kind}:{normalize_path(repo_path)}"


def _bind_run_start_baseline_to_workspace(
    project_dir: str,
    artifacts_dir: str,
    *,
    inherited: bool,
) -> None:
    project_path = Path(project_dir).expanduser()
    if not (project_path / ".git").exists():
        return
    normalized_project = normalize_path(str(project_path))
    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / f"{FINALIZER_BASELINE_FILENAME}.lock"
    with locked_file(lock_path, fcntl.LOCK_EX):
        payload = _read_finalizer_baseline_payload(root)
        raw_records = [
            item for item in payload.get("repositories", []) if isinstance(item, dict)
        ]
        if _run_start_main_matches(raw_records, normalized_project):
            return
        from .commit_finalizer_state import collect_baseline_repositories

        baseline_repos = collect_baseline_repositories(str(project_path))
        fingerprints: dict[str, tuple[str, str | None]] | None
        fingerprints = {} if inherited else None
        run_start_records = [
            _baseline_record(
                repo_id=_repo_id(repo.kind, repo.name, repo.path),
                repo_path=repo.path,
                kind=repo.kind,
                name=repo.name,
                scope=_BASELINE_SCOPE_RUN_START,
                fingerprints=fingerprints,
            )
            for repo in baseline_repos
        ]
        kept_opened = [
            item
            for item in raw_records
            if item.get("scope") == _BASELINE_SCOPE_OPENED_REPO
            and _path_is_inside(str(item.get("path", "")), normalized_project)
        ]
        _write_finalizer_baseline_payload(root, [*run_start_records, *kept_opened])


def _run_start_main_matches(records: list[dict[str, Any]], project_path: str) -> bool:
    return any(
        item.get("scope") == _BASELINE_SCOPE_RUN_START
        and item.get("kind") == "main"
        and normalize_path(str(item.get("path", ""))) == project_path
        for item in records
    )


def _path_is_inside(child: str, parent: str) -> bool:
    if not child:
        return False
    child_path = Path(normalize_path(child))
    parent_path = Path(normalize_path(parent))
    if child_path == parent_path:
        return True
    try:
        child_path.relative_to(parent_path)
    except ValueError:
        return False
    return True


def _baseline_record(
    *,
    repo_id: str,
    repo_path: str,
    kind: str,
    name: str,
    scope: str,
    fingerprints: Mapping[str, tuple[str, str | None]] | None = None,
) -> dict[str, Any]:
    path = normalize_path(repo_path)
    fingerprint_items = (
        dirty_path_fingerprints(path) if fingerprints is None else fingerprints
    )
    return {
        "repo_id": repo_id,
        "path": path,
        "kind": kind,
        "name": name,
        "scope": scope,
        "captured_at": datetime.now(UTC).isoformat(),
        "head": _baseline_head(path),
        "fingerprints": {
            item_path: list(fingerprint)
            for item_path, fingerprint in fingerprint_items.items()
        },
    }


def _baseline_head(repo_path: str) -> str | None:
    """Return *repo_path*'s HEAD sha, or ``None`` when it cannot be read.

    Best-effort only: an unborn HEAD, a corrupt checkout, or a git failure
    records ``null`` so raw-commit detection is skipped for the repo instead
    of failing the baseline capture.
    """

    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _write_dirty_baseline_records(
    root: Path,
    records: list[dict[str, Any]],
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / f"{FINALIZER_BASELINE_FILENAME}.lock"
    with locked_file(lock_path, fcntl.LOCK_EX):
        _write_finalizer_baseline_payload(root, records)


def _read_finalizer_baseline_payload(root: Path) -> dict[str, Any]:
    try:
        payload = json.loads((root / FINALIZER_BASELINE_FILENAME).read_text())
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "repositories": []}
    if not isinstance(payload, dict) or not isinstance(
        payload.get("repositories"), list
    ):
        return {"schema_version": 1, "repositories": []}
    return payload


def _write_finalizer_baseline_payload(
    root: Path,
    records: list[dict[str, Any]],
) -> None:
    payload = {
        "schema_version": 1,
        "repositories": sorted(records, key=lambda item: str(item.get("repo_id", ""))),
    }
    _write_json_atomic(root / FINALIZER_BASELINE_FILENAME, payload)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
