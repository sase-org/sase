"""Best-effort launch-time staging for prompt artifact references."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import fcntl
import hashlib
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
_NON_FILE_REF_KINDS = frozenset({"agent", "bug", "commit", "patch", "stitch"})
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
    vcs_revision: str | None
    locator: str | None
    skipped_reason: str | None
    logical_path: str | None
    root_name: str | None
    authored_path: str | None
    origin: str | None
    object_relpath: str | None
    sidecar_visibility: str | None


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

    File references are either recorded as clean tracked VCS content or copied
    into the workspace-local content-addressed pool. Locator-only references
    receive a manifest row without touching the pool.
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

        record["source_path"] = str(source)
        size_bytes = source.stat().st_size
        record["size_bytes"] = size_bytes
        record["mime_type"] = artifact_file_mime_type(source)
        record["sidecar_visibility"] = _agents_sidecar_metadata(workspace)[1]

        vcs = _clean_vcs_provenance(source)
        if vcs is not None:
            sha256 = _clean_vcs_prompt_artifact_digest(source)
            record["sha256"] = sha256
            record["object_relpath"] = str(
                require_rust_binding("artifact_object_relpath")(sha256)
            )
            record["vcs_repo"] = vcs[0]
            record["vcs_relpath"] = vcs[1]
            record["vcs_revision"] = vcs[2]
            _append_manifest_record(manifest_path, lock_path, record)
            return record

        sha256 = hash_file(source)
        record["sha256"] = sha256
        record["object_relpath"] = str(
            require_rust_binding("artifact_object_relpath")(sha256)
        )
        if capture_file_exceeds_size_limit(size_bytes):
            record["skipped_reason"] = "too-large"
            _append_manifest_record(manifest_path, lock_path, record)
            return record

        record["origin"] = _origin_for_prompt_artifact(record)
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


def capture_prompt_file_ref(
    *,
    source: Path,
    logical_path: str,
    root_name: str,
    authored_path: str,
    raw_ref: str,
    expanded_ref: str,
    workspace_root: Path | str | None = None,
    agent_artifacts_dir: Path | str | None = None,
) -> PromptArtifactRecord | None:
    """Capture one resolved ``@file:<path>`` reference into the local pool."""

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
        source = Path(source).expanduser().resolve(strict=True)
        record = _base_record(
            raw_ref=raw_ref,
            expanded_ref=expanded_ref,
            ref_kind="file",
            label=source.name,
            locator=logical_path,
            agent_artifacts_dir=artifacts_dir,
        )
        record["source_path"] = str(source)
        record["logical_path"] = logical_path
        record["root_name"] = root_name
        record["authored_path"] = authored_path
        record["origin"] = "ref"
        _repo, visibility = _agents_sidecar_metadata(workspace)
        record["sidecar_visibility"] = visibility

        pool_dir = staging_root / PROMPT_ARTIFACT_POOL_DIR
        pool_dir.mkdir(parents=True, exist_ok=True)
        descriptor, tmp_name = tempfile.mkstemp(
            prefix=".capture.",
            suffix=".tmp",
            dir=pool_dir,
        )
        os.close(descriptor)
        tmp_path = Path(tmp_name)
        try:
            digest = hashlib.sha256()
            size_bytes = 0
            with source.open("rb") as input_stream, tmp_path.open("wb") as output:
                while chunk := input_stream.read(1024 * 1024):
                    size_bytes += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
            sha256 = digest.hexdigest()
            record["sha256"] = sha256
            record["size_bytes"] = size_bytes
            record["mime_type"] = artifact_file_mime_type(source)
            record["object_relpath"] = str(
                require_rust_binding("artifact_object_relpath")(sha256)
            )
            if capture_file_exceeds_size_limit(size_bytes):
                record["skipped_reason"] = "too-large"
                _append_manifest_record(manifest_path, lock_path, record)
                return record

            pool_filename = str(
                require_rust_binding("prompt_artifact_pool_filename")(
                    sha256,
                    "file-ref",
                )
            )
            pool_relpath = f"{PROMPT_ARTIFACT_POOL_DIR}/{pool_filename}"
            record["pool_relpath"] = pool_relpath
            pool_path = staging_root / pool_relpath
            created = _store_captured_tmp_and_append_record(
                tmp_path=tmp_path,
                expected_sha256=sha256,
                pool_path=pool_path,
                manifest_path=manifest_path,
                lock_path=lock_path,
                record=record,
            )
            if created and _pool_exceeds_budget(staging_root):
                _prune_prompt_artifact_pool(workspace)
            return record
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - capture is launch auxiliary work.
        log.debug(
            "Could not capture prompt file ref %s: %s", raw_ref, exc, exc_info=True
        )
        return None


def _prune_prompt_artifact_pool(workspace_root: Path | str) -> int:
    """Remove published terminal-run pool files until the budget is met.

    A pooled file is eligible only when every manifest row that names it
    belongs to a terminal agent run whose commit checkpoint records successful
    prompt-archive publication. Manifest provenance is intentionally retained.
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
        vcs_revision=None,
        locator=locator,
        skipped_reason=None,
        logical_path=None,
        root_name=None,
        authored_path=None,
        origin=None,
        object_relpath=None,
        sidecar_visibility=None,
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


def _clean_vcs_provenance(source: Path) -> tuple[str, str, str] | None:
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
            revision = _git_head_revision(root)
            if revision:
                return repo_name, relpath, revision
    return None


def _git_head_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode(errors="replace").strip()


def _clean_vcs_prompt_artifact_digest(source: Path) -> str:
    if source.suffix.casefold() not in {".md", ".markdown"}:
        return hash_file(source)
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return hash_file(source)
    stripped = str(require_rust_binding("referenced_by_block_strip")(text))
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


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


def _store_captured_tmp_and_append_record(
    *,
    tmp_path: Path,
    expected_sha256: str,
    pool_path: Path,
    manifest_path: Path,
    lock_path: Path,
    record: PromptArtifactRecord,
) -> bool:
    with locked_file(lock_path, fcntl.LOCK_EX):
        created = _store_captured_tmp(tmp_path, pool_path, expected_sha256)
        _append_manifest_record_unlocked(manifest_path, record)
    return created


def _store_captured_tmp(
    tmp_path: Path,
    target: Path,
    expected_sha256: str,
) -> bool:
    if target.exists():
        if hash_file(target) != expected_sha256:
            raise RuntimeError(f"prompt artifact digest collision at {target}")
        return False
    if hash_file(tmp_path) != expected_sha256:
        raise RuntimeError("captured prompt artifact digest mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_path, target)
    return True


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


def _origin_for_prompt_artifact(record: PromptArtifactRecord) -> str:
    raw_ref = record.get("raw_ref") or ""
    if record.get("ref_kind") == "file" and (
        raw_ref.startswith("@file:explicit:") or raw_ref.startswith("@file:default:")
    ):
        return "created"
    return "capture"


def _agents_sidecar_metadata(workspace: Path) -> tuple[str, str]:
    try:
        from sase._linked_repo_config import (
            _SIDECAR_ROLE_KEY,
            _SIDECAR_SLUG_KEY,
            merged_sidecar_entries_from_config,
            resolution_config,
        )

        config = resolution_config(str(workspace), None)
        for entry in merged_sidecar_entries_from_config(
            config,
            primary_workspace_dir=str(workspace),
        ):
            if entry.get(_SIDECAR_ROLE_KEY) == "agents":
                repo = str(
                    entry.get(_SIDECAR_SLUG_KEY) or entry.get("name") or "agents"
                )
                visibility = str(entry.get("visibility") or "public")
                return repo, visibility
    except Exception:
        log.debug("Could not resolve agents sidecar visibility", exc_info=True)
    return "agents", "public"


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
    try:
        checkpoint = json.loads(
            (artifacts_dir / "commit_state.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False
    completed = (
        checkpoint.get("completed_steps") if isinstance(checkpoint, dict) else None
    )
    return isinstance(completed, list) and "publish_prompt_archive" in completed


__all__ = [
    "PROMPT_ARTIFACT_MANIFEST_NAME",
    "PROMPT_ARTIFACT_POOL_DIR",
    "PromptArtifactRecord",
    "capture_prompt_file_ref",
    "stage_prompt_artifact",
]
