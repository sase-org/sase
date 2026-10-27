"""Low-level Git and locking operations for agents sidecar synchronization."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING

from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.git_lock_retry import try_remove_stale_index_lock
from sase.sdd._push_race import is_retryable_push_race

if TYPE_CHECKING:
    from sase.agents_sync.publication_protection import PublicationProtectionScope

DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS = 10.0
AGENTS_SYNC_AUTO_COMMIT_TYPE = "agents_sync"
_LOCK_TIMEOUT_ENV = "SASE_AGENTS_SYNC_LOCK_TIMEOUT"
_AGENTS_PAYLOAD_PATHS = (
    "README.md",
    "schema.json",
    "users",
    "agents",
    "families",
    "sessions",
)
_LEGACY_MANIFEST_PATH = "manifest.json"


def commit_agents_payload_if_dirty(
    repo: Path,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    *,
    extra_paths: tuple[str, ...] = (),
    protection_scope: PublicationProtectionScope | None = None,
) -> bool | str:
    protection_error = _verify_agents_payload_protection(
        repo,
        git_runner,
        scope=protection_scope,
    )
    if protection_error is not None:
        return protection_error
    payload_paths = _existing_or_tracked_payload_paths(repo, git_runner)
    staged_paths = (
        *payload_paths,
        *(
            path
            for path in extra_paths
            if (repo / path).exists() or _tracked_path(repo, path, git_runner)
        ),
    )
    if not staged_paths:
        return False
    staged = git_runner(
        repo,
        ["add", "--force", "--", *staged_paths],
        op="agents_sync.stage",
    )
    if staged.returncode != 0:
        return agents_git_error("could not stage agents sidecar payload", staged)
    if extra_paths and protection_scope is not None:
        from sase.agents_sync.prompt_archive.protection import (
            unstage_unpublishable_archive_paths,
        )

        withheld = unstage_unpublishable_archive_paths(
            repo,
            git_runner,
            scope=protection_scope,
            archive_paths=extra_paths,
        )
        if withheld is not None:
            return withheld
    dirty = git_runner(
        repo,
        ["diff", "--cached", "--quiet", "--", *staged_paths],
        op="agents_sync.diff_staged",
    )
    if dirty.returncode == 0:
        return False
    if dirty.returncode != 1:
        return agents_git_error(
            "could not inspect staged agents sidecar changes",
            dirty,
        )
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    committed = git_runner(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            apply_auto_commit_type_tag(
                f"chore(agents): sync from {owner.username}.{owner.machine_name}",
                AGENTS_SYNC_AUTO_COMMIT_TYPE,
            ),
        ],
        op="agents_sync.commit",
    )
    if committed.returncode != 0:
        return agents_git_error("could not commit agents sidecar payload", committed)
    return True


def _candidate_rejection_blocked(
    lookup: object,
    scope: PublicationProtectionScope | None,
    relative: str,
    data: bytes,
) -> bool:
    """Return whether a GH013 rejection already blocked these exact bytes.

    A failed lookup never withholds on its own; the fresh scan below still
    decides. Only a durable ``blocked`` record for this exact digest keeps a
    rebuilt candidate out of staging, so recovery cannot replay rejected
    bytes through a path that bypasses snapshot gating.
    """

    if scope is None:
        return False
    import hashlib

    try:
        record = lookup(  # type: ignore[operator]
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=relative,
            sha256=hashlib.sha256(data).hexdigest(),
        )
    except Exception:  # noqa: BLE001 - a failed lookup never authorizes publish.
        return False
    return isinstance(record, dict) and record.get("status") == "blocked"


def _verify_agents_payload_protection(
    repo: Path,
    git_runner: GitRunner,
    *,
    scope: PublicationProtectionScope | None = None,
) -> str | None:
    """Fail-closed pre-stage verification for the agents payload worktree.

    Scans only blobs that differ from ``HEAD`` under the agents payload
    paths — the exact candidate bytes staging would commit — never the whole
    upstream history. Existing dirty or pending worktree content cannot evade
    the guard because any worktree blob that is not already committed is a
    candidate. Returns an error string when any candidate cannot pass a
    complete text scan, or when verification itself cannot run; ``None``
    means every candidate is clean. The reusable scope boundary stays
    available to the prompt-archive staging without imposing
    archive-specific behavior here, so only agents payload paths are
    covered. The protection modules stay out of the TUI startup closure,
    so they are imported here instead of at module top level.
    """

    from sase.agents_sync.publication_protection import (
        MAX_PUBLICATION_SCAN_BYTES,
        lookup_publication_content_record,
        record_publication_bytes_scan,
        scan_publication_bytes,
    )

    max_bytes = scope.max_bytes if scope is not None else MAX_PUBLICATION_SCAN_BYTES
    payload_paths = _existing_or_tracked_payload_paths(repo, git_runner)
    if not payload_paths:
        return None
    candidates = _changed_payload_files(repo, git_runner, payload_paths)
    if isinstance(candidates, str):
        return candidates
    blocked = 0
    for relative in candidates:
        candidate_path = repo / relative
        if candidate_path.is_symlink():
            return (
                "agents payload failed protection verification: "
                f"unsupported symlink at {relative!r}"
            )
        if not candidate_path.is_file():
            # Staging a deletion removes bytes; nothing to scan.
            continue
        try:
            data = candidate_path.read_bytes()
        except OSError:
            return (
                "agents payload failed protection verification: "
                f"could not read {relative!r}"
            )
        if not data:
            continue
        if scope is not None and _candidate_rejection_blocked(
            lookup_publication_content_record, scope, relative, data
        ):
            blocked += 1
            continue
        verdict = scan_publication_bytes(data, max_bytes=max_bytes)
        if scope is not None:
            try:
                record_publication_bytes_scan(
                    scope.project_key,
                    repository_identity=scope.repository_identity,
                    relative_destination=relative,
                    verdict=verdict,
                )
            except Exception:  # noqa: BLE001 - the scan verdict still holds.
                pass
        if not verdict.is_publishable:
            blocked += 1
            continue
        if verdict.sha256 is None:
            blocked += 1
            continue
        try:
            if _sha256_file(candidate_path) != verdict.sha256:
                return (
                    "agents payload failed protection verification: "
                    f"{relative!r} changed between scanning and writing"
                )
        except OSError:
            return (
                "agents payload failed protection verification: "
                f"could not re-read {relative!r}"
            )
    if blocked:
        return (
            "agents payload failed protection verification: "
            f"{blocked} file(s) withheld; see `sase doctor` for details"
        )
    return None


def _changed_payload_files(
    repo: Path,
    git_runner: GitRunner,
    payload_paths: tuple[str, ...],
) -> tuple[str, ...] | str:
    """List worktree blobs under payload paths that differ from ``HEAD``."""

    status = git_runner(
        repo,
        ["status", "--porcelain=v1", "-z", "--", *payload_paths],
        op="agents_sync.protection_status",
    )
    if status.returncode != 0:
        return agents_git_error(
            "could not inspect agents sidecar worktree for protection",
            status,
        )
    changed: list[str] = []
    tokens = status.stdout.split("\0") if status.stdout else []
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            return (
                "agents payload failed protection verification: "
                "could not parse worktree status"
            )
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC" or y in "RC":
            # Rename/copy entries carry the other side as the next token;
            # both sides are candidates because staging touches them.
            if index < len(tokens) and tokens[index]:
                changed.append(tokens[index])
                index += 1
        if x == "U" or y == "U" or x == "A" and y == "A":
            return (
                "agents payload failed protection verification: "
                f"could not verify conflicted file at {path!r}"
            )
        if y == "D":
            # Staging a deletion removes bytes; nothing to scan.
            continue
        if path:
            changed.append(path)
    ignored = git_runner(
        repo,
        [
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            *payload_paths,
        ],
        op="agents_sync.protection_ignored",
    )
    if ignored.returncode != 0:
        return agents_git_error(
            "could not inspect ignored agents sidecar files for protection",
            ignored,
        )
    changed.extend(token for token in ignored.stdout.split("\0") if token)
    return tuple(dict.fromkeys(changed))


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_payload_paths(repo: Path, git_runner: GitRunner) -> tuple[str, ...]:
    if (repo / _LEGACY_MANIFEST_PATH).exists() or _tracked_legacy_manifest(
        repo, git_runner
    ):
        return (_LEGACY_MANIFEST_PATH, *_AGENTS_PAYLOAD_PATHS)
    return _AGENTS_PAYLOAD_PATHS


def _existing_or_tracked_payload_paths(
    repo: Path, git_runner: GitRunner
) -> tuple[str, ...]:
    return tuple(
        path
        for path in _candidate_payload_paths(repo, git_runner)
        if (repo / path).exists() or _tracked_path(repo, path, git_runner)
    )


def _tracked_path(repo: Path, path: str, git_runner: GitRunner) -> bool:
    tracked = git_runner(
        repo,
        ["ls-files", "--", path],
        op="agents_sync.extra_path_tracked",
    )
    return tracked.returncode == 0 and bool(tracked.stdout.strip())


def _tracked_legacy_manifest(repo: Path, git_runner: GitRunner) -> bool:
    tracked = git_runner(
        repo,
        ["ls-files", "--error-unmatch", "--", _LEGACY_MANIFEST_PATH],
        op="agents_sync.legacy_manifest_tracked",
    )
    return tracked.returncode == 0


def clean_agents_payload_worktree(
    repo: Path,
    git_runner: GitRunner,
) -> str | None:
    """Restore the regenerable sidecar payload to ``HEAD``.

    Agents sync shares this clone with ``sase repo open``, so either actor may
    have reset the checkout since the previous operation. Keep recovery
    idempotent and never stash payload writes: every payload path is rebuilt
    from local agent artifacts on each pass, making discarded writes safe to
    regenerate.
    """

    _clear_stale_agents_index_lock(repo, git_runner)
    payload_paths = _existing_or_tracked_payload_paths(repo, git_runner)
    reset = git_runner(
        repo,
        ["reset", "--quiet", "HEAD", "--", *payload_paths],
        op="agents_sync.payload_reset_index",
    )
    if reset.returncode != 0:
        return agents_git_error("could not reset agents sidecar payload index", reset)

    tracked = git_runner(
        repo,
        ["ls-files", "--", *payload_paths],
        op="agents_sync.payload_tracked",
    )
    if tracked.returncode != 0:
        return agents_git_error("could not inspect tracked agents payload", tracked)
    tracked_paths = tuple(tracked.stdout.splitlines())
    restore_roots = tuple(
        root
        for root in payload_paths
        if any(path == root or path.startswith(f"{root}/") for path in tracked_paths)
    )
    if restore_roots:
        restored = git_runner(
            repo,
            ["checkout", "--", *restore_roots],
            op="agents_sync.payload_restore",
        )
        if restored.returncode != 0:
            return agents_git_error(
                "could not restore tracked agents sidecar payload", restored
            )

    cleaned = git_runner(
        repo,
        ["clean", "-fdx", "--", *payload_paths],
        op="agents_sync.payload_clean",
    )
    if cleaned.returncode != 0:
        return agents_git_error(
            "could not remove untracked agents sidecar payload", cleaned
        )
    return None


def _clear_stale_agents_index_lock(repo: Path, git_runner: GitRunner) -> None:
    del git_runner
    try_remove_stale_index_lock(repo)


def ensure_agents_clone(
    target: ProjectTarget,
    *,
    git_runner: GitRunner,
    lock_timeout_seconds: float,
) -> str | None:
    if (target.sidecar_path / ".git").exists():
        return None
    target.sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    clone_lock = target.sidecar_path.parent / ".sase-agents-sync-clone.lock"
    with bounded_agents_lock(clone_lock, lock_timeout_seconds) as acquired:
        if not acquired:
            return "agents sync clone lock is busy"
        if (target.sidecar_path / ".git").exists():
            return None
        if target.sidecar_path.exists():
            return f"agents sidecar path is not a git clone: {target.sidecar_path}"
        temp_root = Path(
            tempfile.mkdtemp(
                prefix=".sase-agents-clone-", dir=target.sidecar_path.parent
            )
        )
        checkout = temp_root / "checkout"
        try:
            cloned = git_runner(
                target.sidecar_path.parent,
                ["clone", "--origin", "origin", target.remote_url, str(checkout)],
                network=True,
                op="agents_sync.clone",
            )
            if cloned.returncode != 0:
                return agents_git_error(
                    "could not clone configured agents sidecar", cloned
                )
            os.replace(checkout, target.sidecar_path)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
    return None


def coerce_owner(owner: AgentOwnerIdentity | str) -> AgentOwnerIdentity:
    if isinstance(owner, AgentOwnerIdentity):
        return owner
    try:
        configured = require_agent_owner_identity()
    except (RuntimeError, ValueError):
        # Compatibility for direct internal/test calls that historically
        # supplied only the machine. Public sync always requires full identity.
        return AgentOwnerIdentity("local", owner)
    return (
        configured
        if configured.machine_name == owner
        else AgentOwnerIdentity(configured.username, owner)
    )


def pull_agents_rebase(
    repo: Path, git_runner: GitRunner, op: str
) -> subprocess.CompletedProcess[str]:
    return git_runner(
        repo,
        ["pull", "--rebase", "--no-autostash"],
        network=True,
        op=op,
    )


def abort_agents_rebase(repo: Path, git_runner: GitRunner) -> str | None:
    git_dir = agents_git_dir(repo, git_runner)
    if not any(
        (git_dir / marker).exists() for marker in ("rebase-merge", "rebase-apply")
    ):
        return None
    result = git_runner(
        repo,
        ["rebase", "--abort"],
        op="agents_sync.rebase_abort",
    )
    return (
        None
        if result.returncode == 0
        else agents_git_error("git rebase --abort failed", result)
    )


def agents_git_dir(repo: Path, git_runner: GitRunner) -> Path:
    result = git_runner(
        repo,
        ["rev-parse", "--git-dir"],
        op="agents_sync.git_dir",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return repo / ".git"
    git_dir = Path(result.stdout.strip())
    return git_dir if git_dir.is_absolute() else repo / git_dir


def agents_ahead_count(repo: Path, git_runner: GitRunner) -> int:
    result = git_runner(
        repo,
        ["rev-list", "--count", "@{upstream}..HEAD"],
        op="agents_sync.ahead",
    )
    try:
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except ValueError:
        return 0


@dataclass(frozen=True, slots=True)
class _SyncLockHolder:
    """One recorded ``bounded_agents_lock`` acquisition."""

    pid: int
    operation: str | None
    agent: str | None
    started_at: float


def _lock_holder_path(path: Path) -> Path:
    return path.parent / f"{path.name}.holder"


def _write_lock_holder(path: Path, *, operation: str | None = None) -> None:
    """Record this process as the lock holder beside the flock file.

    Best-effort: holder tracking must never fail a sync operation.
    """

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        holder = _SyncLockHolder(
            pid=os.getpid(),
            operation=operation,
            agent=os.environ.get("SASE_AGENT_NAME") or None,
            started_at=time.time(),
        )
        tmp_path = path.parent / f"{path.name}.holder.{os.getpid()}.tmp"
        tmp_path.write_text(
            json.dumps(
                {
                    "pid": holder.pid,
                    "operation": holder.operation,
                    "agent": holder.agent,
                    "started_at": holder.started_at,
                }
            ),
            encoding="utf-8",
        )
        os.replace(tmp_path, _lock_holder_path(path))
    except OSError:
        return


def _clear_lock_holder(path: Path) -> None:
    """Remove the holder record written by :func:`_write_lock_holder`."""

    try:
        _lock_holder_path(path).unlink(missing_ok=True)
    except OSError:
        return


def _holder_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def _read_lock_holder(path: Path) -> _SyncLockHolder | None:
    """Return the live holder record, ignoring stale or unreadable ones."""

    try:
        raw = _lock_holder_path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    started_at = data.get("started_at")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(started_at, (int, float)):
        return None
    if not _holder_pid_alive(pid):
        return None
    operation = data.get("operation")
    agent = data.get("agent")
    return _SyncLockHolder(
        pid=pid,
        operation=operation if isinstance(operation, str) else None,
        agent=agent if isinstance(agent, str) else None,
        started_at=float(started_at),
    )


def lock_holder_diagnostic(path: Path) -> str | None:
    """Describe the current lock holder for lock-busy error messages."""

    holder = _read_lock_holder(path)
    if holder is None:
        return None
    age = max(time.time() - holder.started_at, 0.0)
    parts = [f"pid {holder.pid}"]
    if holder.operation:
        parts.append(f"operation {holder.operation!r}")
    if holder.agent:
        parts.append(f"agent {holder.agent!r}")
    parts.append(f"age {age:.0f}s")
    return f"lock holder: {', '.join(parts)}"


@contextmanager
def bounded_agents_lock(
    path: Path,
    timeout_seconds: float,
    *,
    operation: str | None = None,
) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))
        if acquired:
            _write_lock_holder(path, operation=operation)
        yield acquired
    finally:
        if acquired:
            _clear_lock_holder(path)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def is_agents_non_fast_forward(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "[rejected]" in text or is_retryable_push_race(result.stdout, result.stderr)


def agents_git_error(
    prefix: str,
    result: subprocess.CompletedProcess[str],
    cleanup: str | None = None,
) -> str:
    detail = (result.stderr or result.stdout or "unknown git error").strip()
    message = f"{prefix}: {detail}"
    return f"{message}; {cleanup}" if cleanup else message


def configured_agents_lock_timeout() -> float:
    raw = os.environ.get(_LOCK_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS
    return max(value, 0.0)


__all__ = [
    "AGENTS_SYNC_AUTO_COMMIT_TYPE",
    "DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS",
    "abort_agents_rebase",
    "agents_ahead_count",
    "agents_git_dir",
    "agents_git_error",
    "bounded_agents_lock",
    "clean_agents_payload_worktree",
    "coerce_owner",
    "commit_agents_payload_if_dirty",
    "configured_agents_lock_timeout",
    "ensure_agents_clone",
    "is_agents_non_fast_forward",
    "lock_holder_diagnostic",
    "pull_agents_rebase",
]
