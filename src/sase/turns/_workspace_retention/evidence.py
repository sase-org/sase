"""Evidence fingerprint and cheap stat signatures for held-workspace settlement.

A retained workspace is re-examined by every stale-running cleanup pass. Most
passes find nothing new, so settlement persists two cheap facts with the
retention record:

- an evidence fingerprint: a stable hash over the policy reason, the dirt
  classification, affected repo ids, normalized probe errors, and each repo's
  sorted dirty-path set;
- a stat signature per repo, with no subprocess: the mtime/size of the
  resolved gitdir's ``index`` and ``HEAD`` plus the checkout root's mtime,
  alongside ``probed_at``.

A later pass whose signature and freshness checks hold skips every git probe,
snapshot, decision-sheet publication, pin call, record write, and
notification. The ``--no-optional-locks`` git probe does not touch the index,
so probing never perturbs the signature.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .types import WorkspaceRetentionRepo

#: Re-probe interval for a held workspace whose stat signature is unchanged.
#: A workspace that becomes clean or changes evidence is released or
#: re-settled within one interval. Custody rules are unchanged, and a failed
#: probe never releases.
REPROBE_INTERVAL_SECONDS = 30 * 60

#: At most one "Workspace still held" +1 per hold per hour, on undismissed
#: rows only (epic decision ``held_heartbeat = yes``).
HEARTBEAT_INTERVAL_SECONDS = 60 * 60

#: Notify-state marker beside the retention record. It holds the notified
#: fingerprint and reason, the last +1 time, and a dismissed latch. It is a
#: separate file so hourly heartbeats never churn the custody record.
NOTIFY_STATE_LOCATOR = "diagnostics/workspace_retention_notify.json"


def evidence_now() -> float:
    """Return the current epoch time (indirection for tests)."""
    return time.time()


def _resolve_repo_gitdir(repo_path: str) -> str | None:
    """Return the gitdir for *repo_path* without running a subprocess.

    Handles plain checkouts (``<repo>/.git`` is a directory) and linked
    worktrees (``<repo>/.git`` is a file holding ``gitdir: <path>``).
    Returns ``None`` when the gitdir cannot be resolved.
    """
    try:
        dot_git = Path(repo_path) / ".git"
        if dot_git.is_dir():
            return str(dot_git)
        if dot_git.is_file():
            try:
                text = dot_git.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("gitdir:"):
                    target = stripped[len("gitdir:") :].strip()
                    if not target:
                        return None
                    candidate = Path(target)
                    if not candidate.is_absolute():
                        candidate = Path(repo_path) / candidate
                    return str(candidate)
            return None
        return None
    except OSError:
        return None


def _stat_pair(path: str | None) -> list[int] | None:
    """Return ``[mtime_ns, size]`` for *path*, or ``None`` when unreadable."""
    if path is None:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [int(st.st_mtime_ns), int(st.st_size)]


def compute_stat_signature(
    repos: Sequence[WorkspaceRetentionRepo | tuple[str, str]],
) -> dict[str, Any]:
    """Compute a cheap no-subprocess stat signature keyed by repo id.

    Each entry records the resolved gitdir plus the mtime/size of its
    ``index`` and ``HEAD`` and the checkout root's mtime. A repo that cannot
    be statted records ``{"unavailable": True}`` so the next pass re-probes
    instead of skipping on missing evidence.
    """
    signature: dict[str, Any] = {}
    for repo in repos:
        if isinstance(repo, WorkspaceRetentionRepo):
            repo_id, repo_path = repo.repo_id, repo.path
        else:
            repo_id, repo_path = repo
        try:
            root_mtime_ns = int(os.stat(repo_path).st_mtime_ns)
        except OSError:
            signature[repo_id] = {"unavailable": True}
            continue
        entry: dict[str, Any] = {"root_mtime_ns": root_mtime_ns}
        gitdir = _resolve_repo_gitdir(repo_path)
        if gitdir is None:
            entry["unavailable"] = True
            signature[repo_id] = entry
            continue
        entry["gitdir"] = gitdir
        entry["index"] = _stat_pair(os.path.join(gitdir, "index"))
        entry["head"] = _stat_pair(os.path.join(gitdir, "HEAD"))
        entry["head_ref"] = _stat_pair(_resolve_head_ref(gitdir))
        if entry["index"] is None and entry["head"] is None:
            entry["unavailable"] = True
        signature[repo_id] = entry
    return signature


def _resolve_head_ref(gitdir: str) -> str | None:
    """Return the ref file ``HEAD`` points at, or ``None`` when detached.

    A committed repo keeps ``HEAD`` as an unchanging symref while the
    branch ref moves on every commit, so the signature must watch the
    resolved target too.
    """
    try:
        text = Path(gitdir, "HEAD").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("ref:"):
            target = stripped[len("ref:") :].strip()
            if target:
                return os.path.join(gitdir, target)
    return None


def _normalize_probe_errors(errors: Sequence[str]) -> list[str]:
    """Normalize probe errors for fingerprinting: strip, dedupe, sort."""
    return sorted({error.strip() for error in errors if error.strip()})


def compute_evidence_fingerprint(
    *,
    reason: str,
    dirt: Mapping[str, Any],
    affected_repo_ids: Sequence[str],
    probe_errors: Sequence[str],
    dirty_paths_by_repo: Mapping[str, Sequence[str]],
) -> str:
    """Hash the settlement evidence into a stable fingerprint string."""
    canonical = {
        "reason": reason,
        "dirt": {key: dirt[key] for key in sorted(dirt)},
        "affected_repo_ids": sorted(affected_repo_ids),
        "probe_errors": _normalize_probe_errors(probe_errors),
        "dirty_paths": {
            repo_id: sorted(dirty_paths_by_repo[repo_id])
            for repo_id in sorted(dirty_paths_by_repo)
        },
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evidence_from_record(record: Any) -> dict[str, Any] | None:
    """Return the stored evidence block, or ``None`` for older records.

    Older records without the block simply settle once more.
    """
    if record is None:
        return None
    payload = getattr(record, "payload", None)
    if not isinstance(payload, dict):
        return None
    fingerprint = payload.get("evidence_fingerprint")
    signature = payload.get("evidence_stat_signature")
    probed_at = payload.get("probed_at")
    if (
        not isinstance(fingerprint, str)
        or not fingerprint
        or not isinstance(signature, dict)
        or not isinstance(probed_at, (int, float))
    ):
        return None
    return {
        "fingerprint": fingerprint,
        "stat_signature": signature,
        "repos": payload.get("evidence_repos")
        if isinstance(payload.get("evidence_repos"), dict)
        else {},
        "probed_at": float(probed_at),
    }


def check_unchanged_hold(
    *,
    record: Any,
    project_file: str,
    workspace_num: int,
    workflow: str,
    cl_name: str,
    artifacts_timestamp: str,
    pid: int,
    now: float | None = None,
) -> str:
    """Decide whether a later cleanup pass may skip re-settling this hold.

    Returns ``"skip"`` only when every condition holds: the record is still
    an unresolved retain carrying an evidence block, the exact claim still
    holds, every stat signature is unchanged, and ``now - probed_at`` is less
    than the re-probe interval. Returns ``"no_evidence"`` when the record
    predates evidence persistence (settle once more), else ``"resettle"``.

    Reads the claim file only; no git subprocess, snapshot, pin call, record
    write, or notification happens here.
    """
    from sase.running_field import get_claimed_workspaces

    current = evidence_now() if now is None else now
    if record is None or not getattr(record, "unresolved", False):
        return "resettle"
    evidence = _evidence_from_record(record)
    if evidence is None:
        return "no_evidence"
    try:
        claims = get_claimed_workspaces(project_file)
    except OSError:
        return "resettle"
    held = any(
        claim.workspace_num == workspace_num
        and claim.workflow == workflow
        and (claim.cl_name or "") == (cl_name or "")
        and (claim.artifacts_timestamp or "") == (artifacts_timestamp or "")
        and claim.pid == pid
        for claim in claims
    )
    if not held:
        return "resettle"
    stored_signature = evidence["stat_signature"]
    stored_repos = evidence["repos"]
    if not isinstance(stored_repos, dict) or not stored_repos:
        return "resettle"
    current_signature = compute_stat_signature(
        [(repo_id, str(path)) for repo_id, path in stored_repos.items()]
    )
    if current_signature != stored_signature:
        return "resettle"
    if current - evidence["probed_at"] >= REPROBE_INTERVAL_SECONDS:
        return "resettle"
    return "skip"


def read_notify_state(artifacts_dir: str | Path | None) -> dict[str, Any]:
    """Read the notify-state marker; missing or malformed data is empty."""
    if not artifacts_dir:
        return {}
    try:
        raw = (Path(artifacts_dir) / NOTIFY_STATE_LOCATOR).read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def write_notify_state(
    artifacts_dir: str | Path | None, state: Mapping[str, Any]
) -> None:
    """Persist the notify-state marker (best effort, never raises)."""
    if not artifacts_dir:
        return
    try:
        from sase.core.atomic_json import write_json_marker_atomic

        write_json_marker_atomic(
            Path(artifacts_dir) / NOTIFY_STATE_LOCATOR, dict(state)
        )
    except Exception:  # noqa: BLE001 - marker writes are best effort
        return


def describe_evidence_change(
    *,
    old_reason: str | None,
    old_affected: Sequence[str],
    new_reason: str,
    new_affected: Sequence[str],
) -> str:
    """Summarize what changed between the last notified hold and now."""
    parts: list[str] = []
    if old_reason and old_reason != new_reason:
        parts.append(f"reason changed from {old_reason} to {new_reason}")
    old_set = {item for item in old_affected if item}
    new_set = {item for item in new_affected if item}
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    if added:
        parts.append(f"now affecting: {', '.join(added)}")
    if removed:
        parts.append(f"cleared: {', '.join(removed)}")
    if not parts:
        parts.append("evidence changed")
    return "; ".join(parts)


__all__ = [
    "HEARTBEAT_INTERVAL_SECONDS",
    "NOTIFY_STATE_LOCATOR",
    "REPROBE_INTERVAL_SECONDS",
    "check_unchanged_hold",
    "evidence_now",
    "compute_evidence_fingerprint",
    "compute_stat_signature",
    "describe_evidence_change",
    "read_notify_state",
    "write_notify_state",
]
