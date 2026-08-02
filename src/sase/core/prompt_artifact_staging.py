"""Best-effort launch-time staging for prompt artifact references."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import fcntl
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import TypedDict, cast

from sase.config import get_artifact_capture_pool_max_bytes
from sase.core.artifact_capture_policy import (
    GitVcsProbe,
    capture_file_exceeds_size_limit,
)
from sase.core.artifact_file_helpers import artifact_file_mime_type, hash_file
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file
from sase.repo_inventory import collect_repo_inventory


log = logging.getLogger(__name__)

PROMPT_ARTIFACT_MANIFEST_NAME = "prompt-artifacts.jsonl"
PROMPT_ARTIFACT_MANIFEST_LOCK_NAME = "prompt-artifacts.lock"
PROMPT_ARTIFACT_POOL_DIR = "pool"
PROMPT_ARCHIVE_PUBLICATION_MARKER_NAME = "prompt-archive-published.json"
_NON_FILE_REF_KINDS = frozenset({"agent", "bug", "commit"})
_VCS_PROBE = GitVcsProbe()


class PromptArtifactRecord(TypedDict):
    """Python projection of the Rust-owned prompt-artifact manifest wire."""

    schema_version: int
    recorded_at: str
    agent_artifacts_dir: str
    raw_ref: str
    expanded_ref: str
    ref_kind: str
    label: str
    source_path: str | None
    sha256: str | None
    size_bytes: int | None
    mime_type: str | None
    pool_relpath: str | None
    vcs_repo: str | None
    vcs_relpath: str | None
    locator: str | None
    skipped_reason: str | None


def stage_prompt_artifact(
    *,
    raw_ref: str,
    expanded_ref: str,
    resolved_path: Path | str | None,
    ref_kind: str,
    label: str,
    locator: str | None = None,
    workspace_root: Path | str | None = None,
    agent_artifacts_dir: Path | str | None = None,
) -> PromptArtifactRecord | None:
    """Stage one prompt reference without ever breaking prompt launch.

    File references are copied into the workspace-local content-addressed pool.
    Clean tracked files also record VCS provenance so publication can prefer a
    repository link after verifying that it still names the captured bytes.
    Locator-only references receive a manifest row without touching the pool.
    """

    try:
        artifacts_dir = _resolve_agent_artifacts_dir(agent_artifacts_dir)
        if artifacts_dir is None:
            return None
        workspace = (
            Path(workspace_root or Path.cwd()).expanduser().resolve(strict=False)
        )
        staging_root = workspace / ".sase" / "artifacts"
        manifest_path = staging_root / PROMPT_ARTIFACT_MANIFEST_NAME
        lock_path = staging_root / PROMPT_ARTIFACT_MANIFEST_LOCK_NAME

        record = _base_record(
            raw_ref=raw_ref,
            expanded_ref=expanded_ref,
            ref_kind=ref_kind,
            label=label,
            locator=locator,
            agent_artifacts_dir=artifacts_dir,
        )
        source = _resolved_file(resolved_path, workspace)
        if ref_kind in _NON_FILE_REF_KINDS:
            _append_manifest_record(manifest_path, lock_path, record)
            return record
        if source is None:
            log.debug("Could not classify prompt artifact %s as a file", raw_ref)
            return None

        size_bytes = source.stat().st_size
        sha256 = hash_file(source)
        record["source_path"] = str(source)
        record["sha256"] = sha256
        record["size_bytes"] = size_bytes
        record["mime_type"] = artifact_file_mime_type(source)

        vcs = _clean_vcs_provenance(source)
        if vcs is not None:
            record["vcs_repo"] = vcs[0]
            record["vcs_relpath"] = vcs[1]

        if capture_file_exceeds_size_limit(size_bytes):
            record["skipped_reason"] = "too-large"
            _append_manifest_record(manifest_path, lock_path, record)
            return record

        pool_filename = str(
            require_rust_binding("prompt_artifact_pool_filename")(
                sha256,
                source.name,
            )
        )
        pool_relpath = f"{PROMPT_ARTIFACT_POOL_DIR}/{pool_filename}"
        record["pool_relpath"] = pool_relpath
        pool_path = staging_root / pool_relpath
        created = _store_and_append_record(
            source=source,
            expected_sha256=sha256,
            pool_path=pool_path,
            manifest_path=manifest_path,
            lock_path=lock_path,
            record=record,
        )
        if created and _pool_exceeds_budget(staging_root):
            _prune_prompt_artifact_pool(workspace)
        return record
    except Exception as exc:  # noqa: BLE001 - staging is launch auxiliary work.
        log.debug("Could not stage prompt artifact %s: %s", raw_ref, exc, exc_info=True)
        return None


def _prune_prompt_artifact_pool(workspace_root: Path | str) -> int:
    """Remove published terminal-run pool files until the budget is met.

    A pooled file is eligible only when every manifest row that names it
    belongs to a terminal agent run with a durable prompt-archive publication
    marker. Manifest provenance is intentionally retained.
    """

    workspace = Path(workspace_root).expanduser().resolve(strict=False)
    staging_root = workspace / ".sase" / "artifacts"
    manifest_path = staging_root / PROMPT_ARTIFACT_MANIFEST_NAME
    lock_path = staging_root / PROMPT_ARTIFACT_MANIFEST_LOCK_NAME
    budget = get_artifact_capture_pool_max_bytes()
    removed = 0
    with locked_file(lock_path, fcntl.LOCK_EX):
        pool_files = _pool_files(staging_root)
        total_size = sum(size for _path, size in pool_files)
        if total_size <= budget or not manifest_path.is_file():
            return 0
        records = _parse_manifest(manifest_path.read_bytes())
        rows_by_pool: dict[str, list[PromptArtifactRecord]] = defaultdict(list)
        for record in records:
            pool_relpath = record.get("pool_relpath")
            if isinstance(pool_relpath, str) and pool_relpath:
                rows_by_pool[pool_relpath].append(record)

        candidates: list[tuple[float, Path, int]] = []
        for path, size in pool_files:
            relpath = path.relative_to(staging_root).as_posix()
            rows = rows_by_pool.get(relpath, [])
            if rows and all(_run_is_terminal_and_published(row) for row in rows):
                candidates.append((path.stat().st_mtime, path, size))
        for _mtime, path, size in sorted(candidates):
            if total_size <= budget:
                break
            path.unlink(missing_ok=True)
            total_size -= size
            removed += 1
    return removed


def _base_record(
    *,
    raw_ref: str,
    expanded_ref: str,
    ref_kind: str,
    label: str,
    locator: str | None,
    agent_artifacts_dir: Path,
) -> PromptArtifactRecord:
    schema_version = int(require_rust_binding("prompt_artifact_wire_schema_version")())
    return PromptArtifactRecord(
        schema_version=schema_version,
        recorded_at=datetime.now(tz=UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        agent_artifacts_dir=str(agent_artifacts_dir),
        raw_ref=raw_ref,
        expanded_ref=expanded_ref,
        ref_kind=ref_kind,
        label=label,
        source_path=None,
        sha256=None,
        size_bytes=None,
        mime_type=None,
        pool_relpath=None,
        vcs_repo=None,
        vcs_relpath=None,
        locator=locator,
        skipped_reason=None,
    )


def _resolve_agent_artifacts_dir(
    value: Path | str | None,
) -> Path | None:
    raw = value if value is not None else os.environ.get("SASE_ARTIFACTS_DIR")
    if raw is None or not str(raw).strip():
        return None
    return Path(raw).expanduser().resolve(strict=False)


def _resolved_file(value: Path | str | None, workspace: Path) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = workspace / path
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return resolved if resolved.is_file() else None


def _clean_vcs_provenance(source: Path) -> tuple[str, str] | None:
    toplevel = _VCS_PROBE.repo_toplevel(str(source))
    if toplevel is None:
        return None
    normalized_toplevel = Path(toplevel).expanduser().resolve(strict=False)
    try:
        inventory = collect_repo_inventory()
    except Exception:
        log.debug(
            "Could not collect repository inventory for %s", source, exc_info=True
        )
        return None

    candidates: list[tuple[str, Path, str]] = []
    for record in inventory.records:
        seen_paths: set[str] = set()
        for raw_root in (record.path, *(clone.path for clone in record.clones)):
            if not raw_root or raw_root in seen_paths:
                continue
            seen_paths.add(raw_root)
            root = Path(raw_root).expanduser().resolve(strict=False)
            if root != normalized_toplevel:
                continue
            try:
                relpath = source.relative_to(root).as_posix()
            except ValueError:
                continue
            candidates.append((record.name, root, relpath))
    for repo_name, root, relpath in sorted(candidates):
        if _git_path_is_tracked_and_clean(root, relpath):
            return repo_name, relpath
    return None


def _git_path_is_tracked_and_clean(root: Path, relpath: str) -> bool:
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relpath],
            capture_output=True,
            check=False,
            timeout=5,
        )
        if tracked.returncode != 0:
            return False
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
                "--",
                relpath,
            ],
            capture_output=True,
            check=False,
            timeout=5,
        )
        if status.returncode != 0 or status.stdout.strip():
            return False
        working_blob = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "hash-object",
                f"--path={relpath}",
                str(root / relpath),
            ],
            capture_output=True,
            check=False,
            timeout=5,
        )
        committed_blob = subprocess.run(
            ["git", "-C", str(root), "rev-parse", f"HEAD:{relpath}"],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return (
        working_blob.returncode == 0
        and committed_blob.returncode == 0
        and bool(working_blob.stdout.strip())
        and working_blob.stdout.strip() == committed_blob.stdout.strip()
    )


def _append_manifest_record(
    manifest_path: Path,
    lock_path: Path,
    record: PromptArtifactRecord,
) -> None:
    with locked_file(lock_path, fcntl.LOCK_EX):
        _append_manifest_record_unlocked(manifest_path, record)


def _append_manifest_record_unlocked(
    manifest_path: Path,
    record: PromptArtifactRecord,
) -> None:
    render = require_rust_binding("prompt_artifact_manifest_render_record")
    line = str(render(dict(record)))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _store_and_append_record(
    *,
    source: Path,
    expected_sha256: str,
    pool_path: Path,
    manifest_path: Path,
    lock_path: Path,
    record: PromptArtifactRecord,
) -> bool:
    with locked_file(lock_path, fcntl.LOCK_EX):
        created = _store_pool_file(source, pool_path, expected_sha256)
        _append_manifest_record_unlocked(manifest_path, record)
    return created


def _store_pool_file(source: Path, target: Path, expected_sha256: str) -> bool:
    if target.exists():
        if hash_file(target) != expected_sha256:
            raise RuntimeError(f"prompt artifact digest collision at {target}")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    tmp_path = Path(tmp_name)
    try:
        shutil.copy2(source, tmp_path)
        if hash_file(tmp_path) != expected_sha256:
            raise RuntimeError(f"prompt artifact changed while staging: {source}")
        os.replace(tmp_path, target)
    finally:
        tmp_path.unlink(missing_ok=True)
    return True


def _pool_exceeds_budget(staging_root: Path) -> bool:
    budget = get_artifact_capture_pool_max_bytes()
    total = 0
    for _path, size in _pool_files(staging_root):
        total += size
        if total > budget:
            return True
    return False


def _pool_files(staging_root: Path) -> list[tuple[Path, int]]:
    pool_dir = staging_root / PROMPT_ARTIFACT_POOL_DIR
    try:
        return [
            (path, path.stat().st_size) for path in pool_dir.iterdir() if path.is_file()
        ]
    except OSError:
        return []


def _parse_manifest(data: bytes) -> list[PromptArtifactRecord]:
    parse = require_rust_binding("prompt_artifact_manifest_parse")
    return cast(list[PromptArtifactRecord], parse(data))


def _run_is_terminal_and_published(record: PromptArtifactRecord) -> bool:
    raw_dir = record.get("agent_artifacts_dir")
    if not isinstance(raw_dir, str) or not raw_dir:
        return False
    artifacts_dir = Path(raw_dir).expanduser()
    if not (artifacts_dir / "done.json").is_file():
        return False
    return (artifacts_dir / PROMPT_ARCHIVE_PUBLICATION_MARKER_NAME).is_file()


def mark_prompt_archive_published(
    agent_artifacts_dir: Path | str,
    *,
    primary_revision: str,
) -> None:
    """Record that this run's prompt bytes reached the durable archive."""

    artifacts_dir = Path(agent_artifacts_dir).expanduser().resolve(strict=False)
    marker = artifacts_dir / PROMPT_ARCHIVE_PUBLICATION_MARKER_NAME
    marker.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_tmp = tempfile.mkstemp(
        prefix=f".{marker.name}.",
        suffix=".tmp",
        dir=marker.parent,
    )
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "primary_revision": primary_revision,
                    "published_at": datetime.now(tz=UTC)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
                },
                stream,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, marker)
    finally:
        tmp.unlink(missing_ok=True)


__all__ = [
    "PROMPT_ARTIFACT_MANIFEST_NAME",
    "PROMPT_ARTIFACT_POOL_DIR",
    "PROMPT_ARCHIVE_PUBLICATION_MARKER_NAME",
    "PromptArtifactRecord",
    "mark_prompt_archive_published",
    "stage_prompt_artifact",
]
