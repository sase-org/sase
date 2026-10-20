"""Agents-sidecar inspection for agent-publication doctor checks."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, TYPE_CHECKING

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.targets import resolve_sync_targets
from sase.agents_sync.v2_io import owner_manifest_path, read_owner_manifest
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.config import require_agent_owner_identity
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    is_disabled_project_lifecycle_state,
)
from sase.doctor._agent_publication import OwnerManifestProblem

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_SIDECAR_GIT_TIMEOUT_SECONDS = 10.0


def outbox_sidecar_states(
    context: DoctorContext,
    project_keys: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    """Inspect each outbox project's hidden agents clone (read-only, best-effort).

    Reports commits ahead of/behind upstream, a rebase in progress, untracked
    ``files/objects``, and dirty ``prompts/`` or ``artifacts/``. Any failure
    degrades to an ``unavailable`` entry: doctor must never fail because a
    sidecar clone is wedged.
    """

    if not project_keys:
        return ()
    try:
        require_agent_owner_identity()
    except (RuntimeError, ValueError):
        return ()
    try:
        selection = resolve_sync_targets(
            project_keys,
            projects_root=context.sase_home / "projects",
        )
    except Exception:  # noqa: BLE001 - doctor isolates target resolution.
        return ()
    states: list[dict[str, Any]] = []
    for target in selection.targets:
        states.append(
            _sidecar_state(target.project_key, target.project, target.sidecar_path)
        )
    return tuple(states)


def _sidecar_state(
    project_key: str, project: str, sidecar_path: Path
) -> dict[str, Any]:
    """Read one hidden clone's sync state, degrading to ``unavailable``."""

    base: dict[str, Any] = {
        "project_key": project_key,
        "project": project,
        "sidecar_path": str(sidecar_path),
    }
    try:
        if not (sidecar_path / ".git").exists():
            return {**base, "status": "missing"}
        git_dir_result = _sidecar_git(
            sidecar_path, ["rev-parse", "--git-dir"], timeout=10.0
        )
        git_dir = Path(git_dir_result.stdout.strip())
        git_dir = git_dir if git_dir.is_absolute() else sidecar_path / git_dir
        ahead, behind = _sidecar_ahead_behind(sidecar_path)
        rebase_in_progress = any(
            (git_dir / marker).exists() for marker in ("rebase-merge", "rebase-apply")
        )
        untracked_objects = _sidecar_porcelain_count(
            sidecar_path, ("files/objects",), untracked_only=True
        )
        dirty_prompts = _sidecar_porcelain_count(
            sidecar_path, ("prompts",), untracked_only=False
        )
        dirty_artifacts = _sidecar_porcelain_count(
            sidecar_path, ("artifacts",), untracked_only=False
        )
    except Exception as exc:  # noqa: BLE001 - doctor never fails on sidecar state.
        return {**base, "status": "unavailable", "error": str(exc)[:200]}
    return {
        **base,
        "status": "ok",
        "ahead": ahead,
        "behind": behind,
        "rebase_in_progress": rebase_in_progress,
        "untracked_objects": untracked_objects,
        "dirty_prompts": dirty_prompts,
        "dirty_artifacts": dirty_artifacts,
    }


def _sidecar_git(
    sidecar_path: Path, args: list[str], *, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one read-only git command in a hidden clone."""

    return subprocess.run(
        ["git", *args],
        cwd=sidecar_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _sidecar_ahead_behind(sidecar_path: Path) -> tuple[int | None, int | None]:
    """Return ``(ahead, behind)`` counts against the upstream, if resolvable."""

    result = _sidecar_git(
        sidecar_path,
        ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
        timeout=_SIDECAR_GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return None, None
    try:
        ahead_raw, behind_raw = result.stdout.strip().split()
        return int(ahead_raw), int(behind_raw)
    except ValueError:
        return None, None


def _sidecar_porcelain_count(
    sidecar_path: Path, pathspecs: tuple[str, ...], *, untracked_only: bool
) -> int | None:
    """Count porcelain entries under *pathspecs* (``None`` when unreadable)."""

    args = ["status", "--porcelain=v1"]
    args.append("--untracked-files=all" if untracked_only else "--untracked-files=no")
    args.extend(("--", *pathspecs))
    result = _sidecar_git(sidecar_path, args, timeout=_SIDECAR_GIT_TIMEOUT_SECONDS)
    if result.returncode != 0:
        return None
    count = 0
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        if untracked_only and not line.startswith("??"):
            continue
        count += 1
    return count


def owner_manifest_problems(
    context: DoctorContext,
    records: tuple[ProjectRecordWire, ...],
) -> tuple[tuple[OwnerManifestProblem, ...], tuple[str, ...]]:
    enabled_projects = tuple(
        record.project_name
        for record in records
        if record.is_project and not is_disabled_project_lifecycle_state(record.state)
    )
    if not enabled_projects:
        return (), ()
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        return (), (f"owner manifest check skipped: owner identity unavailable: {exc}",)
    try:
        selection = resolve_sync_targets(
            enabled_projects,
            projects_root=context.sase_home / "projects",
        )
    except Exception as exc:  # noqa: BLE001 - doctor isolates target resolution.
        return (), (
            "owner manifest check skipped: could not resolve agents sidecar "
            f"targets: {type(exc).__name__}: {exc}",
        )

    problems: list[OwnerManifestProblem] = []
    for target in selection.targets:
        try:
            read_owner_manifest(
                target.sidecar_path,
                owner,
                V2ProjectIdentity(target.project_key, target.project),
            )
        except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
            problems.append(
                OwnerManifestProblem(
                    target.project_key,
                    target.project,
                    target.sidecar_path / owner_manifest_path(owner),
                    str(exc),
                )
            )
    target_errors = tuple(
        f"{outcome.project}: {outcome.error or outcome.skip_reason}"
        for outcome in selection.outcomes
        if outcome.error or outcome.skip_reason
    )
    return tuple(problems), target_errors
