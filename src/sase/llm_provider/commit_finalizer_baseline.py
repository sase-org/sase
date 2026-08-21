"""Pre-existing dirty-path baseline capture for commit finalization.

Captured once at runner start, before the agent's first turn, so later
finalizer passes can tell paths that were already dirty in the workspace
apart from paths this agent's own run touched, and stop attributing
pre-existing dirt to the agent (bead sase-lb.1.6).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Any

from .commit_finalizer_git import dirty_path_fingerprints, normalize_path
from sase.memory.locks import locked_file

_logger = logging.getLogger(__name__)

BASELINE_FILENAME = "commit_finalizer_baseline.json"
FINALIZER_BASELINE_FILENAME = "finalizer_baseline.json"

DirtyBaseline = dict[str, dict[str, tuple[str, "str | None"]]]

_BASELINE_SCOPE_RUN_START = "run_start"
_BASELINE_SCOPE_OPENED_REPO = "opened_repo"


def capture_dirty_baseline(project_dir: str, artifacts_dir: str) -> None:
    """Snapshot already-dirty paths before this agent's first turn.

    Best-effort only: any failure leaves no baseline file on disk, which
    makes the finalizer behave exactly as it did before baselines existed.
    """
    try:
        from .commit_finalizer_state import collect_dirty_state

        dirty_state = collect_dirty_state(
            project_dir, artifact_root=Path(artifacts_dir)
        )
        records = [
            _baseline_record(
                repo_id=_repo_id(repo.kind, repo.name, repo.path),
                repo_path=repo.path,
                kind=repo.kind,
                name=repo.name,
                scope=_BASELINE_SCOPE_RUN_START,
            )
            for repo in dirty_state.repos
        ]
        _write_dirty_baseline_records(Path(artifacts_dir), records)
    except Exception:
        _logger.warning(
            "Failed to capture commit finalizer dirty-path baseline", exc_info=True
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
    record = _baseline_record(
        repo_id=repo_id,
        repo_path=repo_path,
        kind=kind,
        name=name,
        scope=_BASELINE_SCOPE_OPENED_REPO,
    )
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
                if existing_path != record["path"]:
                    return (
                        f"repository baseline {repo_id!r} already points at "
                        f"{existing_path}; refusing to recapture {record['path']}"
                    )
                return None
            records[repo_id] = record
            _write_finalizer_baseline_payload(root, list(records.values()))
    except Exception as exc:
        _logger.warning("Failed to capture opened repo dirty baseline", exc_info=True)
        return f"{type(exc).__name__}: {exc}"
    return None


def load_dirty_baseline(artifact_root: Path | None) -> DirtyBaseline | None:
    """Load the baseline :func:`capture_dirty_baseline` wrote, if any.

    New runs write ``finalizer_baseline.json``. ``commit_finalizer_baseline.json``
    is a historical-only reader for archived agents; this function never writes
    that filename.

    Returns ``None`` on a missing, unreadable, or malformed baseline file so
    callers degrade to pre-baseline behavior rather than raising.
    """
    if artifact_root is None:
        return None
    baseline = _load_finalizer_dirty_baseline(Path(artifact_root))
    if baseline is not None:
        return baseline
    return _load_legacy_dirty_baseline(Path(artifact_root))


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


def _load_finalizer_dirty_baseline(artifact_root: Path) -> DirtyBaseline | None:
    try:
        payload = json.loads(
            (artifact_root / FINALIZER_BASELINE_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return None
    records = payload.get("repositories")
    if not isinstance(records, list):
        return None
    baseline: DirtyBaseline = {}
    for item in records:
        if not isinstance(item, dict):
            return None
        repo_path = item.get("path")
        scope = item.get("scope")
        fingerprints = item.get("fingerprints")
        if not isinstance(repo_path, str) or not isinstance(fingerprints, dict):
            return None
        if scope != _BASELINE_SCOPE_RUN_START:
            continue
        repo_entries: dict[str, tuple[str, str | None]] = {}
        for path, fingerprint in fingerprints.items():
            if not _is_valid_fingerprint_entry(path, fingerprint):
                return None
            repo_entries[path] = (fingerprint[0], fingerprint[1])
        baseline[repo_path] = repo_entries
    return baseline


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


def _baseline_record(
    *,
    repo_id: str,
    repo_path: str,
    kind: str,
    name: str,
    scope: str,
) -> dict[str, Any]:
    path = normalize_path(repo_path)
    return {
        "repo_id": repo_id,
        "path": path,
        "kind": kind,
        "name": name,
        "scope": scope,
        "fingerprints": {
            item_path: list(fingerprint)
            for item_path, fingerprint in dirty_path_fingerprints(path).items()
        },
    }


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
