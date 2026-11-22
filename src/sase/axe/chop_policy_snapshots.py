"""Host-side snapshots consumed by the Rust chop policy engine."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.agent.running import list_running_agents
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)

from .config import ChopConfig

_GIT_TIMEOUT_SECONDS = 15

#: ProjectSpec suffixes whose fs-trigger token ignores the RUNNING block.
_PROJECT_SPEC_SUFFIXES = (".sase", ".gp")

#: ``(path, mtime_ns, ctime_ns, size, inode) -> digest`` for watched
#: ProjectSpecs. Preflight runs in the long-lived routine process, so an
#: unchanged ProjectSpec is read and hashed once, not on every tick.
_RUNNING_FREE_DIGESTS: dict[tuple[str, int, int, int, int], str] = {}
_RUNNING_FREE_DIGEST_CAP = 512


def check_chop_trigger_runtime(chop: ChopConfig) -> str | None:
    """Return a doctor error for an unusable trigger, otherwise ``None``."""
    provider = chop.trigger.get("provider")
    if provider == "git.commits_since":
        project = str(chop.trigger.get("project") or "")
        record = _resolve_chop_git_project(project)
        if record is None:
            return f"project ref {project!r} does not match a registered SASE project"
        if not record.workspace_dir:
            return f"project {project!r} has no primary workspace"
        try:
            run_git(Path(record.workspace_dir).expanduser(), "rev-parse", "HEAD")
        except RuntimeError as exc:
            return str(exc)
        return None
    if provider == "fs":
        paths = chop.trigger.get("paths")
        _, error = _compute_fs_trigger_token(paths if isinstance(paths, list) else [])
        if error is not None:
            return f"fs trigger paths could not be read: {error}"
        return None
    return None


def _resolve_chop_git_project(project: str) -> ProjectRecordWire | None:
    """Resolve a trigger project ref without creating or mutating a project."""
    try:
        records = list_project_records(
            sase_projects_dir(), "all", include_home=False, projects_only=True
        )
    except Exception:
        return None

    raw = project.removeprefix("#")
    candidates = {raw.casefold()}
    if raw.startswith("git:"):
        candidates.add(raw.removeprefix("git:").casefold())
    if raw.startswith("gh:"):
        owner_repo = raw.removeprefix("gh:")
        candidates.add(f"gh_{owner_repo.replace('/', '__')}".casefold())

    for record in records:
        names = {
            record.project_name,
            effective_project_name(record),
            *record.aliases,
        }
        if any(name.casefold() in candidates for name in names if name):
            return record
    return None


def git_snapshot(
    trigger: dict[str, Any],
    checkpoint: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    project = str(trigger.get("project") or "")
    record = _resolve_chop_git_project(project)
    if record is None or not record.workspace_dir:
        return None, checkpoint

    repo = Path(record.workspace_dir).expanduser()
    head = run_git(repo, "rev-parse", "HEAD")
    checkpoint_key = f"git.commits_since:{project}"
    entries = checkpoint.get("entries")
    raw_entry = entries.get(checkpoint_key) if isinstance(entries, dict) else None
    cursor = str(raw_entry.get("cursor") or "") if isinstance(raw_entry, dict) else ""

    checkpoint_found = False
    if cursor:
        try:
            run_git(repo, "cat-file", "-e", f"{cursor}^{{commit}}")
            count = int(run_git(repo, "rev-list", "--count", f"{cursor}..HEAD"))
            checkpoint_found = True
        except (RuntimeError, ValueError):
            count = int(trigger["threshold"])
    else:
        # Preserve the retired workflows' missing-marker behavior: the first
        # observation fires and establishes a runner-owned checkpoint.
        count = int(trigger["threshold"])

    checkpoint_for_decision = checkpoint
    if cursor and not checkpoint_found:
        checkpoint_for_decision = json.loads(json.dumps(checkpoint))
        decision_entries = checkpoint_for_decision.get("entries")
        if isinstance(decision_entries, dict):
            decision_entries.pop(checkpoint_key, None)

    return (
        {
            "project": project,
            "head": head,
            "commits_since_checkpoint": count,
            "checkpoint_found": checkpoint_found,
        },
        checkpoint_for_decision,
    )


def _resolve_fs_watch_path(raw: str) -> Path:
    """Resolve one fs trigger watch path against the SASE state root.

    Absolute paths (and ``~``) pass through untouched; anything else is
    relative to ``sase_home()`` so a chop can watch its own state files
    without knowing the host's absolute layout.
    """
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else sase_home() / candidate


def _strip_running_block(text: str) -> str:
    """Return ProjectSpec text without its RUNNING block or blank lines.

    The top-level ``RUNNING:`` field holds workspace claims; it ends at the
    first non-blank line that is not indented. Blank lines are dropped too,
    because the claim writers re-normalize the blank lines around the block
    when it appears or disappears.
    """
    kept: list[str] = []
    in_running = False
    for line in text.splitlines():
        if not line.strip():
            continue
        if in_running:
            if line[:1].isspace():
                continue
            in_running = False
        if line.startswith("RUNNING:"):
            in_running = True
            continue
        kept.append(line)
    return "\n".join(kept)


def _running_free_digest(entry: Path, info: Any) -> str:
    """Return a digest of *entry*'s content without its RUNNING claim block.

    Cached by file identity (path, mtime, ctime, size, inode); atomic
    ProjectSpec writes replace the inode, so every real write re-hashes.
    """
    key = (
        str(entry),
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_size,
        info.st_ino,
    )
    cached = _RUNNING_FREE_DIGESTS.get(key)
    if cached is not None:
        return cached
    text = entry.read_text(encoding="utf-8", errors="replace")
    digest = hashlib.blake2b(
        _strip_running_block(text).encode("utf-8"), digest_size=16
    ).hexdigest()
    if len(_RUNNING_FREE_DIGESTS) >= _RUNNING_FREE_DIGEST_CAP:
        _RUNNING_FREE_DIGESTS.clear()
    _RUNNING_FREE_DIGESTS[key] = digest
    return digest


def _fs_watch_token(spec: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Compute one shallow, cheap state token for a single watch spec.

    Returns ``(token, None)`` on success. A path that simply does not exist
    is a valid, stable token state, not an error; only an unreadable path
    (permission denied, a broken symlink loop, ...) returns ``(None, error)``
    so the caller can fail open instead of trusting a partial token.

    Glob matches whose name starts with ``.`` (atomic-write temp files such
    as ``.tmp_*.sase``, editor swap files) are ignored unless the glob's own
    final component starts with ``.``. A matched ProjectSpec file (``*.sase``
    or legacy ``*.gp``) contributes a digest of its content without the
    RUNNING workspace-claim block instead of its mtime and size: agent
    launches, exits, and leases rewrite only that block, and no fs-guarded
    job reads it, so claim churn must not fire them.
    """
    raw_path = str(spec.get("path") or "")
    glob = spec.get("glob")
    base = _resolve_fs_watch_path(raw_path)
    try:
        if glob:
            if not base.is_dir():
                return f"{raw_path}|{glob}:missing", None
            include_hidden = Path(str(glob)).name.startswith(".")
            parts = []
            for entry in sorted(base.glob(str(glob))):
                if not include_hidden and entry.name.startswith("."):
                    continue
                info = entry.stat()
                if entry.is_dir():
                    child_count = sum(1 for _ in entry.iterdir())
                    parts.append(
                        f"{entry.name}:{info.st_mtime_ns}:{info.st_size}:{child_count}"
                    )
                elif entry.suffix in _PROJECT_SPEC_SUFFIXES:
                    parts.append(f"{entry.name}:{_running_free_digest(entry, info)}")
                else:
                    parts.append(f"{entry.name}:{info.st_mtime_ns}:{info.st_size}:")
            return f"{raw_path}|{glob}:" + ",".join(parts), None
        if not base.exists():
            return f"{raw_path}:missing", None
        info = base.stat()
        if base.is_dir():
            child_count = sum(1 for _ in base.iterdir())
            return f"{raw_path}:dir:{info.st_mtime_ns}:{child_count}", None
        return f"{raw_path}:{info.st_mtime_ns}:{info.st_size}", None
    except OSError as exc:
        return None, str(exc)


def _compute_fs_trigger_token(
    paths: Sequence[Any],
) -> tuple[str | None, str | None]:
    """Combine every configured watch spec into one trigger-wide state token.

    Each entry is either a bare path string or a ``{path, glob}`` mapping.
    Fails open on the first unreadable path: returns ``(None, error)`` rather
    than a token built from a partial observation.
    """
    parts: list[str] = []
    for raw_spec in paths:
        spec = raw_spec if isinstance(raw_spec, Mapping) else {"path": raw_spec}
        token, error = _fs_watch_token(spec)
        if error is not None:
            return None, error
        parts.append(token or "")
    return "\x1f".join(parts), None


def fs_snapshot(trigger: dict[str, Any]) -> dict[str, Any]:
    paths = trigger.get("paths")
    token, error = _compute_fs_trigger_token(paths if isinstance(paths, list) else [])
    if error is not None:
        return {"error": error}
    return {"token": token}


def patch_snapshots(context_file: str | None) -> list[dict[str, str]]:
    if not context_file:
        raise ValueError("patch guard requires a job context file")
    try:
        context = json.loads(Path(context_file).read_text(encoding="utf-8"))
        patch_path = Path(str(context["all_patches_file"]))
        rows = json.loads(patch_path.read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load Patch guard snapshot: {exc}") from exc
    if not isinstance(rows, list):
        raise ValueError("Patch guard snapshot must be a list")
    return [
        {"name": str(row.get("name") or ""), "status": str(row.get("status") or "")}
        for row in rows
        if isinstance(row, dict)
    ]


def agent_snapshots(guards: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    include_runner_slots = any(
        guard.get("provider") == "agent_runners" for guard in guards
    )
    snapshots: list[dict[str, Any]] = []
    for agent in list_running_agents():
        if not agent.name:
            continue
        snapshot: dict[str, Any] = {
            "name": str(agent.name),
            "status": str(agent.status),
            "agent_clan": getattr(agent, "agent_clan", None),
            "active": True,
        }
        if include_runner_slots:
            snapshot["holds_runner_slot"] = bool(
                getattr(agent, "holds_runner_slot", None)
            )
        snapshots.append(snapshot)
    return snapshots


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(f"git observation failed for {repo}: {detail}")
    return result.stdout.strip()


__all__ = [
    "agent_snapshots",
    "check_chop_trigger_runtime",
    "fs_snapshot",
    "git_snapshot",
    "patch_snapshots",
    "run_git",
]
