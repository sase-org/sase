"""Post-commit tracking: diff capture, COMMITS entries, result markers, Patch."""

from __future__ import annotations

import json
import os
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.core.patch_metadata import canonicalize_patch_metadata
from sase.workflows.commit.commit_tracking_diff import (
    capture_pre_commit_diff,
    resolve_cl_name,
    resolve_project_file,
    write_commit_diff_artifact,
)
from sase.workflows.commit.commit_tracking_entries import append_commits_entry
from sase.workflows.commit.commit_tracking_patch import (
    cleanup_reservation,
    create_patch,
)

__all__ = [
    "agent_workspace_dir",
    "append_commits_entry",
    "capture_pre_commit_diff",
    "cleanup_reservation",
    "create_patch",
    "record_sdd_commit_result_marker",
    "resolve_cl_name",
    "resolve_project_file",
    "write_commit_diff_artifact",
    "write_result_marker",
    "write_unpushed_commit_marker",
]


def _repository_root(path: object) -> str | None:
    """Return the nearest repository root containing *path*, when recognizable.

    Commit tracking only needs repository identity, not provider behavior.  The
    nearest marker matters because sidecar repositories may be nested inside
    the primary workspace.  Unknown VCS layouts deliberately return ``None``
    so callers can preserve the legacy compatibility behavior.
    """
    if not isinstance(path, (str, os.PathLike)):
        return None
    try:
        candidate = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not candidate.is_dir():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists() or (directory / ".hg").exists():
            return os.path.normcase(os.path.normpath(os.fspath(directory)))
    return None


def _persist_primary_commit_metadata(
    artifacts_dir: str,
    diff_path: str | None,
    changespec_name: str | None,
    *,
    commit_cwd: str | None = None,
) -> None:
    """Persist generic primary-repository commit metadata fallbacks.

    ``commit_results.json`` records every commit with its repository-aware
    metadata.  The corresponding ``agent_meta.json`` fields have a narrower
    contract: they describe commits in the agent's primary workspace.  Do not
    let a linked, external, sidecar, or temporary repository replace them.

    Historical agents may lack ``workspace_dir`` or use an unrecognized VCS
    layout.  In those cases repository identity cannot be proven, so retain
    the previous conservative behavior and publish the metadata rather than
    silently dropping the only persisted attribution.
    """
    normalized_changespec_name = (
        changespec_name.strip() if changespec_name and changespec_name.strip() else None
    )
    if not diff_path and not normalized_changespec_name:
        return

    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            return
        primary_root = _repository_root(meta.get("workspace_dir"))
        commit_root = _repository_root(commit_cwd)
        if (
            primary_root is not None
            and commit_root is not None
            and primary_root != commit_root
        ):
            return
        original_meta = dict(meta)
        canonicalize_patch_metadata(meta)
        canonicalize_agent_tribe_metadata(meta)
        if diff_path and meta.get("commit_diff_path") != diff_path:
            meta["commit_diff_path"] = diff_path
        if (
            normalized_changespec_name
            and meta.get("commit_patch_name") != normalized_changespec_name
        ):
            meta["commit_patch_name"] = normalized_changespec_name
            meta["commit_changespec_name"] = normalized_changespec_name
        if meta == original_meta:
            return
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return


def _load_commit_results(results_path: str) -> list[dict[str, Any]]:
    try:
        with open(results_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _marker_identity(marker: Mapping[str, Any]) -> tuple[Any, Any]:
    return (marker.get("cwd"), marker.get("result"))


def _settle_related_commit_markers(
    results: list[dict[str, Any]],
    marker: dict[str, Any],
) -> None:
    """Mark earlier rows for the same operation as superseded.

    Recovery keys unpushed work by SHA. A rebase rewrites that SHA, so the
    previous ``pushed: false`` row must stop being eligible while remaining
    in the ledger for audit.
    """
    new_key = _marker_identity(marker)
    operation_id = marker.get("operation_id")
    run_id = marker.get("run_id")
    cwd = marker.get("cwd")
    new_result = marker.get("result")
    success = marker.get("pushed") is not False
    if not success and not operation_id:
        return
    for existing in results:
        if _marker_identity(existing) == new_key:
            continue
        related = False
        existing_op = existing.get("operation_id")
        if operation_id and existing_op == operation_id:
            related = True
        elif (
            success
            and existing.get("pushed") is False
            and existing.get("cwd") == cwd
            and existing.get("run_id") == run_id
            and not existing_op
        ):
            related = True
        if not related:
            continue
        existing["superseded_by"] = new_result
        existing["settled"] = True


def _upsert_commit_results_marker(
    artifacts_dir: str,
    marker: dict[str, Any],
) -> bool:
    results_path = os.path.join(artifacts_dir, "commit_results.json")
    try:
        results = _load_commit_results(results_path)
        key = _marker_identity(marker)
        for index, existing in enumerate(results):
            if _marker_identity(existing) == key:
                results[index] = marker
                break
        else:
            results.append(marker)
        _settle_related_commit_markers(results, marker)

        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results, f)
    except (TypeError, OSError):
        return False
    return True


def agent_workspace_dir(artifacts_dir: str) -> str | None:
    """Resolve the primary workspace recorded for an agent artifact directory."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        meta = None
    if isinstance(meta, dict):
        workspace_dir = meta.get("workspace_dir")
        if isinstance(workspace_dir, str) and workspace_dir.strip():
            return workspace_dir
    from sase.env_contracts import WORKSPACE_PIN_ENV_VARS

    for env_name in (*WORKSPACE_PIN_ENV_VARS, "PWD"):
        workspace_dir = os.environ.get(env_name)
        if workspace_dir:
            return workspace_dir
    return None


def _sdd_repo_name_for_commit_cwd(
    commit_cwd: str,
    workspace_dir: str | None,
) -> str | None:
    """Return an external SDD repository label containing ``commit_cwd``."""

    if not workspace_dir:
        return None
    try:
        from sase.sdd.store import get_primary_workspace_dir, read_sdd_store_record

        cwd = Path(commit_cwd).expanduser().resolve(strict=False)
        workspace = Path(workspace_dir).expanduser().resolve(strict=False)
        sidecars_root = workspace / "sase" / "repos"
        try:
            relative = cwd.relative_to(sidecars_root)
        except ValueError:
            relative = None
        if relative is not None and relative.parts:
            role = relative.parts[0]
            if role not in {"external", "linked"}:
                return role

        legacy_root = workspace / ".sase" / "sdd"
        try:
            cwd.relative_to(legacy_root)
        except ValueError:
            return None
        primary_workspace = get_primary_workspace_dir(str(workspace), 1)
        record = read_sdd_store_record(primary_workspace)
        if record is not None and record.repo:
            return record.repo
        return "sdd"
    except Exception:
        return None


def _external_repo_name_for_commit_cwd(
    commit_cwd: str,
    workspace_dir: str | None,
) -> str | None:
    """Return the canonical external-repo name containing ``commit_cwd``."""

    if not workspace_dir:
        return None
    try:
        from sase.external_repos import external_repo_name_from_clone_parts
        from sase.linked_repos import EXTERNAL_REPO_CLONES_SUBDIR

        repo_root = _repository_root(commit_cwd)
        if repo_root is None:
            return None
        external_root = (
            Path(workspace_dir)
            .expanduser()
            .resolve(strict=False)
            .joinpath(*EXTERNAL_REPO_CLONES_SUBDIR)
        )
        clone_parts = Path(repo_root).relative_to(external_root).parts
        return external_repo_name_from_clone_parts(clone_parts)
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve_commit_created_at(cwd: str, sha: str | None) -> int | None:
    """Best-effort author-time lookup for a just-made commit. Never raises."""
    if not sha:
        return None
    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(cwd)
        commits = provider.log(cwd, 1, revs=(sha,), merges="show")
    except Exception:
        return None

    if not commits:
        return None
    commit = commits[0]
    target = sha.lower()
    if commit.full_id.lower() != target and commit.short_id.lower() != target:
        return None
    return commit.timestamp


def record_sdd_commit_result_marker(
    *,
    cwd: str | os.PathLike[str],
    result: str,
    message: str,
    repo_name: str | None = None,
    artifacts_dir: str | os.PathLike[str] | None = None,
    diff_path: str | None = None,
) -> None:
    """Append an SDD commit to an agent's commit-results marker list.

    SDD commits are additional repo commits, not the primary workflow commit,
    so this deliberately does not write ``commit_result.json``.
    """
    resolved_artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved_artifacts_dir:
        return

    artifacts_dir_str = os.fspath(resolved_artifacts_dir)
    if not os.path.isdir(artifacts_dir_str):
        return

    run_id = os.environ.get("SASE_AGENT_TIMESTAMP", "").strip()
    if not run_id:
        run_id = os.path.basename(os.path.normpath(artifacts_dir_str))

    cwd_str = os.fspath(cwd)
    marker: dict[str, Any] = {
        "method": "sdd_commit",
        "run_id": run_id,
        "cwd": cwd_str,
        "result": result,
        "commit_result": result,
        "commit_sha": result,
        "message": message,
        "repo_name": repo_name or Path(cwd_str).name,
        "diff_path": diff_path,
        "commit_diff_path": diff_path,
    }
    committed_at = _resolve_commit_created_at(cwd_str, result)
    if committed_at is not None:
        marker["committed_at"] = committed_at
    _upsert_commit_results_marker(artifacts_dir_str, marker)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir_str)


def write_result_marker(
    method: str,
    payload: dict,
    diff_path: str | None,
    result: str | None,
    changespec_name: str | None,
    *,
    entry_id: str | None = None,
    commit_sha: str | None = None,
    commit_tree: str | None = None,
    commit_cwd: str | os.PathLike[str] | None = None,
    pushed: bool | None = None,
    dispatch_error: str | None = None,
    operation_id: str | None = None,
) -> bool:
    """Write commit result to a marker file for xprompt post-steps.

    ``commit_sha``/``commit_tree`` are the run-owned ledger fields: unlike
    ``result`` (which is a PR URL for ``create_pull_request`` and a diff path
    for ``create_proposal``), they are always the commit this run finalized,
    letting a later reader identify it without decoding ``method`` first.

    ``commit_cwd`` is the repository identity recorded as ``cwd`` and used for
    sidecar/external classification, commit-time lookup, and primary-metadata
    ownership. Direct callers that omit it keep the ambient working directory.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return False

    run_id = os.environ.get("SASE_AGENT_TIMESTAMP", "").strip()
    if not run_id:
        run_id = os.path.basename(os.path.normpath(artifacts_dir))
    resolved_cwd = os.fspath(commit_cwd) if commit_cwd is not None else os.getcwd()
    workspace_dir = agent_workspace_dir(artifacts_dir)
    repo_name = _external_repo_name_for_commit_cwd(resolved_cwd, workspace_dir)
    if repo_name is None:
        repo_name = _sdd_repo_name_for_commit_cwd(resolved_cwd, workspace_dir)

    marker = {
        "method": method,
        "run_id": run_id,
        "cwd": resolved_cwd,
        "result": result,
        "commit_result": result,
        "message": payload.get("message", ""),
        "name": payload.get("name", ""),
        "bead_id": payload.get("bead_id", ""),
        "patch_name": changespec_name,
        "changespec_name": changespec_name,
        "commit_patch_name": changespec_name,
        "commit_changespec_name": changespec_name,
        "entry_id": entry_id,
        "stitch_id": entry_id,
        "commit_entry_id": entry_id,
        "diff_path": diff_path,
        "commit_diff_path": diff_path,
    }
    if repo_name is not None:
        marker["repo_name"] = repo_name
    if commit_sha:
        marker["commit_sha"] = commit_sha
    if commit_tree:
        marker["commit_tree"] = commit_tree
    if pushed is not None:
        marker["pushed"] = pushed
    if dispatch_error:
        marker["dispatch_error"] = dispatch_error
    if operation_id:
        marker["operation_id"] = operation_id
    committed_at = _resolve_commit_created_at(resolved_cwd, result)
    if committed_at is not None:
        marker["committed_at"] = committed_at
    marker_file_written = True
    if pushed is not False:
        marker_path = os.path.join(artifacts_dir, "commit_result.json")
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker, f)
        except OSError:
            marker_file_written = False
        else:
            _persist_primary_commit_metadata(
                artifacts_dir,
                diff_path,
                changespec_name,
                commit_cwd=resolved_cwd,
            )
    return _upsert_commit_results_marker(artifacts_dir, marker) and marker_file_written


def write_unpushed_commit_marker(
    method: str,
    payload: dict,
    *,
    cwd: str | os.PathLike[str],
    result: str,
    commit_sha: str,
    commit_tree: str | None = None,
    push_error: str | None = None,
    operation_id: str | None = None,
    dispatch_error: str | None = None,
) -> bool:
    """Record a local commit whose post-commit push failed.

    This intentionally writes only the multi-repository ledger. The ordinary
    ``commit_result.json`` singleton remains reserved for completed tracking.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return False
    if not os.path.isdir(artifacts_dir):
        return False

    run_id = os.environ.get("SASE_AGENT_TIMESTAMP", "").strip()
    if not run_id:
        run_id = os.path.basename(os.path.normpath(artifacts_dir))
    resolved_cwd = os.fspath(cwd)
    workspace_dir = agent_workspace_dir(artifacts_dir)
    repo_name = _external_repo_name_for_commit_cwd(resolved_cwd, workspace_dir)
    if repo_name is None:
        repo_name = _sdd_repo_name_for_commit_cwd(resolved_cwd, workspace_dir)

    marker: dict[str, Any] = {
        "method": method,
        "run_id": run_id,
        "cwd": resolved_cwd,
        "result": result,
        "commit_result": result,
        "commit_sha": commit_sha,
        "message": payload.get("message", ""),
        "name": payload.get("name", ""),
        "bead_id": payload.get("bead_id", ""),
        "patch_name": None,
        "changespec_name": None,
        "commit_patch_name": None,
        "commit_changespec_name": None,
        "entry_id": None,
        "stitch_id": None,
        "commit_entry_id": None,
        "diff_path": None,
        "commit_diff_path": None,
        "pushed": False,
    }
    if repo_name is not None:
        marker["repo_name"] = repo_name
    if commit_tree:
        marker["commit_tree"] = commit_tree
    if push_error:
        marker["push_error"] = push_error
    if dispatch_error:
        marker["dispatch_error"] = dispatch_error
    if operation_id:
        marker["operation_id"] = operation_id
    committed_at = _resolve_commit_created_at(resolved_cwd, commit_sha)
    if committed_at is not None:
        marker["committed_at"] = committed_at
    written = _upsert_commit_results_marker(artifacts_dir, marker)
    if not written:
        return False
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    return True
