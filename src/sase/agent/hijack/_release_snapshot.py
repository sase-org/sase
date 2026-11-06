"""Snapshot verification before a hijacked workspace is released.

Restart and dismiss both release the held workspace, so the recovery
snapshot must be verified (or refreshed) first. :func:`ensure_recovery_snapshot`
walks the primary checkout plus every linked or sidecar repo with changes,
reuses a recorded snapshot only when its fingerprint still matches the live
checkout, and re-snapshots otherwise. Any failure fails closed: the caller
keeps the hold and names the ``--discard-without-snapshot`` escape hatch.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack.recover_common import RecoveryRefusal, clean_string

LOG = logging.getLogger(__name__)


def ensure_recovery_snapshot(
    record: Mapping[str, Any],
    *,
    discard_without_snapshot: bool = False,
    snapshot_repo: Callable[..., Any] | None = None,
    fingerprint_fn: Callable[[str], dict[str, str]] | None = None,
    merge_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Verify (or refresh) recovery snapshots before a release resolution.

    Returns the snapshot list to persist on the record. Recorded snapshots
    whose fingerprint token still matches the live checkout are reused;
    anything stale or missing is re-captured. A snapshot failure raises
    :class:`RecoveryRefusal` with code ``snapshot_failed`` unless
    *discard_without_snapshot* is set, in which case the already-recorded
    snapshots are returned unchanged.
    """
    if snapshot_repo is None:
        from sase.workspace_provider._snapshot_capture_source import (
            snapshot_git_repo as _snapshot_git_repo,
        )

        snapshot_repo = _snapshot_git_repo
    if fingerprint_fn is None:
        from sase.workspace_provider._snapshot_capture_source import (
            snapshot_source_fingerprint as _fingerprint,
        )

        fingerprint_fn = _fingerprint
    existing = [
        dict(entry)
        for entry in record.get("snapshots") or []
        if isinstance(entry, Mapping)
    ]
    workspace_dir = clean_string(record.get("workspace_dir"))
    workspace_num = record.get("workspace_num")
    if workspace_dir is None or not isinstance(workspace_num, int):
        if existing:
            return existing
        raise RecoveryRefusal(
            "snapshot_failed",
            "Cannot snapshot before release: the hijack record has no "
            "workspace directory. Re-run with --discard-without-snapshot "
            "(dangerous: uncommitted work may be lost) to release anyway.",
        )
    roots = _release_repo_roots(record)
    if not roots:
        return existing
    by_repo = {
        str(entry.get("repo") or ""): entry for entry in existing if entry.get("repo")
    }
    updated: list[dict[str, Any]] = []
    errors: list[str] = []
    for root in roots:
        recorded = by_repo.get(root)
        try:
            current = fingerprint_fn(root)
        except Exception as exc:
            LOG.warning("release snapshot fingerprint failed for %s: %s", root, exc)
            errors.append(f"{root}: {exc}")
            continue
        token = _fingerprint_token(current)
        if recorded is not None and str(recorded.get("fingerprint") or "") == token:
            updated.append(recorded)
            continue
        try:
            snap = snapshot_repo(
                root,
                workspace_dir=str(workspace_dir),
                workspace_num=int(workspace_num),
                label=f"hijack-release-{record.get('agent_name') or 'agent'}",
                reason="hijack recovery release",
            )
        except Exception as exc:
            LOG.warning("release snapshot capture failed for %s: %s", root, exc)
            errors.append(f"{root}: {exc}")
            continue
        if snap is None:
            if recorded is not None:
                updated.append(recorded)
            continue
        updated.append(
            {
                "repo": root,
                "reference": str(
                    getattr(snap, "snapshot_id", "") or getattr(snap, "head", "")
                ),
                "fingerprint": token or str(getattr(snap, "worktree_tree", "")),
            }
        )
    if errors:
        message = (
            "Recovery snapshot failed before release ("
            + "; ".join(errors)
            + "). The workspace stays held. Re-run with "
            "--discard-without-snapshot (dangerous: uncommitted work may "
            "be lost) to release without a verified snapshot."
        )
        if discard_without_snapshot:
            LOG.warning("releasing without a verified snapshot: %s", message)
            return existing
        raise RecoveryRefusal("snapshot_failed", message)
    merged = _merge_record_snapshots(record, updated, merge_fn=merge_fn)
    return merged if merged is not None else updated


def _merge_record_snapshots(
    record: Mapping[str, Any],
    snapshots: list[dict[str, Any]],
    *,
    merge_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]] | None:
    """Persist refreshed snapshots on the record without a state transition."""
    hijack_id = clean_string(record.get("hijack_id"))
    if hijack_id is None:
        return None
    merge = merge_fn
    if merge is None:
        from sase.agent.hijack._stop_evidence import attach_evidence

        def merge(hijack_id: str, fields: dict[str, Any]) -> None:
            attach_evidence(hijack_id, fields)

    try:
        merge(hijack_id, {"snapshots": snapshots})
    except Exception as exc:  # noqa: BLE001 - merge failure fails closed upstream
        LOG.warning("could not merge release snapshots for %s: %s", hijack_id, exc)
        return None
    return snapshots


def _release_repo_roots(record: Mapping[str, Any]) -> list[str]:
    """Return every checkout a release snapshot must cover.

    The workspace toplevel plus every recorded snapshot repo, extended with
    the predecessor's opened/linked/sidecar repos so work shelled into a
    sibling checkout after the hijack is still preserved.
    """
    roots: list[str] = []
    workspace_dir = clean_string(record.get("workspace_dir"))
    if workspace_dir:
        toplevel = _repo_toplevel(workspace_dir)
        if toplevel is not None and toplevel not in roots:
            roots.append(toplevel)
    for entry in record.get("snapshots") or []:
        if not isinstance(entry, Mapping):
            continue
        repo = entry.get("repo")
        if isinstance(repo, str) and repo and repo not in roots:
            roots.append(repo)
    for repo in _meta_repo_roots(record):
        if repo not in roots:
            roots.append(repo)
    return roots


def _meta_repo_roots(record: Mapping[str, Any]) -> list[str]:
    """Return toplevels for repos the predecessor meta lists as opened."""
    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return []
    try:
        meta = json.loads(
            Path(artifacts_dir, "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return []
    if not isinstance(meta, Mapping):
        return []
    roots: list[str] = []
    for key in ("opened_repos", "linked_repos", "sidecar_repos", "repo_roots"):
        value = meta.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, str) or not entry:
                continue
            toplevel = _repo_toplevel(entry)
            if toplevel is not None and toplevel not in roots:
                roots.append(toplevel)
    return roots


def _repo_toplevel(path: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    toplevel = proc.stdout.strip()
    return toplevel or None


def _fingerprint_token(fingerprint: Mapping[str, str]) -> str:
    return json.dumps(dict(fingerprint), sort_keys=True, separators=(",", ":"))


__all__ = [
    "ensure_recovery_snapshot",
]
