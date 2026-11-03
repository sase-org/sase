"""Best-effort evidence and snapshots for the hijack stop protocol."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from sase.agent.hijack._stop_models import HijackTarget, StopDeps, read_json_dict


def attach_evidence(hijack_id: str, evidence: dict[str, Any]) -> None:
    """Merge best-effort evidence fields into the record without a transition.

    Evidence is data, not state: the merge re-reads under the record lock and
    rewrites data fields at the same revision so the pending ``confirmed_stop``
    CAS still observes exactly one winner.
    """

    from sase.agent.hijack import ledger
    from sase.notification_gates.durability import atomic_write_json, file_lock

    allowed = {
        "run_duration_seconds",
        "last_tool",
        "last_tool_age_seconds",
        "repo_diffs",
        "snapshots",
        "stale_lock_files",
        "error",
    }
    payload = {key: value for key, value in evidence.items() if key in allowed}
    if not payload:
        return
    path = ledger.hijack_record_path(hijack_id)
    with file_lock(ledger.hijack_record_lock_path(hijack_id), timeout=10.0):
        current = ledger.read_hijack_record_payload(path)
        if current is None:
            raise RuntimeError(f"hijack record {hijack_id} disappeared")
        current.update(payload)
        atomic_write_json(path, current)


def collect_evidence(target: HijackTarget, *, deps: StopDeps) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    now = deps.now() if deps.now is not None else time.time()
    if target.run_started_at is not None:
        evidence["run_duration_seconds"] = max(0.0, now - target.run_started_at)
    last_tool, last_tool_age = _read_last_tool(target.artifacts_dir, now=now)
    if last_tool is not None:
        evidence["last_tool"] = last_tool
    if last_tool_age is not None:
        evidence["last_tool_age_seconds"] = last_tool_age
    repo_roots = _evidence_repo_roots(target)
    diffs: list[dict[str, Any]] = []
    stale_locks: list[str] = []
    for root in repo_roots:
        stats = _git_diff_stats(root)
        if stats is not None:
            diffs.append({"repo": root, **stats})
        lock = _stale_index_lock(root)
        if lock is not None:
            stale_locks.append(lock)
    evidence["repo_diffs"] = diffs
    evidence["stale_lock_files"] = stale_locks
    return evidence


def _evidence_repo_roots(target: HijackTarget) -> list[str]:
    roots: list[str] = []
    if target.workspace_dir:
        toplevel = _git_repo_toplevel(target.workspace_dir)
        if toplevel is not None:
            roots.append(toplevel)
    meta = read_json_dict(Path(target.artifacts_dir) / "agent_meta.json") or {}
    for key in ("opened_repos", "linked_repos", "sidecar_repos", "repo_roots"):
        value = meta.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, str) or not entry:
                continue
            toplevel = _git_repo_toplevel(entry)
            if toplevel is not None and toplevel not in roots:
                roots.append(toplevel)
    return roots


def capture_snapshots(
    target: HijackTarget, *, deps: StopDeps
) -> tuple[list[dict[str, Any]], str | None]:
    snapshot_repo = deps.snapshot_repo
    if snapshot_repo is None:
        from sase.workspace_provider._snapshot_capture_source import (
            snapshot_git_repo as _snapshot_git_repo,
        )

        snapshot_repo = _snapshot_git_repo
    if target.workspace_dir is None or target.workspace_num is None:
        return [], None
    snapshots: list[dict[str, Any]] = []
    errors: list[str] = []
    for root in _evidence_repo_roots(target):
        try:
            record = snapshot_repo(
                root,
                workspace_dir=target.workspace_dir,
                workspace_num=int(target.workspace_num),
                label=f"hijack-{target.name}",
                reason="agent hijack",
            )
        except Exception as exc:
            errors.append(f"{root}: {exc}")
            continue
        if record is None:
            continue
        snapshots.append(
            {
                "repo": root,
                "reference": str(
                    getattr(record, "snapshot_id", "") or getattr(record, "head", "")
                ),
                "fingerprint": str(getattr(record, "worktree_tree", "")),
            }
        )
    return snapshots, "; ".join(errors) if errors else None


def format_diff_summary(record: dict[str, Any]) -> str:
    diffs = record.get("repo_diffs")
    if not isinstance(diffs, list) or not diffs:
        return ""
    files = 0
    insertions = 0
    deletions = 0
    for entry in diffs:
        if not isinstance(entry, dict):
            continue
        try:
            files += int(entry.get("files_changed") or 0)
            insertions += int(entry.get("insertions") or 0)
            deletions += int(entry.get("deletions") or 0)
        except (TypeError, ValueError):
            continue
    if files == 0:
        return ""
    return f"{files} files +{insertions} \u2212{deletions}"


def _git_repo_toplevel(path: str) -> str | None:
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


def _git_diff_stats(root: str) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            ["git", "-C", root, "diff", "--numstat", "HEAD", "--"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    files_changed = 0
    insertions = 0
    deletions = 0
    binary_files = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted = parts[0], parts[1]
        files_changed += 1
        if added == "-" or deleted == "-":
            binary_files += 1
            continue
        try:
            insertions += int(added)
            deletions += int(deleted)
        except ValueError:
            continue
    try:
        status = subprocess.run(
            ["git", "-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        status = None
    untracked = 0
    if status is not None and status.returncode == 0:
        untracked = sum(
            1 for line in status.stdout.splitlines() if line.startswith("??")
        )
    if files_changed == 0 and untracked == 0:
        return None
    return {
        "files_changed": files_changed + untracked,
        "insertions": insertions,
        "deletions": deletions,
        "binary_files": binary_files,
    }


def _stale_index_lock(root: str) -> str | None:
    candidate = Path(root) / ".git" / "index.lock"
    try:
        if candidate.is_file():
            return str(candidate)
    except OSError:
        return None
    return None


def _read_last_tool(
    artifacts_dir: str, *, now: float
) -> tuple[str | None, float | None]:
    try:
        from sase.ace.tui.llm_calls._parser import read_tool_call_file

        entries = read_tool_call_file(
            Path(artifacts_dir) / "tool_calls.jsonl", Path(artifacts_dir), 0
        )
    except Exception:
        return None, None
    if not entries:
        return None, None
    last = entries[-1]
    name = last.tool_name or last.event or None
    age: float | None = None
    try:
        recorded = last._recorded_at_sort
        age = max(0.0, now - recorded.timestamp())
    except Exception:
        age = None
    return name, age


__all__ = [
    "attach_evidence",
    "capture_snapshots",
    "collect_evidence",
    "format_diff_summary",
]
