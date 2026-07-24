"""Locked pull/integrate/export/commit/push transaction for agents sidecars."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any

from sase.agents_sync.bundles import integrate_foreign_bundles
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.io import read_manifest
from sase.agents_sync.models import (
    AgentsManifest,
    ExportCounts,
    IntegrationCounts,
    ProjectTarget,
    SyncOutcome,
)
from sase.agents_sync.publication import reconcile_agent_hoods
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)

DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS = 2.0
_LOCK_TIMEOUT_ENV = "SASE_AGENTS_SYNC_LOCK_TIMEOUT"


def sync_agents(
    projects: Sequence[str] = (),
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> tuple[SyncOutcome, ...]:
    """Synchronize every selected project without cross-project fail-fast."""

    selection = resolve_sync_targets(projects)
    outcomes = list(selection.outcomes)
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        outcomes.extend(
            SyncOutcome(
                target.project_key,
                target.project,
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(outcomes, key=lambda item: item.project_key))

    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    for target in selection.targets:
        pending_publications: tuple[Any, ...] = ()
        try:
            from sase.agents_sync.publication_outbox import (
                acknowledge_agent_publications,
                list_agent_publications,
            )

            pending_publications = list_agent_publications(target.project_key)
            outcome = _sync_project(
                target,
                owner,
                git_runner=git_runner,
                lock_timeout_seconds=timeout,
            )
            if outcome.ok and outcome.skip_reason is None and pending_publications:
                acknowledge_agent_publications(
                    target.project_key,
                    (item.logical_key for item in pending_publications),
                )
            outcomes.append(outcome)
        except Exception as exc:  # noqa: BLE001 - per-project isolation contract
            outcomes.append(
                SyncOutcome(
                    target.project_key,
                    target.project,
                    error=f"agents sync failed: {exc}",
                )
            )

    result = tuple(sorted(outcomes, key=lambda item: item.project_key))
    try:
        from sase.agents_sync.status import rewrite_agents_sync_status_after_sync

        rewrite_agents_sync_status_after_sync(projects)
    except Exception:
        # A cache write must never turn an already-complete sync into failure.
        pass
    return result


def _sync_project(
    target: ProjectTarget,
    owner: AgentOwnerIdentity | str,
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float = DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS,
) -> SyncOutcome:
    """Run one project's bounded mutation transaction."""

    resolved_owner = _coerce_owner(owner)

    if not target.primary_checkout.is_dir():
        return _error(target, "primary checkout does not exist")
    clone_error = ensure_agents_clone(
        target,
        git_runner=git_runner,
        lock_timeout_seconds=lock_timeout_seconds,
    )
    if clone_error is not None:
        if clone_error == "agents sync clone lock is busy":
            return _skip(target, clone_error)
        return _error(target, clone_error)

    lock_path = (
        agents_git_dir(target.sidecar_path, git_runner) / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, lock_timeout_seconds) as acquired:
        if not acquired:
            return _skip(target, "agents sync lock is busy")
        return _sync_project_locked(target, resolved_owner, git_runner)


def _sync_project_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> SyncOutcome:
    repo = target.sidecar_path
    pulled = pull_agents_rebase(repo, git_runner, "agents_sync.pull")
    if pulled.returncode != 0:
        cleanup = abort_agents_rebase(repo, git_runner)
        return _error(
            target,
            agents_git_error("git pull --rebase failed", pulled, cleanup),
        )

    try:
        integrated, exported = _integrate_export_pass(target, repo, owner, git_runner)
    except Exception as exc:  # noqa: BLE001 - project-scoped format/import error
        return _error(target, str(exc), pulled=True)

    committed_result = commit_agents_payload_if_dirty(repo, owner, git_runner)
    if isinstance(committed_result, str):
        return _error(target, committed_result, pulled=True)
    committed = committed_result
    should_push = committed or agents_ahead_count(repo, git_runner) > 0
    if not should_push:
        return SyncOutcome(
            target.project_key,
            target.project,
            pulled=True,
            integrated=integrated.integrated,
            refreshed=integrated.refreshed,
            exported=exported.exported,
            export_refreshed=exported.refreshed,
            hoods_published=exported.hoods_published,
            hoods_refreshed=exported.hoods_refreshed,
            hoods_unchanged=exported.hoods_unchanged,
            families_published=exported.families_published,
            runs_published=exported.runs_published,
            committed=False,
            diagnostics=exported.diagnostics,
        )

    pushed = git_runner(
        repo,
        ["push"],
        network=True,
        op="agents_sync.push",
    )
    if pushed.returncode == 0:
        return SyncOutcome(
            target.project_key,
            target.project,
            pulled=True,
            integrated=integrated.integrated,
            refreshed=integrated.refreshed,
            exported=exported.exported,
            export_refreshed=exported.refreshed,
            hoods_published=exported.hoods_published,
            hoods_refreshed=exported.hoods_refreshed,
            hoods_unchanged=exported.hoods_unchanged,
            families_published=exported.families_published,
            runs_published=exported.runs_published,
            committed=committed,
            pushed=True,
            push_attempts=1,
            diagnostics=exported.diagnostics,
        )
    if not is_agents_non_fast_forward(pushed):
        return _error(
            target,
            agents_git_error("git push failed", pushed),
            pulled=True,
            integrated=integrated.integrated,
            refreshed=integrated.refreshed,
            exported=exported.exported,
            export_refreshed=exported.refreshed,
            hoods_published=exported.hoods_published,
            hoods_refreshed=exported.hoods_refreshed,
            hoods_unchanged=exported.hoods_unchanged,
            families_published=exported.families_published,
            runs_published=exported.runs_published,
            committed=committed,
            push_attempts=1,
            diagnostics=exported.diagnostics,
        )

    if committed:
        dropped = git_runner(
            repo,
            ["reset", "--hard", "HEAD^"],
            op="agents_sync.retry_drop_commit",
        )
        if dropped.returncode != 0:
            return _error(
                target,
                agents_git_error(
                    "could not prepare rejected sync commit for retry", dropped
                ),
                pulled=True,
                push_attempts=1,
            )

    repulled = pull_agents_rebase(repo, git_runner, "agents_sync.retry_pull")
    if repulled.returncode != 0:
        cleanup = abort_agents_rebase(repo, git_runner)
        return _error(
            target,
            agents_git_error("git pull --rebase retry failed", repulled, cleanup),
            pulled=True,
            push_attempts=1,
        )
    try:
        retry_integrated, retry_exported = _integrate_export_pass(
            target, repo, owner, git_runner
        )
    except Exception as exc:  # noqa: BLE001 - project-scoped retry error
        return _error(
            target,
            f"sync recompute after push rejection failed: {exc}",
            pulled=True,
            push_attempts=1,
        )
    retry_commit_result = commit_agents_payload_if_dirty(repo, owner, git_runner)
    if isinstance(retry_commit_result, str):
        return _error(
            target,
            retry_commit_result,
            pulled=True,
            push_attempts=1,
        )
    retry_committed = retry_commit_result
    retry_push = git_runner(
        repo,
        ["push"],
        network=True,
        op="agents_sync.retry_push",
    )
    all_diagnostics = tuple(
        dict.fromkeys((*exported.diagnostics, *retry_exported.diagnostics))
    )
    if retry_push.returncode != 0:
        return _error(
            target,
            agents_git_error("git push retry failed", retry_push),
            pulled=True,
            integrated=max(integrated.integrated, retry_integrated.integrated),
            refreshed=max(integrated.refreshed, retry_integrated.refreshed),
            exported=max(exported.exported, retry_exported.exported),
            export_refreshed=max(exported.refreshed, retry_exported.refreshed),
            hoods_published=max(
                exported.hoods_published, retry_exported.hoods_published
            ),
            hoods_refreshed=max(
                exported.hoods_refreshed, retry_exported.hoods_refreshed
            ),
            hoods_unchanged=max(
                exported.hoods_unchanged, retry_exported.hoods_unchanged
            ),
            families_published=max(
                exported.families_published,
                retry_exported.families_published,
            ),
            runs_published=max(exported.runs_published, retry_exported.runs_published),
            committed=retry_committed,
            push_attempts=2,
            diagnostics=all_diagnostics,
        )
    return SyncOutcome(
        target.project_key,
        target.project,
        pulled=True,
        integrated=max(integrated.integrated, retry_integrated.integrated),
        refreshed=max(integrated.refreshed, retry_integrated.refreshed),
        exported=max(exported.exported, retry_exported.exported),
        export_refreshed=max(exported.refreshed, retry_exported.refreshed),
        hoods_published=max(exported.hoods_published, retry_exported.hoods_published),
        hoods_refreshed=max(exported.hoods_refreshed, retry_exported.hoods_refreshed),
        hoods_unchanged=max(exported.hoods_unchanged, retry_exported.hoods_unchanged),
        families_published=max(
            exported.families_published, retry_exported.families_published
        ),
        runs_published=max(exported.runs_published, retry_exported.runs_published),
        committed=retry_committed,
        pushed=True,
        push_attempts=2,
        diagnostics=all_diagnostics,
    )


def _integrate_export_pass(
    target: ProjectTarget,
    repo: Path,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> tuple[IntegrationCounts, ExportCounts]:
    legacy_manifest_path = repo / "manifest.json"
    legacy_manifest = (
        read_manifest(legacy_manifest_path)
        if legacy_manifest_path.is_file()
        else AgentsManifest()
    )
    integrated = integrate_foreign_bundles(
        target,
        repo,
        legacy_manifest,
        owner.machine_name,
    )
    published = reconcile_agent_hoods(
        target,
        repo,
        identity=AgentIdentitySnapshot(owner),
        git_runner=git_runner,
    )
    return integrated, ExportCounts(
        diagnostics=published.diagnostics,
        hoods_published=published.hoods_published,
        hoods_refreshed=published.hoods_refreshed,
        hoods_unchanged=published.hoods_unchanged,
        families_published=published.families_published,
        runs_published=published.runs_published,
    )


def commit_agents_payload_if_dirty(
    repo: Path,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> bool | str:
    status = git_runner(
        repo,
        [
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "README.md",
            "schema.json",
            "users",
            "agents",
            "families",
        ],
        op="agents_sync.status_payload",
    )
    if status.returncode != 0:
        return agents_git_error("could not inspect agents sidecar changes", status)
    if not status.stdout.strip():
        return False
    staged = git_runner(
        repo,
        ["add", "--", "README.md", "schema.json", "users", "agents", "families"],
        op="agents_sync.stage",
    )
    if staged.returncode != 0:
        return agents_git_error("could not stage agents sidecar payload", staged)
    committed = git_runner(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            f"chore(agents): sync from {owner.username}.{owner.machine_name}",
        ],
        op="agents_sync.commit",
    )
    if committed.returncode != 0:
        return agents_git_error("could not commit agents sidecar payload", committed)
    return True


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


def _coerce_owner(owner: AgentOwnerIdentity | str) -> AgentOwnerIdentity:
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


@contextmanager
def bounded_agents_lock(path: Path, timeout_seconds: float) -> Iterator[bool]:
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
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def is_agents_non_fast_forward(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "non-fast-forward" in text or "fetch first" in text or "[rejected]" in text


def agents_git_error(
    prefix: str,
    result: subprocess.CompletedProcess[str],
    cleanup: str | None = None,
) -> str:
    detail = (result.stderr or result.stdout or "unknown git error").strip()
    message = f"{prefix}: {detail}"
    return f"{message}; {cleanup}" if cleanup else message


def _error(target: ProjectTarget, error: str, **kwargs: Any) -> SyncOutcome:
    return SyncOutcome(target.project_key, target.project, error=error, **kwargs)


def _skip(target: ProjectTarget, reason: str) -> SyncOutcome:
    return SyncOutcome(target.project_key, target.project, skip_reason=reason)


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
    "DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS",
    "abort_agents_rebase",
    "agents_ahead_count",
    "agents_git_dir",
    "agents_git_error",
    "bounded_agents_lock",
    "commit_agents_payload_if_dirty",
    "configured_agents_lock_timeout",
    "ensure_agents_clone",
    "is_agents_non_fast_forward",
    "pull_agents_rebase",
    "sync_agents",
]
