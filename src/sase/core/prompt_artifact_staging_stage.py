"""Stage one prompt artifact reference into VCS provenance or the local pool.

Split out of :mod:`sase.core.prompt_artifact_staging` to keep each module
under the 500-line cap. Capture lives in
:mod:`sase.core.prompt_artifact_staging_capture`; pool IO lives in
:mod:`sase.core.prompt_artifact_staging_pool`. The public import path
remains :mod:`sase.core.prompt_artifact_staging`.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import subprocess

from sase.core._prompt_artifact_staging_shared import (
    PROMPT_ARTIFACT_MANIFEST_LOCK_NAME,
    PROMPT_ARTIFACT_MANIFEST_NAME,
    PROMPT_ARTIFACT_POOL_DIR,
    PromptArtifactRecord,
    agents_sidecar_metadata,
    base_record,
    resolve_agent_artifacts_dir,
)
from sase.core.artifact_capture_policy import (
    GitVcsProbe,
    capture_file_exceeds_size_limit,
)
from sase.core.artifact_file_helpers import artifact_file_mime_type, hash_file
from sase.core.prompt_artifact_staging_pool import (
    append_manifest_record,
    pool_exceeds_budget,
    prune_prompt_artifact_pool,
    store_and_append_record,
)
from sase.core.rust import require_rust_binding
from sase.repo_inventory import collect_repo_inventory


log = logging.getLogger(__name__)

_NON_FILE_REF_KINDS = frozenset({"agent", "bug", "commit", "goal", "patch", "stitch"})
_VCS_PROBE = GitVcsProbe()


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
        artifacts_dir = resolve_agent_artifacts_dir(agent_artifacts_dir)
        if artifacts_dir is None:
            return None
        workspace = (
            Path(workspace_root or Path.cwd()).expanduser().resolve(strict=False)
        )
        staging_root = workspace / ".sase" / "artifacts"
        manifest_path = staging_root / PROMPT_ARTIFACT_MANIFEST_NAME
        lock_path = staging_root / PROMPT_ARTIFACT_MANIFEST_LOCK_NAME

        record = base_record(
            raw_ref=raw_ref,
            expanded_ref=expanded_ref,
            ref_kind=ref_kind,
            label=label,
            locator=locator,
            agent_artifacts_dir=artifacts_dir,
        )
        source = _resolved_file(resolved_path, workspace)
        if ref_kind in _NON_FILE_REF_KINDS:
            append_manifest_record(manifest_path, lock_path, record)
            return record
        if source is None:
            log.debug("Could not classify prompt artifact %s as a file", raw_ref)
            return None

        record["source_path"] = str(source)
        size_bytes = source.stat().st_size
        record["size_bytes"] = size_bytes
        record["mime_type"] = artifact_file_mime_type(source)
        record["sidecar_visibility"] = agents_sidecar_metadata(workspace)[1]

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
            append_manifest_record(manifest_path, lock_path, record)
            return record

        sha256 = hash_file(source)
        record["sha256"] = sha256
        record["object_relpath"] = str(
            require_rust_binding("artifact_object_relpath")(sha256)
        )
        if capture_file_exceeds_size_limit(size_bytes):
            record["skipped_reason"] = "too-large"
            append_manifest_record(manifest_path, lock_path, record)
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
        created = store_and_append_record(
            source=source,
            expected_sha256=sha256,
            pool_path=pool_path,
            manifest_path=manifest_path,
            lock_path=lock_path,
            record=record,
        )
        if created and pool_exceeds_budget(staging_root):
            prune_prompt_artifact_pool(workspace)
        return record
    except Exception as exc:  # noqa: BLE001 - staging is launch auxiliary work.
        log.debug("Could not stage prompt artifact %s: %s", raw_ref, exc, exc_info=True)
        return None


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
    stripped = str(require_rust_binding("links_block_strip")(stripped))
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


def _origin_for_prompt_artifact(record: PromptArtifactRecord) -> str:
    raw_ref = record.get("raw_ref") or ""
    if record.get("ref_kind") == "file" and (
        raw_ref.startswith("@file:explicit:") or raw_ref.startswith("@file:default:")
    ):
        return "created"
    return "capture"


__all__ = [
    "stage_prompt_artifact",
]
